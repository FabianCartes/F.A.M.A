"""HTTP ingestion validation without production lifespan or cloud services."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from tests.test_ingestion_upload_integrity import upload_environment, synthetic_wav


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
