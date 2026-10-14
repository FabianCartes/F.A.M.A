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
        if getattr(route, "path", "") in {"/api/ingestion/upload", "/api/ingestion/sync",
                                          "/api/ingestion/datasets/{dataset_name}/files"}:
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
    assert response.json()["status"] == "partial"
    assert response.json()["db_persisted"] is False
    assert response.json()["db_error"] == "No se pudieron guardar los registros de ingesta."
    assert "synthetic-secret" not in response.text
    assert "SELECT" not in response.text
    assert len(objects) == 1  # Cloud transfer is not undone by a database failure.
    assert training.training_service.get_available_datasets(db=db) == []
    retry = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                        files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})
    assert retry.status_code == 200
    assert retry.json()["status"] == "completed"
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
    assert response.json()["status"] == "partial"
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
    assert response.json()["status"] == "partial"
    assert response.json()["total_downloaded"] == 1
    result, = response.json()["results"]
    assert result["db_persisted"] is True
    assert result["files"][0]["error"] == "No se pudo sincronizar el archivo."
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["audio_count"] == 1
    assert dataset["estado"] == "sincronizacion_parcial"
    assert blocked.read_bytes() == b"previous local file"


def test_upload_partial_transfer_reports_status_and_keeps_successful_registration(client, upload_environment, monkeypatch):
    _, db, objects = upload_environment
    monkeypatch.setattr("google.cloud.storage.Client.failures", {"datasets/AvesChilenas/General/failed.wav"})
    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"}, files=[
        ("files", ("accepted.wav", synthetic_wav(), "audio/wav")),
        ("files", ("failed.wav", synthetic_wav(), "audio/wav")),
    ])

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "partial"
    assert result["uploaded"] == 1
    assert result["failed"] == 1
    assert result["db_persisted"] is True
    assert result["errors"] == [{"filename": "failed.wav", "error": "No se pudo subir el archivo."}]
    assert "/private" not in response.text
    assert len(objects) == 1
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["audio_count"] == 1
    assert dataset["estado"] == "subida_parcial"


def test_sync_total_transfer_failure_is_not_reported_as_completed(client, monkeypatch):
    blob = BlobFixture(synthetic_wav())
    blob.fail = True
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: [blob], raising=False)

    response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["total_downloaded"] == 0
    assert response.json()["total_failed"] == 1
    assert response.json()["results"][0]["db_persisted"] is True


def test_sync_preprocessing_failure_is_partial_not_processed(client, upload_environment, monkeypatch):
    _, db, _ = upload_environment
    blob = BlobFixture(b"synthetic invalid wav content")
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: [blob], raising=False)

    response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"], "preprocess": True})

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert response.json()["results"][0]["preprocess_info"]["failed"] == 1
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["estado"] == "sincronizacion_parcial"


def test_sync_successful_preprocessing_is_completed(client, upload_environment, monkeypatch):
    service, db, _ = upload_environment
    blob = BlobFixture(synthetic_wav())
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: [blob], raising=False)

    response = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"], "preprocess": True})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["total_preprocessed"] == 1
    assert response.json()["results"][0]["preprocess_info"]["failed"] == 0
    assert (service.local_processed_dir / "AvesChilenas" / "Chucao" / "audio.npy").is_file()
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["estado"] == "procesado"


def test_inspector_reads_observed_upload_metadata_from_database(client):
    uploaded = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})
    assert uploaded.json()["db_persisted"] is True

    response = client.get("/api/ingestion/datasets/AvesChilenas/files")

    assert response.status_code == 200
    audio, = response.json()["files"]
    assert audio.get("recorded_metadata") == {
        "sample_rate_hz": 8000, "duration_seconds": 1.0, "source": "database"
    }


def test_unreadable_upload_does_not_invent_audio_metadata(client):
    uploaded = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", b"synthetic invalid audio", "audio/wav")})
    assert uploaded.json()["db_persisted"] is True

    response = client.get("/api/ingestion/datasets/AvesChilenas/files")

    assert response.status_code == 200
    audio, = response.json()["files"]
    assert audio["recorded_metadata"] == {
        "sample_rate_hz": None, "duration_seconds": None, "source": "database"
    }


