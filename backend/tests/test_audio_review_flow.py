"""Controlled API integration: real SQLite/storage service, no cloud or model quality claim."""
import csv
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Reuse the controlled predictor and valid in-memory WAV, not the mocked DB fixture.
from tests.test_api_predict import ContractPredictor, create_dummy_wav_bytes
from app.database import Base, get_db
from app.main import app, ensemble_service
from app.services import registry as registry_module, storage
from app.services.feedback import feedback_service
from app.services.registry import ModelRegistry, get_model_registry
from training.datasets.local_folder import LocalFolderPAMIngestor


class ByteBucket:
    """Fake GCS boundary retaining actual bytes and deterministic partial failures."""

    def __init__(self):
        self.objects = {}
        # Catalogue entries are pre-existing cloud prefixes, not prediction uploads.
        self.catalog = {
            f"datasets/{dataset}/{label}/seed.wav"
            for dataset in ("AvesChilenas", "aves_revision")
            for label in ("Chucao", "Turca", "Churrín de la Mocha", "rayadito")
        }
        self.fail_dataset_upload_once = False

    def bucket(self, name):
        return self

    def list_blobs(self, bucket_name, prefix):
        from types import SimpleNamespace
        return [SimpleNamespace(name=key) for key in self.catalog | self.objects.keys()
                if key.startswith(prefix)]

    def blob(self, key):
        bucket = self

        class Blob:
            def upload_from_string(self, data, **kwargs):
                bucket.objects[key] = data
                if key.startswith("datasets/") and bucket.fail_dataset_upload_once:
                    bucket.fail_dataset_upload_once = False
                    raise OSError("Controlled lost acknowledgement after object upload")

            def download_as_bytes(self):
                if key not in bucket.objects:
                    raise FileNotFoundError(key)
                return bucket.objects[key]

        return Blob()


@pytest.fixture
def review_api(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)

    def isolated_db():
        with sessions() as session:
            yield session

    registry = ModelRegistry()
    predictor = ContractPredictor()
    predictor._metadata = predictor.metadata.model_copy(update={"dataset_name": "AvesChilenas"})
    registry.register(predictor, is_default=True)
    monkeypatch.setattr(registry_module, "_global_model_registry", registry)
    monkeypatch.setattr(ensemble_service, "load_models", lambda: None)
    bucket = ByteBucket()
    monkeypatch.setattr(storage.storage, "Client", lambda: bucket)
    raw = tmp_path / "raw"
    monkeypatch.setattr(feedback_service, "raw_data_dir", raw)
    for dataset in ("AvesChilenas", "aves_revision"):
        directory = raw / dataset
        directory.mkdir(parents=True)
        (directory / "metadata.csv").write_text(
            "nombre_archivo,clase,frecuencia_muestreo,duracion_segundos,tamano_bytes,hash_archivo,xc_id,recordist,licencia,pais,localidad,lat,lon,calidad\n",
            encoding="utf-8",
        )
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_model_registry] = lambda: registry
    # Deliberately omit lifespan: no admin seeding or disk model discovery.
    client = TestClient(app)
    try:
        yield client, bucket, raw
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def test_http_local_approval_is_ingestable_while_cloud_catalogue_and_upload_are_offline(review_api, monkeypatch):
    client, bucket, raw = review_api
    (raw / "AvesChilenas/rayadito").mkdir()
    feedback_id, source, audio, _ = predict_and_validate(client, bucket, raw, "Rayadito")

    def offline(*args, **kwargs):
        raise AssertionError("Local approval must not list or upload cloud datasets")

    monkeypatch.setattr(bucket, "list_blobs", offline)
    bucket.fail_dataset_upload_once = True
    response = client.post(f"/api/feedback/{feedback_id}/approve")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "approved", "id_retroalimentacion": 1,
        "destination_path": str(raw / "AvesChilenas/rayadito/feedback_1.wav"),
        "clase": "Rayadito", "filename": "feedback_1.wav",
        "local_status": "incorporated", "sync_status": "pending",
    }
    assert bucket.objects == {source: audio}
    assert bucket.fail_dataset_upload_once is True
    assert pending(client) == []
    dataset = raw / "AvesChilenas"
    samples = LocalFolderPAMIngestor(dataset, annotations_csv=dataset / "metadata.csv").ingest()
    assert len(samples) == 1
    assert samples.iloc[0]["file_path"] == str(dataset / "rayadito/feedback_1.wav")
    assert samples.iloc[0]["clase"] == "Rayadito"
    assert samples.iloc[0]["duracion_segundos"] == .1
    assert client.post(f"/api/feedback/{feedback_id}/approve").json() == response.json()


