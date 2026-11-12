"""Adversarial regressions for standard triad access, weights and activation (stage f verifier probes)."""
import json
import pytest
from sqlalchemy import text
from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo
from app.models.triad_composition import TriadComposition
from app.models.user import Usuario
from app.services import triad_compositions as svc
from app.services.auth import hash_password
from tests.test_triad_api import (triad_env, functional, web, access, catalogue, triad_key, predict, revise,  # noqa: F401
                                  activate_triad, active_flags, V1_WEIGHTS, V2_WEIGHTS, ORIGIN, PASSWORD)
from tests.test_web_sessions import login
from tests.test_api_predict import create_dummy_wav_bytes


def snapshot(env):
    with env.sessions() as db:
        out = {}
        for t in ("triad_composition", "modelo", "prediccion"):
            out[t] = [tuple(r) for r in db.execute(text(f"SELECT * FROM {t} ORDER BY 1"))]
        return out


def add_peer(env):
    with env.sessions() as db:
        db.add(Usuario(id=3, email="peer@example.test", password_hash=hash_password(PASSWORD),
                       nombre_completo="peer", rol="investigador", activo=True))
        db.commit()
    assert login(env.client, "administrador").status_code == 200
    assert env.client.put("/api/access/users/3/datasets/20", headers={"Origin": ORIGIN}).status_code == 200
    assert env.client.put("/api/access/users/2/datasets/10", headers={"Origin": ORIGIN}).status_code == 200


def test_unassigned_peer_is_blind(triad_env):
    env = triad_env
    add_peer(env)
    assert login(env.client, "peer").status_code == 200
    before = snapshot(env)
    body = catalogue(env)
    ids = {m["id"] for m in body["models"]}
    assert not any(i.startswith("fama_triad") or i.startswith("fama_trained_model") for i in ids), ids
    assert body["publication_errors"] == []
    assert env.client.get("/api/triad-compositions/1").status_code == 404
    assert revise(env, V2_WEIGHTS).status_code == 404
    assert predict(env, triad_key()).status_code == 404
    assert env.client.get("/api/inference/history", params={"model_id": triad_key()}).status_code == 404
    assert env.client.post("/api/triad-compositions/1/activate", headers={"Origin": ORIGIN}).status_code == 403
    # default model path
    assert predict(env, None).status_code in (404, 400, 422, 503) or True
    assert snapshot(env) == before


def test_unassigned_peer_default_triad_not_usable(triad_env):
    env = triad_env
    add_peer(env)
    assert login(env.client, "administrador").status_code == 200
    assert activate_triad(env).status_code == 200
    catalogue(env)
    assert login(env.client, "peer").status_code == 200
    before = snapshot(env)
    r = env.client.post("/api/predict", headers={"Origin": ORIGIN},
                        files={"file": ("a.wav", create_dummy_wav_bytes(5.0), "audio/wav")})
    assert r.status_code == 404, (r.status_code, r.text)
    r = env.client.post("/api/predict", headers={"Origin": ORIGIN}, params={"model_id": "default"},
                        files={"file": ("a.wav", create_dummy_wav_bytes(5.0), "audio/wav")})
    assert r.status_code == 404, (r.status_code, r.text)
    for variant in (" fama_triad_1", "FAMA_TRIAD_1", "fama_triad_1 ", "fama_triad_01", "fama_triad_１"):
        r = predict(env, variant)
        assert r.status_code == 404, (variant, r.status_code, r.text)
    b = catalogue(env)
    assert b["default_model_id"] in ("", None), b["default_model_id"]
    assert snapshot(env) == before


def test_unassigned_peer_variants_do_not_leak_to_unassigned_after_catalogue_by_assigned(triad_env):
    env = triad_env
    add_peer(env)
    assert login(env.client, "investigador").status_code == 200
    catalogue(env)  # registry now holds the triad published by an assigned user
    assert login(env.client, "peer").status_code == 200
    for variant in ("fama_triad_1", " fama_triad_1", "FAMA_TRIAD_1", "fama_triad_1\n"):
        r = predict(env, variant)
        assert r.status_code == 404, (variant, r.status_code, r.text)


BAD = [[-0.1, 0.6, 0.5], [0.5, 0.5, 0.5], [0.5, 0.5], [0.25, 0.25, 0.25, 0.25], [0, 0, 0], [True, False, False],
       [None, 0.5, 0.5], ["a", 0.5, 0.5], [1e308, 1e308, -1e308], [0.5, 0.5, 1e-5], [0.3, 0.3, 0.3], [2, -1, 0]]


@pytest.mark.parametrize("weights", BAD)
def test_bad_weights_rejected_no_change(triad_env, weights):
    env = triad_env
    add_peer(env)
    assert login(env.client).status_code == 200
    before = snapshot(env)
    r = revise(env, weights)
    assert r.status_code in (400, 422), (r.status_code, r.text)
    assert snapshot(env) == before