def test_replacing_upload_updates_recorded_metadata(client):
    for content in (synthetic_wav(), synthetic_wav(frames=22050, sample_rate=11025)):
        uploaded = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                               files={"files": ("audio.wav", content, "audio/wav")})
        assert uploaded.json()["db_persisted"] is True

    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]

    assert audio["recorded_metadata"] == {
        "sample_rate_hz": 11025, "duration_seconds": 2.0, "source": "database"
    }


def test_sync_records_metadata_from_downloaded_audio(client, monkeypatch):
    blob = BlobFixture(synthetic_wav(frames=4000))
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: [blob])
    synced = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    assert synced.json()["results"][0]["db_persisted"] is True

    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]

    assert audio["recorded_metadata"] == {
        "sample_rate_hz": 8000, "duration_seconds": 0.5, "source": "database"
    }


def test_sync_refresh_updates_metadata_and_verified_retry_keeps_it(client, monkeypatch):
    blobs = [BlobFixture(synthetic_wav(frames=4000))]
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: blobs)
    first = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    assert first.json()["results"][0]["db_persisted"] is True
    blobs[:] = [BlobFixture(synthetic_wav(frames=22050, sample_rate=11025))]

    second = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    third = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]

    assert second.json()["results"][0]["downloaded"] == 1
    assert third.json()["results"][0]["skipped"] == 1
    assert audio["recorded_metadata"] == {
        "sample_rate_hz": 11025, "duration_seconds": 2.0, "source": "database"
    }


def test_inspector_matches_metadata_by_full_object_route_not_basename(client):
    for label, content in [("Chucao", synthetic_wav()),
                           ("Rayadito", synthetic_wav(frames=22050, sample_rate=11025))]:
        response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas", "class_label": label},
                               files={"files": ("audio.wav", content, "audio/wav")})
        assert response.json()["db_persisted"] is True

    files = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]
    by_class = {item["class_name"]: item["recorded_metadata"] for item in files}

    assert by_class == {
        "Chucao": {"sample_rate_hz": 8000, "duration_seconds": 1.0, "source": "database"},
        "Rayadito": {"sample_rate_hz": 11025, "duration_seconds": 2.0, "source": "database"},
    }


def test_unreadable_replacement_clears_old_metadata_instead_of_preserving_it(client):
    for content in (synthetic_wav(), b"synthetic unreadable replacement"):
        response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                               files={"files": ("audio.wav", content, "audio/wav")})
        assert response.json()["db_persisted"] is True

    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]

    assert audio["recorded_metadata"] == {"sample_rate_hz": None, "duration_seconds": None, "source": "database"}


def test_zero_duration_is_recorded_without_defaulting_to_five_seconds(client):
    response = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", synthetic_wav(frames=0), "audio/wav")})
    assert response.json()["db_persisted"] is True

    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]

    assert audio["recorded_metadata"] == {"sample_rate_hz": 8000, "duration_seconds": 0.0, "source": "database"}


def test_unregistered_cloud_object_has_no_invented_recorded_metadata(client, upload_environment):
    _, _, objects = upload_environment
    objects["datasets/AvesChilenas/Chucao/audio.wav"] = synthetic_wav()

    response = client.get("/api/ingestion/datasets/AvesChilenas/files")

    assert response.status_code == 200
    audio, = response.json()["files"]
    assert audio["recorded_metadata"] is None


def test_inspector_database_failure_returns_inventory_without_leaking_sql(client, upload_environment):
    _, db, _ = upload_environment
    uploaded = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})
    assert uploaded.json()["db_persisted"] is True
    engine = db.get_bind()

    def fail_database(conn, cursor, statement, parameters, context, executemany):
        raise OperationalError(statement, parameters, RuntimeError("synthetic-secret /private/database"))

    event.listen(engine, "before_cursor_execute", fail_database)
    try:
        response = client.get("/api/ingestion/datasets/AvesChilenas/files")
    finally:
        event.remove(engine, "before_cursor_execute", fail_database)

    assert response.status_code == 200
    audio, = response.json()["files"]
    assert audio["recorded_metadata"] is None
    assert "synthetic-secret" not in response.text
    assert "SELECT" not in response.text
    retry, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]
    assert retry["recorded_metadata"]["sample_rate_hz"] == 8000


