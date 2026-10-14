"""HTTP ingestion validation without production lifespan or cloud services."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app import main
from app.services import training
from tests.test_ingestion_upload_integrity import upload_environment, synthetic_wav
from tests.test_ingestion_sync_integrity import BlobFixture


@pytest.fixture
def client(upload_environment, monkeypatch):
    service, db, _ = upload_environment
    monkeypatch.setattr(main, "ingestion_service", service)
    app = FastAPI()
    for route in main.app.routes:
        if getattr(route, "path", "") in {"/api/ingestion/upload", "/api/ingestion/sync"}:
            app.add_api_route(route.path, route.endpoint, methods=list(route.methods))
    app.dependency_overrides[main.get_db] = lambda: db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_upload_invalid_dataset_returns_sanitized_422(client, upload_environment):
    _, _, objects = upload_environment

    response = client.post("/api/ingestion/upload", data={"dataset_name": "../private"},
                           files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})

    assert response.status_code == 422
    assert response.json()["detail"] == "Nombres de carga inválidos."
    assert objects == {}


def test_sync_rejects_invalid_dataset_in_batch_before_cloud_access(client, upload_environment, monkeypatch):
    def forbidden_cloud_access(*args, **kwargs):
        raise AssertionError("Cloud must not be contacted for an invalid batch")

    monkeypatch.setattr("google.cloud.storage.Client", forbidden_cloud_access)

    response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas", "../private"]})

    assert response.status_code == 422
    assert response.json()["detail"] == "Nombres de dataset inválidos."


def test_sync_rejects_overlong_dataset_in_batch_before_cloud_access(client, monkeypatch):
    def forbidden_cloud_access(*args, **kwargs):
        raise AssertionError("Cloud must not be contacted for an overlong name")

    monkeypatch.setattr("google.cloud.storage.Client", forbidden_cloud_access)
    response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas", "d" * 101]})

    assert response.status_code == 422
    assert response.json()["detail"] == "Nombres de dataset inválidos."


def test_upload_rejects_overlong_filename_with_sanitized_422(client, upload_environment):
    _, _, objects = upload_environment
    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("f" * 252 + ".wav", synthetic_wav(), "audio/wav")})

    assert response.status_code == 422
    assert response.json()["detail"] == "Nombres de carga inválidos."
    assert objects == {}


def test_upload_valid_unicode_names_still_transfers_and_registers(client, upload_environment):
    _, _, objects = upload_environment
    response = client.post("/api/ingestion/upload",
                           data={"dataset_name": "AvesChilenas", "class_label": "Churrín del sur"},
                           files={"files": ("grabación.wav", synthetic_wav(), "audio/wav")})

    assert response.status_code == 200
    assert response.json()["db_persisted"] is True, response.json()["db_error"]
    assert response.json()["uploaded"] == 1
    assert "datasets/AvesChilenas/Churrín del sur/grabación.wav" in objects


def test_upload_invalid_second_filename_returns_422_without_partial_transfer(client, upload_environment):
    _, _, objects = upload_environment
    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"}, files=[
        ("files", ("valid.wav", synthetic_wav(), "audio/wav")),
        ("files", ("audio.wav:stream", synthetic_wav(), "audio/wav")),
    ])

    assert response.status_code == 422
    assert response.json()["detail"] == "Nombres de carga inválidos."
    assert objects == {}


def test_provider_value_error_is_not_misreported_as_input_validation(client, monkeypatch):
    def provider_failure(*args, **kwargs):
        raise ValueError("Synthetic provider failure /private/credentials.json")

    monkeypatch.setattr("google.cloud.storage.Client", provider_failure)
    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})

    assert response.status_code == 500
    assert "/private" not in response.text


def test_valid_sync_still_reaches_fake_cloud_and_persists(client, monkeypatch):
    calls = []

    def list_blobs(self, bucket, prefix):
        calls.append(prefix)
        return []

    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", list_blobs, raising=False)
    response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})

    assert response.status_code == 200
    assert calls == ["datasets/AvesChilenas/"]
    assert response.json()["results"][0]["db_persisted"] is True, response.json()["results"][0]["db_error"]


@pytest.mark.parametrize("failing_statement", ["SELECT", "INSERT"])
def test_upload_database_failure_is_sanitized_and_does_not_claim_persistence(client, upload_environment, failing_statement):
    _, db, objects = upload_environment
    engine = db.get_bind()

    def fail_database(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(failing_statement):
            raise OperationalError(statement, parameters, RuntimeError("synthetic-secret /private/database"))

    event.listen(engine, "before_cursor_execute", fail_database)
    try:
        response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                               files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})
    finally:
        event.remove(engine, "before_cursor_execute", fail_database)

    assert response.status_code == 200  # Preserve the existing partial-result contract.
    assert response.json()["db_persisted"] is False
    assert response.json()["db_error"] == "No se pudieron guardar los registros de ingesta."
    assert "synthetic-secret" not in response.text
    assert "SELECT" not in response.text
    assert len(objects) == 1  # Cloud transfer is not undone by a database failure.
    assert training.training_service.get_available_datasets(db=db) == []
    retry = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                        files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})
    assert retry.status_code == 200
    assert retry.json()["db_persisted"] is True
    assert retry.json()["db_error"] is None
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["audio_count"] == 1


@pytest.mark.parametrize("failing_statement", ["SELECT", "INSERT"])
def test_sync_database_failure_is_sanitized_without_erasing_download(client, upload_environment, monkeypatch, failing_statement):
    service, db, _ = upload_environment
    blob = BlobFixture(synthetic_wav())
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: [blob], raising=False)
    engine = db.get_bind()

    def fail_database(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(failing_statement):
            raise OperationalError(statement, parameters, RuntimeError("synthetic-secret /private/database"))

    event.listen(engine, "before_cursor_execute", fail_database)
    try:
        response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    finally:
        event.remove(engine, "before_cursor_execute", fail_database)

    assert response.status_code == 200
    result, = response.json()["results"]
    assert result["db_persisted"] is False
    assert result["db_error"] == "No se pudieron guardar los registros de ingesta."
    assert result["downloaded"] == 1
    assert "synthetic-secret" not in response.text
    assert "SELECT" not in response.text
    assert (service.local_base_dir / "AvesChilenas" / "Chucao" / "audio.wav").read_bytes() == blob.content
    assert training.training_service.get_available_datasets(db=db) == []
    retry = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    assert retry.status_code == 200
    retried, = retry.json()["results"]
    assert retried["db_persisted"] is True
    assert retried["db_error"] is None
    assert retried["skipped"] == 1
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["audio_count"] == 1


def test_sync_local_failure_returns_partial_result_and_registers_only_accepted_audio(client, upload_environment, monkeypatch):
    service, db, _ = upload_environment
    blocked = service.local_base_dir / "AvesChilenas" / "Chucao" / "blocked"
    blocked.parent.mkdir(parents=True)
    blocked.write_bytes(b"previous local file")
    blobs = [BlobFixture(synthetic_wav(), "datasets/AvesChilenas/Chucao/blocked/audio.wav"),
             BlobFixture(synthetic_wav())]
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: blobs, raising=False)

    response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})

    assert response.status_code == 200
    assert response.json()["total_failed"] == 1
    assert response.json()["total_downloaded"] == 1
    result, = response.json()["results"]
    assert result["db_persisted"] is True
    assert result["files"][0]["error"] == "No se pudo sincronizar el archivo."
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["audio_count"] == 1
    assert dataset["estado"] == "sincronizacion_parcial"
    assert blocked.read_bytes() == b"previous local file"