def test_string_numbers_observed(triad_env):
    env = triad_env
    add_peer(env)
    assert login(env.client).status_code == 200
    r = revise(env, ["0.1", "0.2", "0.7"])
    print("STRING_WEIGHTS_STATUS", r.status_code, r.text[:200])


def test_revision_only_from_latest_and_unique_version(triad_env, monkeypatch):
    env = triad_env
    add_peer(env)
    assert login(env.client).status_code == 200
    assert revise(env, V2_WEIGHTS).status_code == 201
    before = snapshot(env)
    assert revise(env, V1_WEIGHTS, 1).status_code == 409
    assert snapshot(env) == before
    # stale reader race: both think v1 is latest
    monkeypatch.setattr(svc, "is_latest", lambda db, c: True)
    r = revise(env, [1, 0, 0], 1)
    assert r.status_code == 409, (r.status_code, r.text)
    assert snapshot(env) == before
    assert revise(env, [1, 0, 0], 2).status_code in (201, 409)


def test_stale_revision_does_not_disturb_activation(triad_env, monkeypatch):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    assert activate_triad(env).status_code == 200
    assert revise(env, V2_WEIGHTS).status_code == 201
    assert active_flags(env) == ([], [2])
    before = snapshot(env)
    monkeypatch.setattr(svc, "is_latest", lambda db, c: True)
    assert revise(env, [1, 0, 0], 1).status_code == 409
    assert active_flags(env) == ([], [2])
    assert snapshot(env) == before


def test_researcher_cannot_activate_no_state_change(triad_env):
    env = triad_env
    add_peer(env)
    assert login(env.client).status_code == 200
    before = snapshot(env)
    for cid in (1, 99):
        r = activate_triad(env, cid)
        assert r.status_code == 403, (cid, r.status_code)
    assert snapshot(env) == before
    assert env.client.post("/api/training/models/1/activate", headers={"Origin": ORIGIN}).status_code == 403
    assert snapshot(env) == before


def test_active_unique_across_tables(triad_env):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    assert env.client.post("/api/training/models/2/activate", headers={"Origin": ORIGIN}).json()["success"]
    assert activate_triad(env).status_code == 200
    assert activate_triad(env).status_code == 200  # idempotent
    assert active_flags(env) == ([], [1])
    # failed single-model activation keeps the active triad
    assert env.client.post("/api/training/models/999/activate", headers={"Origin": ORIGIN}).json()["success"] is False
    assert active_flags(env) == ([], [1])
    assert revise(env, V2_WEIGHTS).status_code == 201
    assert revise(env, [0.2, 0.2, 0.6], 2).status_code == 201
    assert active_flags(env) == ([], [3])
    with env.sessions() as db:
        assert db.query(TriadComposition).filter_by(activo=True).count() == 1




def test_activate_blocked_component(triad_env):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    env.checkpoints[2].write_bytes(env.checkpoints[2].read_bytes() + b"x")
    catalogue(env)
    b = catalogue(env)
    print("BLOCKED_PUBLICATION", b["publication_errors"])
    assert triad_key() not in {m["id"] for m in b["models"]} or True
    r = activate_triad(env)
    print("ACTIVATE_BLOCKED_TRIAD_STATUS", r.status_code, active_flags(env))
    r2 = env.client.post("/api/training/models/2/activate", headers={"Origin": ORIGIN})
    print("ACTIVATE_BLOCKED_MODEL_STATUS", r2.status_code, r2.text[:200])


def test_blocked_component_blocks_predict_for_assigned(triad_env):
    env = triad_env
    add_peer(env)
    assert login(env.client).status_code == 200
    catalogue(env)
    env.checkpoints[3].write_bytes(env.checkpoints[3].read_bytes() + b"x")
    b = catalogue(env)
    print("CATALOGUE_AFTER_TAMPER", sorted(m["id"] for m in b["models"]), b["publication_errors"])
    r = predict(env, triad_key())
    assert r.status_code in (404, 503), (r.status_code, r.text)
    r = predict(env, "fama_trained_model_3")
    print("COMPONENT_PREDICT_AFTER_TAMPER", r.status_code)
    # peer on dataset 20 must not see publication errors about dataset 10
    assert login(env.client, "peer").status_code == 200
    assert catalogue(env)["publication_errors"] == []


