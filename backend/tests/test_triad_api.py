"""Standard triad compositions over authenticated HTTP: catalogue, prediction, history and activation."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import torch
from sqlalchemy.orm import sessionmaker

from app import main
from app.database import get_db
from app.models.dataset import ConjuntoDatos
from app.models.prediction import Prediccion
from app.models.training import Modelo
from app.models.triad_composition import TriadComposition
from app.models.user import Usuario
from app.routes.prediction_history import router as prediction_history_router
from app.routes.triad_compositions import router as triad_router
from app.services import triad_compositions as compositions_service
from app.services.auth import hash_password
from app.services.predictors import trained_predictor
from app.services.registry import ModelRegistry, get_model_registry
from app.services.triad_compositions import create_initial_composition
from tests.schema_support import migrated_engine
from tests.test_api_predict import create_dummy_wav_bytes
from tests.test_resource_access import access, assign, functional, web  # noqa: F401  (fixtures)
from tests.test_web_sessions import ORIGIN, PASSWORD, login

CLASSES = ["a", "b", "c"]
# Component 0 favours class a, 1 favours b and 2 favours c, so the weights decide the winner.
VECTORS = [[.6, .3, .1], [.2, .6, .2], [.1, .3, .6]]
V1_WEIGHTS = [.7, .2, .1]   # -> a (.47)
V2_WEIGHTS = [.1, .2, .7]   # -> c (.47)
TRIAD_ID = 1


@pytest.fixture
def triad_env(functional, monkeypatch, tmp_path):  # noqa: F811
    client, _ = functional

    class Neural(torch.nn.Module):
        def __init__(self, num_classes):
            super().__init__()
            self.logits = torch.nn.Parameter(torch.zeros(num_classes))
        def forward(self, inputs):
            return self.logits.unsqueeze(0)

    monkeypatch.setattr(trained_predictor, "AudioCNN", Neural)
    engine = migrated_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    sessions = sessionmaker(bind=engine)
    weights_dir = main.training_service.checkpoints_dir
    weights_dir.mkdir(parents=True, exist_ok=True)
    checkpoints = {}
    with sessions() as db:
        for index, role in enumerate(("administrador", "investigador"), 1):
            db.add(Usuario(id=index, email=f"{role}@example.test", password_hash=hash_password(PASSWORD),
                           nombre_completo=role, rol=role, activo=True))
        db.add_all([ConjuntoDatos(id_conjunto_datos=10, nombre="AvesChilenas", ruta_gcp="datasets/AvesChilenas"),
                    ConjuntoDatos(id_conjunto_datos=20, nombre="engine_diagnostics", ruta_gcp="datasets/engine_diagnostics")])
        for model_id, vector in enumerate(VECTORS, 1):
            path = weights_dir / f"triad_{model_id}.pt"
            torch.save({"architecture": "AudioCNN", "classes": CLASSES,
                        "state_dict": {"logits": torch.log(torch.tensor(vector))},
                        "padding": torch.zeros(4096)}, path)
            checkpoints[model_id] = path
            db.add(Modelo(id_modelo=model_id, id_conjunto_datos=10, arquitectura="AudioCNN", epocas=1,
                          tasa_aprendizaje=0.001, tamano_lote=1, ruta_binario_gcp=f"models/{path.name}",
                          hash_binario=hashlib.sha256(path.read_bytes()).hexdigest()))
        db.commit()
        composition = create_initial_composition(
            db, job_id="job-1", dataset_id=10, partition_version="p1",
            components=list(zip((1, 2, 3), V1_WEIGHTS)), author_id=1)
        assert composition.id == TRIAD_ID

    def isolated_db():
        with sessions() as db:
            yield db

    registry = ModelRegistry()
    client.app.dependency_overrides[get_db] = isolated_db
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    # The lightweight application copies main's flat routes; add the nested ones explicitly.
    client.app.include_router(prediction_history_router)
    client.app.include_router(triad_router)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    monkeypatch.setattr(main.feedback_service, "import_root", private)
    monkeypatch.setattr(main, "upload_audio_to_gcp", AsyncMock(return_value=True))
    (tmp_path / "raw" / "AvesChilenas" / "Chucao").mkdir(parents=True)
    return SimpleNamespace(client=client, sessions=sessions, registry=registry, checkpoints=checkpoints)


def catalogue(env):
    response = env.client.get("/api/models")
    assert response.status_code == 200, response.text
    return response.json()


def triad_key(composition_id=TRIAD_ID):
    return f"fama_triad_{composition_id}"


def predict(env, model_id, name="tone.wav"):
    return env.client.post("/api/predict", headers={"Origin": ORIGIN}, params={"model_id": model_id},
                           files={"file": (name, create_dummy_wav_bytes(5.0), "audio/wav")})


def revise(env, weights, composition_id=TRIAD_ID):
    return env.client.post(f"/api/triad-compositions/{composition_id}/weights",
                           headers={"Origin": ORIGIN}, json={"weights": weights})


def stored_version(env, weights, active=False):
    """A later version stored before weights were fixed at training (ADR 0082)."""
    with env.sessions() as db:
        first = db.get(TriadComposition, TRIAD_ID)
        db.add(TriadComposition(
            dataset_id=first.dataset_id, partition_version=first.partition_version, job_id=first.job_id,
            version=2, previous_id=first.id, first_model_id=1, second_model_id=2, third_model_id=3,
            first_weight=weights[0], second_weight=weights[1], third_weight=weights[2],
            author_id=1, created_at=first.created_at, activo=active))
        db.commit()


def composition_rows(env):
    with env.sessions() as db:
        return [(r.id, r.version, r.previous_id) for r in db.query(TriadComposition).order_by(TriadComposition.id)]


# --- Rule 3: registry and catalogue ---------------------------------------------------------

def test_assigned_user_sees_the_composition_as_one_metadata_only_model(triad_env):
    env = triad_env
    assign(env.client)
    body = catalogue(env)
    by_id = {model["id"]: model for model in body["models"]}
    assert set(by_id) == {"fama_trained_model_1", "fama_trained_model_2", "fama_trained_model_3", triad_key()}
    triad = by_id[triad_key()]
    assert (triad["dataset_name"], triad["classes"], triad["has_weights"]) == ("AvesChilenas", CLASSES, True)
    assert triad["is_default"] is False and triad["metrics"] is None
    assert body["publication_errors"] == []
    # Publication never loaded weights: every component is still lazy.
    published = env.registry.get(triad_key())
    assert all(component.model is None for component in published.components)
    assert [component.model_id for component in published.components] == [
        "fama_trained_model_1", "fama_trained_model_2", "fama_trained_model_3"]
    assert published.weights == tuple(V1_WEIGHTS)


def test_individual_models_are_still_published_exactly_as_before(triad_env):
    env = triad_env
    assign(env.client)
    models = {model["id"]: model for model in catalogue(env)["models"]}
    for model_id in (1, 2, 3):
        model = models[f"fama_trained_model_{model_id}"]
        assert (model["dataset_name"], model["classes"], model["has_weights"]) == ("AvesChilenas", CLASSES, True)
        assert model["checkpoint_sha256"] == hashlib.sha256(env.checkpoints[model_id].read_bytes()).hexdigest()


def test_unassigned_user_neither_lists_nor_predicts_with_the_composition(triad_env):
    env = triad_env
    assert login(env.client).status_code == 200
    assert triad_key() not in {model["id"] for model in catalogue(env)["models"]}
    response = predict(env, triad_key())
    assert response.status_code == 404
    assert response.json() == {"detail": "Modelo no encontrado o no asignado."}
    with env.sessions() as db:
        assert db.query(Prediccion).count() == 0


def test_administrator_sees_the_composition(triad_env):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    assert triad_key() in {model["id"] for model in catalogue(env)["models"]}


@pytest.mark.parametrize("damage", ["hash-missing", "hash-invalid", "bytes-changed"])
def test_a_blocked_component_blocks_the_composition(triad_env, damage):
    env = triad_env
    with env.sessions() as db:
        if damage == "bytes-changed":
            env.checkpoints[2].write_bytes(env.checkpoints[2].read_bytes() + b"changed")
        else:
            db.get(Modelo, 2).hash_binario = None if damage == "hash-missing" else "not-a-digest"
            db.commit()
    assign(env.client)
    body = catalogue(env)
    assert triad_key() not in {model["id"] for model in body["models"]}
    response = predict(env, triad_key())
    assert response.status_code == 503, response.text
    with env.sessions() as db:
        assert db.query(Prediccion).count() == 0
    assert login(env.client, "administrador").status_code == 200
    assert {"model_id": triad_key(), "code": "triad_component_blocked"} in catalogue(env)["publication_errors"]


def ensemble_digest(env, weights=V1_WEIGHTS):
    from app.schemas.evaluation import triad_ensemble_sha256
    hashes = [hashlib.sha256(env.checkpoints[model_id].read_bytes()).hexdigest() for model_id in (1, 2, 3)]
    return hashes, triad_ensemble_sha256(hashes, list(weights), CLASSES)


def joint_identity(env, split):
    hashes, digest = ensemble_digest(env)
    return dict(composition_id=TRIAD_ID, composition_version=1, component_model_ids=[1, 2, 3],
                checkpoint_sha256s=hashes, weights=list(V1_WEIGHTS), checkpoint_sha256=digest,
                schema_version=2, evaluator_version="recording-v1", dataset="AvesChilenas", split=split,
                manifest_sha256="d" * 64, classes=list(CLASSES), sample_count=3,
                predictor_config={"components": [{}, {}, {}]}, preprocessing_config={"components": [{}, {}, {}]},
                aggregation_config={"components": [{}, {}, {}]})


def record_joint_attempts(env):
    """Validation completes and test fails, as the training job stores them."""
    from ml_core.classification_metrics import calculate_classification_report
    from app.services.recording_evaluator import REJECTION_LABEL
    from app.services.triad_evaluations import TriadEvaluationService
    with env.sessions() as db:
        service = TriadEvaluationService(db)
        val = service.create(joint_identity(env, "val"))
        service.start(val["id"])
        service.complete(val["id"], calculate_classification_report(
            ["a", "b", "c"], ["a", "b", "b"], CLASSES, rejection_label=REJECTION_LABEL))
        test = service.create(joint_identity(env, "test"))
        service.fail(test["id"], "Checkpoint cambió durante inferencia")


def test_the_catalogue_exposes_the_ensemble_digest_of_the_triad(triad_env):
    env = triad_env
    assign(env.client)
    triad = {model["id"]: model for model in catalogue(env)["models"]}[triad_key()]
    assert triad["checkpoint_sha256"] == ensemble_digest(env)[1]
    assert triad["evaluations"] is None
    # Reading the catalogue never loads a component.
    assert all(component.model is None for component in env.registry.get(triad_key()).components)


def test_the_catalogue_shows_the_stored_joint_evaluation_of_the_triad(triad_env):
    env = triad_env
    assign(env.client)
    record_joint_attempts(env)
    body = catalogue(env)
    assert body["evaluation_catalogue_status"] == "available"
    triad = {model["id"]: model for model in body["models"]}[triad_key()]
    val, test = triad["evaluations"]["val"], triad["evaluations"]["test"]
    assert val["latest_attempt"]["status"] == "completed"
    assert val["latest_completed"]["report"]["metrics"]["accuracy"] == pytest.approx(2 / 3)
    assert val["latest_completed"]["provenance"]["checkpoint_sha256"] == triad["checkpoint_sha256"]
    assert val["admitted_completed"] is None
    assert test["latest_completed"] is None
    assert test["latest_attempt"]["status"] == "failed"
    # Failure reasons may carry private paths; the catalogue never exposes them.
    assert "Checkpoint cambió" not in json.dumps(body) and "error_reason" not in json.dumps(body)
    assert all(component.model is None for component in env.registry.get(triad_key()).components)
    # Individual components keep their own (empty) evaluations.
    assert all(model["evaluations"] is None for model in body["models"] if model["id"] != triad_key())


def test_an_unassigned_user_never_receives_the_joint_evaluation(triad_env):
    env = triad_env
    record_joint_attempts(env)
    assert login(env.client).status_code == 200
    assert triad_key() not in {model["id"] for model in catalogue(env)["models"]}


TRIAD_NAME = "Aves Chilenas · Tríada 1 — AudioCNN + AudioCNN + AudioCNN"


def test_the_catalogue_and_history_name_the_triad_by_dataset_ordinal_and_architectures(triad_env):
    env = triad_env
    assign(env.client)
    triad = {model["id"]: model for model in catalogue(env)["models"]}[triad_key()]
    assert (triad["name"], triad["dataset"]) == (TRIAD_NAME, "Aves Chilenas")
    composition, = env.client.get("/api/training/history").json()["compositions"]
    assert (composition["name"], composition["architectures"]) == (TRIAD_NAME, ["AudioCNN"] * 3)
    # A stored later version keeps the ordinal of its training job.
    stored_version(env, V2_WEIGHTS)
    triad = {model["id"]: model for model in catalogue(env)["models"]}[triad_key(2)]
    assert triad["name"] == TRIAD_NAME


def test_the_composition_lists_each_component_architecture_and_fixed_weight(triad_env):
    env = triad_env
    assign(env.client)
    response = env.client.get(f"/api/triad-compositions/{TRIAD_ID}")
    assert response.status_code == 200, response.text
    assert [(c["architecture"], c["weight"]) for c in response.json()["components"]] == list(
        zip(["AudioCNN"] * 3, V1_WEIGHTS))


# --- Rule 5: prediction, history and feedback -----------------------------------------------

def test_prediction_fuses_the_components_and_feeds_history_and_feedback(triad_env):
    env = triad_env
    assign(env.client)
    catalogue(env)
    response = predict(env, triad_key(), "first.wav")
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["modelo_id"], result["clase"]) == (triad_key(), "a")
    assert result["confianza"] == pytest.approx(.47)
    assert result["detalles"]["weights"] == V1_WEIGHTS and result["detalles"]["ensemble_count"] == 3
    history = env.client.get("/api/inference/history", params={"model_id": triad_key()})
    assert history.status_code == 200, history.text
    item, = history.json()["items"]
    assert (item["id"], item["filename"], item["modelo_id"]) == (result["db_id"], "first.wav", triad_key())
    feedback = env.client.post("/api/feedback", headers={"Origin": ORIGIN},
                               json={"id_prediccion": result["db_id"], "fue_correcta": True})
    assert feedback.status_code == 201, feedback.text
    with env.sessions() as db:
        assert db.query(Prediccion).filter_by(id_prediccion=result["db_id"]).one().modelo_id == triad_key()


def test_history_and_feedback_stay_closed_without_assignment(triad_env):
    env = triad_env
    assign(env.client)
    catalogue(env)
    prediction = predict(env, triad_key()).json()
    assert login(env.client, "administrador").status_code == 200
    assert env.client.delete("/api/access/users/2/datasets/10", headers={"Origin": ORIGIN}).status_code == 204
    assert login(env.client).status_code == 200
    assert env.client.get("/api/inference/history", params={"model_id": triad_key()}).status_code == 404
    denied = env.client.post("/api/feedback", headers={"Origin": ORIGIN},
                             json={"id_prediccion": prediction["db_id"], "fue_correcta": True})
    assert denied.status_code == 404


def test_single_model_prediction_is_unchanged(triad_env):
    env = triad_env
    assign(env.client)
    catalogue(env)
    result = predict(env, "fama_trained_model_2").json()
    assert (result["modelo_id"], result["clase"]) == ("fama_trained_model_2", "b")
    assert "weights" not in result["detalles"]


def test_changed_component_bytes_after_publication_reject_without_inventing_a_result(triad_env):
    env = triad_env
    assign(env.client)
    catalogue(env)
    env.checkpoints[3].write_bytes(env.checkpoints[3].read_bytes() + b"changed after publication")
    response = predict(env, triad_key())
    assert response.status_code == 503, response.text
    with env.sessions() as db:
        assert db.query(Prediccion).count() == 0


# --- Rule 4: fixed training weights (ADR 0082) -----------------------------------------------

def test_weights_cannot_be_revised_after_training(triad_env):
    env = triad_env
    assign(env.client)
    before = {path.name: path.read_bytes() for path in env.checkpoints.values()}
    response = revise(env, V2_WEIGHTS)
    assert response.status_code in (404, 405), response.text
    assert composition_rows(env) == [(1, 1, None)]
    assert {path.name: path.read_bytes() for path in env.checkpoints.values()} == before
    with env.sessions() as db:
        assert db.get(TriadComposition, 1).first_weight == V1_WEIGHTS[0]
    assert {model["id"] for model in catalogue(env)["models"]} >= {triad_key(1)}


def test_the_service_offers_no_weight_revision():
    assert not hasattr(compositions_service, "revise_weights")


def test_a_stored_later_version_predicts_with_its_weights_and_keeps_each_versions_history_apart(triad_env):
    env = triad_env
    assign(env.client)
    catalogue(env)
    first = predict(env, triad_key(1), "v1.wav").json()
    stored_version(env, V2_WEIGHTS)
    catalogue(env)
    second = predict(env, triad_key(2), "v2.wav").json()
    assert (first["clase"], second["clase"]) == ("a", "c")
    assert env.client.post("/api/predict", headers={"Origin": ORIGIN}, params={"model_id": triad_key(1)},
                           files={"file": ("old.wav", create_dummy_wav_bytes(5.0), "audio/wav")}).status_code == 404
    history_1 = env.client.get("/api/inference/history", params={"model_id": triad_key(1)}).json()
    history_2 = env.client.get("/api/inference/history", params={"model_id": triad_key(2)}).json()
    assert [(i["filename"], i["modelo_id"]) for i in history_1["items"]] == [("v1.wav", triad_key(1))]
    assert [(i["filename"], i["modelo_id"]) for i in history_2["items"]] == [("v2.wav", triad_key(2))]
    assert env.client.post("/api/feedback", headers={"Origin": ORIGIN},
                           json={"id_prediccion": first["db_id"], "fue_correcta": False,
                                 "etiqueta_corregida": "b"}).status_code == 201


# --- Rule 6: activation ---------------------------------------------------------------------

def test_a_non_administrator_cannot_activate_models(triad_env):
    env = triad_env
    assign(env.client)
    response = env.client.post("/api/training/models/1/activate", headers={"Origin": ORIGIN})
    assert response.status_code == 403
    with env.sessions() as db:
        assert db.query(Modelo).filter_by(activo=True).count() == 0


def activate_triad(env, composition_id=TRIAD_ID):
    return env.client.post(f"/api/triad-compositions/{composition_id}/activate", headers={"Origin": ORIGIN})


def active_flags(env):
    with env.sessions() as db:
        return ([m.id_modelo for m in db.query(Modelo).filter_by(activo=True)],
                [c.id for c in db.query(TriadComposition).filter_by(activo=True)])


def test_an_administrator_activates_the_composition_as_the_default_model(triad_env):
    env = triad_env
    with env.sessions() as db:
        db.get(Modelo, 1).activo = True
        db.commit()
    assert login(env.client, "administrador").status_code == 200
    response = activate_triad(env)
    assert response.status_code == 200, response.text
    assert response.json()["model_id"] == triad_key() and response.json()["active"] is True
    assert active_flags(env) == ([], [TRIAD_ID])
    body = catalogue(env)
    assert body["default_model_id"] == triad_key()
    assert {m["id"]: m["is_default"] for m in body["models"]}[triad_key()] is True
    assert env.registry.get_default_model_id() == triad_key()


def test_activating_a_model_afterwards_deactivates_the_composition(triad_env):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    assert activate_triad(env).status_code == 200
    response = env.client.post("/api/training/models/2/activate", headers={"Origin": ORIGIN})
    assert response.status_code == 200 and response.json()["success"] is True, response.text
    assert active_flags(env) == ([2], [])


def test_a_non_administrator_cannot_activate_a_composition(triad_env):
    env = triad_env
    assign(env.client)
    response = activate_triad(env)
    assert response.status_code == 403
    assert active_flags(env) == ([], [])


def test_only_the_latest_version_can_be_activated(triad_env):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    stored_version(env, V2_WEIGHTS)
    response = activate_triad(env, 1)
    assert response.status_code == 409, response.text
    assert active_flags(env) == ([], [])
    assert activate_triad(env, 99).status_code == 404
    assert activate_triad(env, 2).status_code == 200
    assert active_flags(env) == ([], [2])


def test_the_active_composition_is_the_default_of_a_fresh_registry(triad_env):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    assert activate_triad(env).status_code == 200
    fresh = ModelRegistry()
    with env.sessions() as db:
        fresh.register_from_db(db, checkpoints_root=main.training_service.checkpoints_dir)
    assert fresh.get_default_model_id() == triad_key()
    assert fresh.get().model_id == triad_key()


def test_a_blocked_active_composition_blocks_the_default_like_a_blocked_model(triad_env):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    assert activate_triad(env).status_code == 200
    env.checkpoints[2].write_bytes(env.checkpoints[2].read_bytes() + b"changed")
    fresh = ModelRegistry()
    with env.sessions() as db:
        fresh.register_from_db(db, checkpoints_root=main.training_service.checkpoints_dir)
    with pytest.raises(Exception) as blocked:
        fresh.get()
    assert type(blocked.value).__name__ == "ModelWeightsError"


def test_single_model_activation_keeps_its_previous_behaviour(triad_env):
    env = triad_env
    assert login(env.client, "administrador").status_code == 200
    first = env.client.post("/api/training/models/1/activate", headers={"Origin": ORIGIN})
    assert first.status_code == 200 and first.json()["success"] is True
    assert first.json()["active_model_id"] == 1
    assert env.client.post("/api/training/models/3/activate", headers={"Origin": ORIGIN}).json()["success"] is True
    assert active_flags(env) == ([3], [])
    assert env.client.post("/api/training/models/999/activate", headers={"Origin": ORIGIN}).json() == {
        "success": False, "error": "Modelo inexistente"}
    assert active_flags(env) == ([3], [])