def test_recorded_metadata_is_not_a_probe_of_changed_cloud_content(client, upload_environment):
    _, _, objects = upload_environment
    uploaded = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                           files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})
    assert uploaded.json()["db_persisted"] is True
    objects["datasets/AvesChilenas/General/audio.wav"] = synthetic_wav(frames=22050, sample_rate=11025)

    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]

    assert audio["recorded_metadata"] == {"sample_rate_hz": 8000, "duration_seconds": 1.0, "source": "database"}


def test_failed_upload_refresh_keeps_previous_recorded_metadata(client, monkeypatch):
    first = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                        files={"files": ("audio.wav", synthetic_wav(), "audio/wav")})
    assert first.json()["db_persisted"] is True
    monkeypatch.setattr("google.cloud.storage.Client.failures", {"datasets/AvesChilenas/General/audio.wav"})

    failed = client.post("/api/ingestion/upload", data={"dataset_name": "AvesChilenas"},
                         files={"files": ("audio.wav", synthetic_wav(frames=22050, sample_rate=11025), "audio/wav")})
    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]

    assert failed.json()["status"] == "failed"
    assert audio["recorded_metadata"] == {"sample_rate_hz": 8000, "duration_seconds": 1.0, "source": "database"}


def test_unreadable_sync_refresh_clears_previous_metadata(client, monkeypatch):
    blobs = [BlobFixture(synthetic_wav())]
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: blobs)
    first = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    assert first.json()["results"][0]["db_persisted"] is True
    blobs[:] = [BlobFixture(b"synthetic unreadable replacement")]

    second = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    audio, = client.get("/api/ingestion/datasets/AvesChilenas/files").json()["files"]

    assert second.json()["results"][0]["db_persisted"] is True
    assert audio["recorded_metadata"] == {"sample_rate_hz": None, "duration_seconds": None, "source": "database"}


@pytest.mark.parametrize("relative, label", [("audio.wav", "General"), ("Chucao/session/audio.wav", "Chucao")])
def test_offline_inspector_preserves_object_identity_for_recorded_metadata(client, monkeypatch, relative, label):
    blob = BlobFixture(synthetic_wav(), f"datasets/AvesChilenas/{relative}")
    monkeypatch.setattr("google.cloud.storage.Client.list_blobs", lambda *args, **kwargs: [blob])
    synced = client.post("/api/ingestion/sync", json={"datasets": ["AvesChilenas"]})
    assert synced.json()["results"][0]["db_persisted"] is True

    def offline_client():
        raise OSError("Synthetic cloud offline")

    monkeypatch.setattr("google.cloud.storage.Client", offline_client)
    response = client.get("/api/ingestion/datasets/AvesChilenas/files")

    assert response.status_code == 200
    audio, = response.json()["files"]
    assert audio["path"] == f"datasets/AvesChilenas/{relative}"
    assert audio["class_name"] == label
    assert audio["recorded_metadata"] == {"sample_rate_hz": 8000, "duration_seconds": 1.0, "source": "database"}


def test_cloud_inspector_keeps_nested_filename_and_ignores_directory_markers(client, upload_environment):
    _, _, objects = upload_environment
    objects["datasets/AvesChilenas/Chucao/session/"] = b""
    objects["datasets/AvesChilenas/Chucao/session/audio.wav"] = synthetic_wav()

    response = client.get("/api/ingestion/datasets/AvesChilenas/files")

    assert response.status_code == 200
    audio, = response.json()["files"]
    assert audio["name"] == "audio.wav"
    assert audio["class_name"] == "Chucao"
    assert audio["path"] == "datasets/AvesChilenas/Chucao/session/audio.wav"