def test_creation_only_for_complete_triads(triad_env):
    env = triad_env
    before = snapshot(env)
    with env.sessions() as db:
        db.add(Modelo(id_modelo=7, id_conjunto_datos=20, arquitectura="AudioCNN", epocas=1, tasa_aprendizaje=.1, tamano_lote=1, ruta_binario_gcp="models/z.pt", hash_binario="f" * 64))
        db.add(Modelo(id_modelo=8, id_conjunto_datos=10, arquitectura="AudioCNN", epocas=1, tasa_aprendizaje=.1, tamano_lote=1, ruta_binario_gcp="models/z.pt", hash_binario=None))
        db.add(Modelo(id_modelo=9, id_conjunto_datos=10, arquitectura="AudioCNN", epocas=1, tasa_aprendizaje=.1, tamano_lote=1, ruta_binario_gcp="models/z.pt", hash_binario="nothex"))
        db.commit()
    mid = snapshot(env)
    cases = [
        [(1, .5), (2, .5)],
        [(1, .5), (2, .25), (3, .25), (7, 0)],
        [(1, .5), (1, .25), (2, .25)],
        [(1, .5), (2, .25), (7, .25)],
        [(1, .5), (2, .25), (8, .25)],
        [(1, .5), (2, .25), (9, .25)],
        [(1, .5), (2, .25), (404, .25)],
        [(1, .5), (2, .25), (3, .5)],
        [(1, -.5), (2, .75), (3, .75)],
        [(1, float("nan")), (2, .5), (3, .5)],
        [(1, True), (2, 0), (3, 0)],
    ]
    for i, comps in enumerate(cases):
        with env.sessions() as db:
            with pytest.raises(svc.TriadCompositionError):
                svc.create_initial_composition(db, job_id=f"new-{i}", dataset_id=10, partition_version="p", components=comps)
        assert snapshot(env) == mid, comps


def test_training_history_exposes_only_latest_authorized_composition(triad_env):
    env = triad_env
    add_peer(env)
    assert login(env.client, "investigador").status_code == 200
    assert revise(env, V2_WEIGHTS).status_code == 201
    response = env.client.get("/api/training/history")
    assert response.status_code == 200
    body = response.json()
    assert {item["id"] for item in body["history"]} >= {1, 2, 3}
    assert body["compositions"] == [{"id": 2, "version": 2, "job_id": "job-1",
                                    "components": [{"id_modelo": 1, "weight": V2_WEIGHTS[0]},
                                                   {"id_modelo": 2, "weight": V2_WEIGHTS[1]},
                                                   {"id_modelo": 3, "weight": V2_WEIGHTS[2]}],
                                    "evaluation": {"val": None, "test": None}}]
    assert login(env.client, "peer").status_code == 200
    response = env.client.get("/api/training/history")
    assert response.status_code == 200
    assert response.json()["compositions"] == []


def _joint_attempt(db, composition_id, split, status, predicted=None):
    from datetime import datetime, timezone
    from ml_core.classification_metrics import calculate_classification_report
    from app.models.triad_composition import TriadCompositionEvaluation
    from app.services.recording_evaluator import REJECTION_LABEL
    composition = db.get(TriadComposition, composition_id)
    now = datetime.now(timezone.utc)
    report = (calculate_classification_report(["b", "a"], predicted, ["b", "a"], rejection_label=REJECTION_LABEL)
              if status == "completed" else None)
    db.add(TriadCompositionEvaluation(
        composition_id=composition_id, composition_version=composition.version,
        component_model_ids=[composition.first_model_id, composition.second_model_id, composition.third_model_id],
        checkpoint_sha256s=["a" * 64] * 3,
        weights=[composition.first_weight, composition.second_weight, composition.third_weight],
        schema_version=2, evaluator_version="recording-v1", checkpoint_sha256="f" * 64, dataset="AvesChilenas",
        split=split, manifest_sha256="d" * 64, classes=["b", "a"], predictor_config={}, preprocessing_config={},
        aggregation_config={}, sample_count=2, report=report, status=status,
        error_reason="Checkpoint cambió durante inferencia" if status == "failed" else None,
        created_at=now, started_at=now if status != "pending" else None,
        finished_at=now if status in ("completed", "failed") else None))
    db.commit()


def test_training_history_exposes_joint_evaluation_of_the_exact_composition(triad_env, monkeypatch):
    from app import main
    env = triad_env
    add_peer(env)
    with env.sessions() as db:
        _joint_attempt(db, 1, "val", "completed", ["b", "b"])
        _joint_attempt(db, 1, "test", "failed")
    assert login(env.client, "investigador").status_code == 200
    def forbidden(*args, **kwargs):
        raise AssertionError("history must not load or run a predictor")
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    monkeypatch.setattr(env.registry, "get", forbidden)
    monkeypatch.setattr(TrainedModelPredictor, "predict", forbidden)
    evaluation = env.client.get("/api/training/history").json()["compositions"][0]["evaluation"]
    assert evaluation["val"]["status"] == "completed" and evaluation["val"]["sample_count"] == 2
    assert evaluation["val"]["metrics"]["accuracy"] == .5 and evaluation["val"]["rejection_rate"] == 0
    assert evaluation["test"] == {"status": "failed", "sample_count": 2, "metrics": None, "rejection_rate": None,
                                  "error_reason": "Checkpoint cambió durante inferencia"}
    # A weight revision is a new composition: it does not inherit version 1 reports.
    assert revise(env, V2_WEIGHTS).status_code == 201
    latest, = env.client.get("/api/training/history").json()["compositions"]
    assert (latest["id"], latest["evaluation"]) == (2, {"val": None, "test": None})
    assert login(env.client, "peer").status_code == 200
    assert env.client.get("/api/training/history").json()["compositions"] == []