def test_automatic_snapshot_resolves_rayadito_and_rejects_override(review_api):
    client, bucket, raw = review_api
    feedback_id, source, audio, _ = predict_and_validate(client, bucket, raw, "Rayadito")
    assert pending(client)[0]["dataset_name"] == "AvesChilenas"
    before = bucket.objects.copy()
    assert client.post(f"/api/feedback/{feedback_id}/approve?dataset_name=aves_revision").status_code == 409
    assert bucket.objects == before
    response = client.post(f"/api/feedback/{feedback_id}/approve")
    assert response.status_code == 200, response.text
    assert response.json()["clase"] == "Rayadito"
    assert bucket.objects == {source: audio}
    assert response.json()["local_status"] == "incorporated"
    assert response.json()["sync_status"] == "pending"
    assert (raw / "AvesChilenas/rayadito/feedback_1.wav").read_bytes() == audio
    assert response.json()["destination_path"] == str(raw / "AvesChilenas/rayadito/feedback_1.wav")
    assert not (raw / "AvesChilenas/Rayadito").exists()
    assert not any(key.startswith("datasets/AvesChilenas/Rayadito/") for key in bucket.objects)
    with (raw / "AvesChilenas/metadata.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["nombre_archivo"] == "feedback_1.wav"
    assert rows[0]["clase"] == "Rayadito"
    assert int(rows[0]["tamano_bytes"]) == len(audio)
    assert bucket.objects[source] == audio


def pending(client):
    response = client.get("/api/feedback/pending")
    assert response.status_code == 200
    return response.json()


def predict_and_validate(client, bucket, raw, corrected=None):
    audio = create_dummy_wav_bytes(duration_sec=0.1)
    prediction = client.post(
        "/api/predict?model_id=contract-birds",
        files={"file": ("field.wav", audio, "audio/wav")},
    )
    assert prediction.status_code == 200, prediction.text
    result = prediction.json()
    assert result["clase"] == "Chucao"
    assert result["gcp_upload"] is True
    assert result["db_id"] > 0
    # Merely running inference does not create a curation item or dataset audio.
    assert pending(client) == []
    assert len(bucket.objects) == 1
    source = next(iter(bucket.objects))
    assert source.startswith("raw_audios/")
    assert bucket.objects[source] == audio
    assert list(raw.rglob("*.wav")) == []

    payload = {"id_prediccion": result["db_id"], "fue_correcta": corrected is None}
    if corrected:
        payload["etiqueta_corregida"] = corrected
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 201, response.text
    feedback = response.json()
    items = pending(client)
    assert len(items) == 1
    assert items[0]["id_prediccion"] == result["db_id"]
    assert items[0]["id_retroalimentacion"] == feedback["id_retroalimentacion"]
    assert items[0]["ruta_audio_prueba"] == source
    assert items[0]["etiqueta_predicha"] == "Chucao"
    assert items[0]["etiqueta_corregida"] == corrected
    assert items[0]["fue_correcta"] is (corrected is None)
    assert items[0]["procesado"] is False
    assert list(bucket.objects) == [source]
    assert list(raw.rglob("*.wav")) == []
    return feedback["id_retroalimentacion"], source, audio, payload


def assert_destinations(bucket, raw, feedback_id, audio, label, slug, dataset):
    filename = "feedback_1.wav"
    local = raw / dataset / label / filename
    assert local.read_bytes() == audio
    assert list(raw.rglob("*.wav")) == [local]
    assert [key for key in bucket.objects if key.startswith("datasets/")] == []
    with (raw / dataset / "metadata.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["nombre_archivo"] == filename
    assert rows[0]["clase"] == label
    assert int(rows[0]["tamano_bytes"]) == len(audio)
    return filename


@pytest.mark.parametrize("corrected,label,slug", [
    (None, "Chucao", "chucao"),
    ("Churrín de la Mocha", "Churrín de la Mocha", "churrin_de_la_mocha"),
])
def test_prediction_validation_approval_preserves_source_bytes(review_api, corrected, label, slug):
    client, bucket, raw = review_api
    feedback_id, source, audio, payload = predict_and_validate(client, bucket, raw, corrected)
    response = client.post(f"/api/feedback/{feedback_id}/approve")
    assert response.status_code == 200, response.text
    filename = assert_destinations(bucket, raw, feedback_id, audio, label, slug, "AvesChilenas")
    assert response.json()["filename"] == filename
    assert response.json()["clase"] == label
    assert pending(client) == []
    assert bucket.objects[source] == audio
    assert client.post("/api/feedback", json=payload).status_code == 409
    replay = client.post(f"/api/feedback/{feedback_id}/approve?dataset_name=AvesChilenas")
    assert replay.status_code == 200
    assert replay.json()["sync_status"] == "pending"


def test_prediction_validation_rejection_retains_source_without_dataset_changes(review_api):
    client, bucket, raw = review_api
    feedback_id, source, audio, payload = predict_and_validate(client, bucket, raw, "Turca")
    before = {path: path.read_bytes() for path in raw.rglob("metadata.csv")}
    response = client.post(f"/api/feedback/{feedback_id}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert pending(client) == []
    assert bucket.objects == {source: audio}
    assert list(raw.rglob("*.wav")) == []
    assert {path: path.read_bytes() for path in before} == before
    assert client.post("/api/feedback", json=payload).status_code == 409
    assert client.post(f"/api/feedback/{feedback_id}/reject").status_code == 409


def test_missing_prediction_source_remains_pending_until_retry(review_api):
    client, bucket, raw = review_api
    feedback_id, source, audio, _ = predict_and_validate(client, bucket, raw)
    # Model a storage-side unavailable object without touching a real filesystem/cloud.
    with patch.dict(bucket.objects, {}, clear=True):
        response = client.post(f"/api/feedback/{feedback_id}/approve?dataset_name=AvesChilenas")
        assert response.status_code == 503
        assert pending(client)[0]["procesado"] is False
        assert list(raw.rglob("*.wav")) == []
        assert bucket.objects == {}
    assert bucket.objects[source] == audio
    assert client.post(f"/api/feedback/{feedback_id}/approve?dataset_name=AvesChilenas").status_code == 200
    assert_destinations(bucket, raw, feedback_id, audio, "Chucao", "chucao", "AvesChilenas")
    assert pending(client) == []


def test_upload_outage_does_not_block_local_approval_and_replay(review_api):
    client, bucket, raw = review_api
    feedback_id, source, audio, payload = predict_and_validate(client, bucket, raw, "Turca")
    bucket.fail_dataset_upload_once = True
    response = client.post(f"/api/feedback/{feedback_id}/approve?dataset_name=AvesChilenas")
    assert response.status_code == 200
    assert response.json()["local_status"] == "incorporated"
    assert response.json()["sync_status"] == "pending"
    assert bucket.fail_dataset_upload_once is True  # No upload was attempted.
    assert len([key for key in bucket.objects if key.startswith("datasets/")]) == 0
    assert (raw / "AvesChilenas/Turca/feedback_1.wav").read_bytes() == audio
    assert pending(client) == []
    # The local decision pins intent; replay cannot change its destination.
    assert client.post("/api/feedback", json=payload).status_code == 409
    before_override = bucket.objects.copy()
    assert client.post(f"/api/feedback/{feedback_id}/approve?dataset_name=aves_revision").status_code == 409
    assert bucket.objects == before_override
    assert pending(client) == []
    assert not any(key.startswith("datasets/aves_revision/") for key in bucket.objects)
    assert client.post(f"/api/feedback/{feedback_id}/approve?dataset_name=AvesChilenas").status_code == 200
    assert_destinations(bucket, raw, feedback_id, audio, "Turca", "turca", "AvesChilenas")
    assert bucket.objects[source] == audio
    assert pending(client) == []


@pytest.mark.parametrize("destination", ["", " ", "../other", "/absolute", "x" * 101])
def test_invalid_destination_override_has_no_side_effects(review_api, destination):
    client, bucket, raw = review_api
    feedback_id, source, audio, _ = predict_and_validate(client, bucket, raw)
    params = {"dataset_name": destination}
    response = client.post(f"/api/feedback/{feedback_id}/approve", params=params)
    assert response.status_code == 422, response.text
    assert pending(client)[0]["procesado"] is False
    assert bucket.objects == {source: audio}
    assert list(raw.rglob("*.wav")) == []
    assert not (raw / f".feedback_{feedback_id}.json").exists()


def test_approval_rejects_different_dataset_without_writes(review_api):
    client, bucket, raw = review_api
    feedback_id, source, audio, _ = predict_and_validate(client, bucket, raw)
    response = client.post(f"/api/feedback/{feedback_id}/approve?dataset_name=aves_revision")
    assert response.status_code == 409, response.text
    assert bucket.objects == {source: audio}
    assert list(raw.rglob("*.wav")) == []
    assert pending(client)[0]["procesado"] is False
    assert not (raw / f".feedback_{feedback_id}.json").exists()
    assert client.post(f"/api/feedback/{feedback_id}/approve").status_code == 200
    assert_destinations(bucket, raw, feedback_id, audio, "Chucao", "chucao", "AvesChilenas")
