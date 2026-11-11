"""Standard assigned-model prediction and history through authenticated HTTP."""
from unittest.mock import AsyncMock

from app import main
from app.models.training import Modelo
from app.models.dataset_import import ImportedDataset
from app.models.imported_training_source import ImportedModelSource
from app.models.prediction import Prediccion
from app.models.training_snapshot import TrainingSnapshot
from app.routes.prediction_history import router as prediction_history_router
from app.services.registry import ModelRegistry, get_model_registry
from tests.test_api_predict import ContractPredictor, create_dummy_wav_bytes
from tests.test_resource_access import access, assign, functional, web
from tests.test_web_sessions import ORIGIN, login
from fastapi.testclient import TestClient


def test_assigned_standard_model_prediction_has_local_audio_and_visible_history(functional, monkeypatch, tmp_path):
    client, sessions = functional
    # The lightweight functional app does not include nested application routers.
    client.app.include_router(prediction_history_router)
    with sessions() as db:
        db.add(Modelo(id_modelo=100, id_conjunto_datos=10, arquitectura="fixture",
                      epocas=1, tasa_aprendizaje=0.01, tamano_lote=2,
                      ruta_binario_gcp="models/synthetic.pt"))
        db.commit()

    registry = ModelRegistry()
    predictor = ContractPredictor("fama_trained_model_100")
    predictor._metadata.dataset_name = "AvesChilenas"
    registry.register(predictor, is_default=True)
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(main.feedback_service, "import_root", root)
    monkeypatch.setattr(main, "upload_audio_to_gcp", AsyncMock(return_value=True))
    (tmp_path / "raw" / "AvesChilenas" / "Chucao").mkdir(parents=True)
    assign(client)

    prediction = client.post("/api/predict", headers={"Origin": ORIGIN},
        params={"model_id": "fama_trained_model_100"},
        files={"file": ("synthetic.wav", create_dummy_wav_bytes(), "audio/wav")})
    assert prediction.status_code == 200, prediction.text
    result = prediction.json()
    assert result["modelo_id"] == "fama_trained_model_100"

    history = client.get("/api/inference/history", params={"model_id": result["modelo_id"]})
    assert history.status_code == 200, history.text
    assert history.headers["cache-control"] == "no-store"
    assert history.json()["next_cursor"] is None
    item, = history.json()["items"]
    assert item["id"] == result["db_id"]
    assert item["filename"] == "synthetic.wav"
    assert item["modelo_id"] == result["modelo_id"]
    assert item["clase"] == result["clase"]
    assert item["confianza"] == result["confianza"]
    assert "local_predictions" not in history.text
    assert str(root) not in history.text
    assert result["gcp_upload"] is False

    feedback = client.post("/api/feedback", headers={"Origin": ORIGIN},
        json={"id_prediccion": result["db_id"], "fue_correcta": True})
    assert feedback.status_code == 201, feedback.text
    feedback_id = feedback.json()["id_retroalimentacion"]
    approved = client.post(f"/api/feedback/{feedback_id}/approve", headers={"Origin": ORIGIN})
    assert approved.status_code == 200, approved.text
    assert approved.json()["db_persisted"] is True


def test_import_owner_without_dataset_assignment_cannot_submit_feedback(functional):
    client, sessions = functional
    dataset_id, snapshot_id = "a" * 32, "b" * 32
    with sessions() as db:
        db.add(ImportedDataset(id=dataset_id, owner_id=2, name="Synthetic private", revision=1))
        db.add(TrainingSnapshot(id=snapshot_id, owner_id=2, dataset_id=dataset_id,
                                dataset_revision=1, name="Synthetic", description="",
                                state="ready", file_count=1, total_size_bytes=44, classes=["Chucao"]))
        db.add(Modelo(id_modelo=301, arquitectura="AudioCNN", epocas=1,
                      tasa_aprendizaje=0.001, tamano_lote=1, ruta_binario_gcp="models/synthetic.pt"))
        db.flush()
        db.add(ImportedModelSource(model_id=301, owner_id=2, dataset_id=dataset_id,
                                   snapshot_id=snapshot_id, identity={"owner_id": 2}))
        db.add(Prediccion(id_prediccion=501, modelo_id="fama_trained_model_301",
                          dataset_name="imported:" + dataset_id, etiqueta_predicha="Chucao",
                          confianza=0.9, ruta_audio_prueba="raw_audios/synthetic.wav"))
        db.commit()
    assert login(client).status_code == 200
    before = client.get("/api/feedback/pending")
    assert before.status_code == 200
    denied = client.post("/api/feedback", headers={"Origin": ORIGIN},
                         json={"id_prediccion": 501, "fue_correcta": True})
    assert denied.status_code == 404, denied.text
    assert denied.json() == {"detail": "Recurso no encontrado o no asignado."}
    after = client.get("/api/feedback/pending")
    assert after.status_code == 200
    assert after.json() == before.json()


