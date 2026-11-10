"""Independent findings pinned at the public HTTP interface."""
from fastapi.testclient import TestClient
import pytest
from tests.test_dataset_import_api import imports, prepare, confirm, operation


def test_recovery_retries_failed_directory_durability(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    job = prepare(client, tmp_path)
    original = module._durable_directory

    def fail_objects_sync(path):
        if path == service.root / "objects":
            raise OSError("persistent synthetic fsync failure")
        return original(path)

    monkeypatch.setattr(module, "_durable_directory", fail_objects_sync)
    assert confirm(client, job).json()["status"] == "failed"
    assert confirm(client, job).json()["status"] == "failed"
    assert client.get("/api/ingestion/imports/datasets").json()["datasets"] == []
    monkeypatch.setattr(module, "_durable_directory", original)
    assert confirm(client, job).json()["added_count"] == 1


def test_legacy_colon_name_remains_readable(tmp_path, monkeypatch):
    from app import main
    from app.services.ingestion import IngestionService
    from tests.test_dataset_zip_validation import wav_bytes
    raw = tmp_path / "raw"
    folder = raw / "Birds:field" / "birds"
    folder.mkdir(parents=True)
    (folder / "one.wav").write_bytes(wav_bytes())
    service = IngestionService(local_base_dir=raw, local_processed_dir=tmp_path / "processed")
    def offline():
        raise RuntimeError("synthetic offline storage")
    monkeypatch.setattr(service, "_get_client", offline)
    monkeypatch.setattr(main, "ingestion_service", service)
    client = TestClient(main.app, raise_server_exceptions=False)
    try:
        from tests.http_security import administrator_http
        with administrator_http(main.app):
            response = client.get("/api/ingestion/datasets/Birds%3Afield/files")
        assert response.status_code == 200, response.text
        assert response.json()["files"][0]["name"] == "one.wav"
    finally:
        client.close()


def test_equivalent_previews_must_reconcile_at_publication(imports, tmp_path):
    client, _, _, _ = imports
    first = prepare(client, tmp_path, key="first", name="First")
    second = prepare(client, tmp_path, key="second", name="Second")
    assert first["preview"]["resolved_target_id"] is None
    assert second["preview"]["resolved_target_id"] is None
    published = confirm(client, first).json()
    before = client.get("/api/ingestion/imports/datasets").json()
    assert confirm(client, second).status_code == 409
    assert client.get("/api/ingestion/imports/datasets").json() == before
    reviewed = operation(client, second["id"], "preview", {"root": ""}).json()
    assert reviewed["preview"]["new_count"] == 0
    assert confirm(client, second).status_code == 409
    repeated = confirm(client, reviewed).json()
    assert repeated["added_count"] == 0
    assert repeated["dataset_id"] == published["dataset_id"]
    assert client.get("/api/ingestion/imports/datasets").json() == before


def test_storage_ancestry_is_durable_before_publication_and_retried(imports, tmp_path, monkeypatch):
    from app.services import dataset_imports as module
    client, service, _, _ = imports
    job = prepare(client, tmp_path)
    original = module._durable_directory
    attempts = []

    def fail_root_parent(path):
        attempts.append(path)
        if path == service.root.parent:
            raise OSError("synthetic storage ancestry fsync failure")
        return original(path)

    monkeypatch.setattr(module, "_durable_directory", fail_root_parent)
    assert confirm(client, job).json()["status"] == "failed"
    assert confirm(client, job).json()["status"] == "failed"
    assert attempts.count(service.root.parent) == 2
    assert client.get("/api/ingestion/imports/datasets").json()["datasets"] == []
    recorded = []
    def record_sync(path):
        recorded.append(path)
        return original(path)
    monkeypatch.setattr(module, "_durable_directory", record_sync)
    assert confirm(client, job).json()["added_count"] == 1
    assert all(parent in recorded for parent in (service.root, *service.root.parents))


def test_equivalent_append_cannot_strand_a_new_dataset_journal(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    existing = confirm(client, prepare(client, tmp_path, key="existing", sample=3)).json()["dataset_id"]
    pending = prepare(client, tmp_path, key="pending-new", name="New dataset")
    original = module._durable_directory

    def interrupt_publication(path):
        if path == service.root / "objects":
            raise OSError("synthetic interruption after journal and move")
        return original(path)

    monkeypatch.setattr(module, "_durable_directory", interrupt_publication)
    assert confirm(client, pending).json()["status"] == "failed"
    assert client.get(f"/api/ingestion/imports/{pending['id']}").json()["status"] == "committing"
    monkeypatch.setattr(module, "_durable_directory", original)
    append = prepare(client, tmp_path, key="equivalent-append", target_id=existing)
    before = client.get(f"/api/ingestion/imports/datasets/{existing}/files").json()
    assert confirm(client, append).status_code == 409
    assert client.get(f"/api/ingestion/imports/datasets/{existing}/files").json() == before
    recovered = confirm(client, pending)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["added_count"] == 1
    assert confirm(client, pending).json() | {"execution": None} == recovered.json() | {"execution": None}


def test_receipt_requires_durable_staging_parent_and_can_retry(imports, tmp_path, monkeypatch):
    from app.routes import dataset_imports as routes
    from tests.test_dataset_zip_validation import archive, wav_bytes
    client, service, _, _ = imports
    job = client.post("/api/ingestion/imports", json={"request_key": "receipt", "name": "Receipt"}).json()
    data = archive(tmp_path / "receipt.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    path = f"/api/ingestion/imports/{job['id']}/archive"
    original = routes._durable_directory

    def fail_parent(path):
        if path == service.root / "staging":
            raise OSError("synthetic missing parent durability")
        return original(path)

    monkeypatch.setattr(routes, "_durable_directory", fail_parent)
    assert client.put(path, content=data, headers={"Content-Type": "application/zip"}).status_code == 500
    assert client.get(f"/api/ingestion/imports/{job['id']}").json()["status"] == "receiving"
    monkeypatch.setattr(routes, "_durable_directory", original)
    assert client.put(path, content=data, headers={"Content-Type": "application/zip"}).status_code == 200
    reviewed = operation(client, job["id"], "preview", {"root": ""}).json()
    assert confirm(client, reviewed).json()["added_count"] == 1


@pytest.mark.parametrize("damage", ["missing_directory", "corrupt_archive"])
def test_identical_archive_retry_restores_retained_bytes(imports, tmp_path, damage):
    import hashlib
    import shutil
    client, service, _, _ = imports
    job = prepare(client, tmp_path)
    staging = service.root / "staging" / job["id"]
    archive = staging / "archive.zip"
    original = archive.read_bytes()
    if damage == "missing_directory":
        shutil.rmtree(staging)
    else:
        archive.write_bytes(b"synthetic corruption")
    response = client.put(f"/api/ingestion/imports/{job['id']}/archive", content=original,
                          headers={"Content-Type": "application/zip"})
    assert response.status_code == 200, response.text
    assert response.json() == job
    assert archive.is_file()
    assert hashlib.sha256(archive.read_bytes()).digest() == hashlib.sha256(original).digest()
    reviewed = operation(client, job["id"], "preview", {"root": ""}).json()
    assert reviewed["status"] == "ready"
    assert confirm(client, reviewed).json()["added_count"] == 1
