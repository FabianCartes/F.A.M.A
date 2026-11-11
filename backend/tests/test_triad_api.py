"""Standard triad compositions over authenticated HTTP: catalogue, prediction, history and revision."""
import hashlib
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


# --- Rule 4: weight revision ----------------------------------------------------------------

def test_assignment_authorizes_a_revision_that_creates_the_next_version(triad_env):
    env = triad_env
    assign(env.client)  # the researcher did not author version 1
    before = {path.name: path.read_bytes() for path in env.checkpoints.values()}
    with env.sessions() as db:
        models_before = [(m.id_modelo, m.hash_binario, m.estado, m.activo) for m in db.query(Modelo).order_by(Modelo.id_modelo)]
    response = revise(env, V2_WEIGHTS)
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["id"], body["model_id"], body["version"], body["previous_id"]) == (2, triad_key(2), 2, 1)
    assert [c["weight"] for c in body["components"]] == V2_WEIGHTS
    assert [c["id_modelo"] for c in body["components"]] == [1, 2, 3]
    assert body["latest"] is True and body["author_id"] == 2
    assert composition_rows(env) == [(1, 1, None), (2, 2, 1)]
    assert {path.name: path.read_bytes() for path in env.checkpoints.values()} == before
    with env.sessions() as db:
        assert [(m.id_modelo, m.hash_binario, m.estado, m.activo) for m in db.query(Modelo).order_by(Modelo.id_modelo)] == models_before
        assert db.get(TriadComposition, 1).first_weight == V1_WEIGHTS[0]  # the old row is never edited
    listed = {model["id"] for model in catalogue(env)["models"]}
    assert triad_key(2) in listed and triad_key(1) not in listed
    assert env.client.get("/api/triad-compositions/1").json()["latest"] is False


@pytest.mark.parametrize("weights", [[.5, .5], [.25] * 4, [.5, .5, .5], [-.5, .75, .75], [0, 0, 0],
                                     [True, 0, 0], ["a", "b", "c"]])
def test_invalid_weights_are_rejected_without_a_new_version(triad_env, weights):
    env = triad_env
    assign(env.client)
    response = revise(env, weights)
    assert response.status_code == 422, response.text
    assert composition_rows(env) == [(1, 1, None)]


def test_a_revision_without_assignment_is_not_found_and_changes_nothing(triad_env):
    env = triad_env
    assert login(env.client).status_code == 200
    response = revise(env, V2_WEIGHTS)
    assert response.status_code == 404
    assert response.json() == {"detail": "Recurso no encontrado o no asignado."}
    assert env.client.get("/api/triad-compositions/1").status_code == 404
    assert composition_rows(env) == [(1, 1, None)]


def test_an_anonymous_revision_is_unauthorized(triad_env):
    env = triad_env
    assert revise(env, V2_WEIGHTS).status_code == 401
    assert composition_rows(env) == [(1, 1, None)]


def test_only_the_latest_version_can_be_revised(triad_env):
    env = triad_env
    assign(env.client)
    assert revise(env, V2_WEIGHTS).status_code == 201
    stale = revise(env, [.3, .3, .4], composition_id=1)
    assert stale.status_code == 409, stale.text
    assert composition_rows(env) == [(1, 1, None), (2, 2, 1)]


def test_a_concurrent_revision_from_the_same_version_fails_cleanly(triad_env, monkeypatch):
    env = triad_env
    assign(env.client)
    with env.sessions() as db:
        winner = db.get(TriadComposition, 1)
        compositions_service.revise_weights(db, winner, V2_WEIGHTS, author_id=1)
    # This request read version 1 as the latest before the other revision committed.
    monkeypatch.setattr(compositions_service, "_latest_version", lambda db, job_id: 1)
    response = revise(env, [.3, .3, .4])
    assert response.status_code == 409, response.text
    assert composition_rows(env) == [(1, 1, None), (2, 2, 1)]


def test_a_revision_changes_the_prediction_and_keeps_each_versions_history_apart(triad_env):
    env = triad_env
    assign(env.client)
    catalogue(env)
    first = predict(env, triad_key(1), "v1.wav").json()
    assert revise(env, V2_WEIGHTS).status_code == 201
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