def test_declared_model_history_pages_and_revocation(functional, monkeypatch, tmp_path):
    client, _ = functional
    client.app.include_router(prediction_history_router)
    registry = ModelRegistry()
    predictor = ContractPredictor("declared-birds")
    predictor._metadata.dataset_name = "AvesChilenas"
    registry.register(predictor, is_default=True)
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(main.feedback_service, "import_root", root)
    assign(client)
    for filename in ("first.wav", "second.wav"):
        result = client.post("/api/predict", headers={"Origin": ORIGIN},
            params={"model_id": "declared-birds"},
            files={"file": (filename, create_dummy_wav_bytes(), "audio/wav")})
        assert result.status_code == 200, result.text
    def no_inference(*args, **kwargs):
        raise AssertionError("History must not run inference")
    monkeypatch.setattr(predictor, "predict", no_inference)
    first = client.get("/api/inference/history", params={"model_id": "declared-birds", "limit": 1})
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "no-store"
    assert [item["filename"] for item in first.json()["items"]] == ["second.wav"]
    cursor = first.json()["next_cursor"]
    second = client.get("/api/inference/history", params={"model_id": "declared-birds", "limit": 1, "cursor": cursor})
    assert second.status_code == 200, second.text
    assert [item["filename"] for item in second.json()["items"]] == ["first.wav"]
    assert second.json()["next_cursor"] is None
    assert "local_predictions" not in first.text
    with TestClient(client.app, base_url=ORIGIN) as administrator:
        assert login(administrator, "administrador").status_code == 200
        assert administrator.delete("/api/access/users/2/datasets/10", headers={"Origin": ORIGIN}).status_code == 204
        before = administrator.get("/api/dashboard/stats")
        assert before.status_code == 200
        denied = client.get("/api/inference/history", params={"model_id": "declared-birds"})
        assert denied.status_code == 404, denied.text
        assert "first.wav" not in denied.text and "second.wav" not in denied.text
        rejected = client.post("/api/predict", headers={"Origin": ORIGIN},
            params={"model_id": "declared-birds"},
            files={"file": ("denied.wav", create_dummy_wav_bytes(), "audio/wav")})
        assert rejected.status_code == 404, rejected.text
        after = administrator.get("/api/dashboard/stats")
        assert after.status_code == 200
        assert after.json()["kpis"]["total_predictions"] == before.json()["kpis"]["total_predictions"]


def test_assigned_cloud_prediction_feedback_uses_configured_bucket(functional, monkeypatch, tmp_path):
    """With no local audio root, the standard flow uploads to and approves from the configured bucket."""
    from dataclasses import replace
    from app.configuration import activate_configuration, get_configuration
    from app.services import storage

    client, _ = functional
    registry = ModelRegistry()
    predictor = ContractPredictor("declared-birds")
    predictor._metadata.dataset_name = "AvesChilenas"
    registry.register(predictor, is_default=True)
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    monkeypatch.setattr(main.feedback_service, "import_root", None)
    monkeypatch.delenv("FAMA_IMPORT_ROOT", raising=False)
    (tmp_path / "raw" / "AvesChilenas" / "Chucao").mkdir(parents=True)

    objects = {}

    class Bucket:
        def __init__(self, name):
            self.name = name

        def blob(self, key):
            return Blob(self.name, key)

    class Blob:
        def __init__(self, bucket, key):
            self.bucket, self.key = bucket, key

        def upload_from_string(self, data, **kwargs):
            objects[(self.bucket, self.key)] = data

        def download_as_bytes(self):
            return objects[(self.bucket, self.key)]

    class Client:
        def bucket(self, name):
            return Bucket(name)

    previous = get_configuration()
    activate_configuration(replace(previous, bucket_name="synthetic-test-bucket"))
    monkeypatch.setattr(storage.storage, "Client", Client)
    try:
        assign(client)
        audio = create_dummy_wav_bytes()
        prediction = client.post("/api/predict", headers={"Origin": ORIGIN},
            params={"model_id": "declared-birds"},
            files={"file": ("cloud.wav", audio, "audio/wav")})
        assert prediction.status_code == 200, prediction.text
        result = prediction.json()
        assert result["gcp_upload"] is True
        (bucket, key), = objects
        assert bucket == "synthetic-test-bucket" and key.startswith("raw_audios/")
        assert objects[(bucket, key)] == audio

        feedback = client.post("/api/feedback", headers={"Origin": ORIGIN},
            json={"id_prediccion": result["db_id"], "fue_correcta": True})
        assert feedback.status_code == 201, feedback.text
        feedback_id = feedback.json()["id_retroalimentacion"]
        approved = client.post(f"/api/feedback/{feedback_id}/approve", headers={"Origin": ORIGIN})
        assert approved.status_code == 200, approved.text
        assert approved.json()["db_persisted"] is True
        stored = tmp_path / "raw" / "AvesChilenas" / "Chucao" / f"feedback_{feedback_id}.wav"
        assert stored.read_bytes() == audio
    finally:
        activate_configuration(previous)