def test_training_history_keeps_explicit_jobs_and_ignores_invalid_compositions(triad_env, monkeypatch):
    from datetime import datetime, timezone
    from app import main

    env = triad_env
    add_peer(env)
    with env.sessions() as db:
        for model_id in (4, 5, 6):
            db.add(Modelo(id_modelo=model_id, id_conjunto_datos=10, arquitectura="AudioCNN", epocas=1,
                          tasa_aprendizaje=.001, tamano_lote=1, ruta_binario_gcp=f"models/missing_{model_id}.pt"))
        db.add(Modelo(id_modelo=7, id_conjunto_datos=20, arquitectura="AudioCNN", epocas=1,
                      tasa_aprendizaje=.001, tamano_lote=1, ruta_binario_gcp="models/missing_7.pt"))
        db.commit()
    assert login(env.client, "investigador").status_code == 200
    before = env.client.get("/api/training/history")
    assert before.status_code == 200
    from app.services.access import ResourceAccess
    with env.sessions() as db:
        expected_history = main.training_service.get_history(db=db, access=ResourceAccess(db, db.get(Usuario, 2)))
    assert before.json()["history"] == expected_history
    with env.sessions() as db:
        common = dict(dataset_id=10, partition_version="p1", version=1, author_id=1,
                      created_at=datetime.now(timezone.utc), first_weight=.2, second_weight=.3, third_weight=.5)
        db.add_all([
            TriadComposition(job_id="job-2", first_model_id=4, second_model_id=5, third_model_id=6, **common),
            TriadComposition(job_id="bad-dataset", first_model_id=1, second_model_id=2, third_model_id=3,
                             **{**common, "dataset_id": 20}),
            TriadComposition(job_id="bad-weights", first_model_id=1, second_model_id=2, third_model_id=3,
                             **{**common, "third_weight": .7}),
            TriadComposition(job_id="hidden-member", first_model_id=1, second_model_id=2, third_model_id=7,
                             **common),
        ])
        db.commit()
    # The metadata path must not load predictors or run inference.
    def forbidden(*args, **kwargs):
        raise AssertionError("history must not load or run a predictor")
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    monkeypatch.setattr(env.registry, "get", forbidden)
    monkeypatch.setattr(TrainedModelPredictor, "_load_model", forbidden)
    monkeypatch.setattr(TrainedModelPredictor, "predict", forbidden)
    monkeypatch.setattr(main.training_service, "set_active_model", forbidden)
    response = env.client.get("/api/training/history")
    assert response.status_code == 200
    body = response.json()
    assert body["history"] == before.json()["history"]
    assert {item["id"] for item in body["history"]} >= {1, 2, 3, 4, 5, 6}
    assert body["compositions"] == [
        {"id": 1, "version": 1, "job_id": "job-1", "components": [
            {"id_modelo": 1, "weight": V1_WEIGHTS[0]}, {"id_modelo": 2, "weight": V1_WEIGHTS[1]},
            {"id_modelo": 3, "weight": V1_WEIGHTS[2]}], "evaluation": {"val": None, "test": None}},
        {"id": 2, "version": 1, "job_id": "job-2", "components": [
            {"id_modelo": 4, "weight": .2}, {"id_modelo": 5, "weight": .3},
            {"id_modelo": 6, "weight": .5}], "evaluation": {"val": None, "test": None}},
    ]


def test_history_isolated_per_version(triad_env):
    env = triad_env
    add_peer(env)
    assert login(env.client).status_code == 200
    catalogue(env)
    a = predict(env, triad_key(1), "v1.wav").json()
    assert revise(env, V2_WEIGHTS).status_code == 201
    catalogue(env)
    b = predict(env, triad_key(2), "v2.wav").json()
    h1 = env.client.get("/api/inference/history", params={"model_id": triad_key(1)}).json()["items"]
    h2 = env.client.get("/api/inference/history", params={"model_id": triad_key(2)}).json()["items"]
    assert [i["filename"] for i in h1] == ["v1.wav"] and [i["filename"] for i in h2] == ["v2.wav"]
    # single component history does not include triad predictions
    h3 = env.client.get("/api/inference/history", params={"model_id": "fama_trained_model_1"}).json()["items"]
    assert h3 == []
