"""Authenticated public import HTTP interface, SQLite memory and private files."""
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.test_dataset_zip_validation import archive, wav_bytes


@pytest.fixture
def imports(tmp_path):
    from app.database import Base, get_db
    from app.routes.dataset_imports import router, get_import_service, get_import_user
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_zip import ImportLimits

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    service = DatasetImports(tmp_path / "managed", limits=ImportLimits(free_bytes=1))
    app = FastAPI()
    app.include_router(router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_import_service] = lambda: service
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app, raise_server_exceptions=False)
    yield client, service, app, sessions
    client.close()
    engine.dispose()


def prepare(client, tmp_path, *, key="request-1", name="Birds", target_id=None, sample=1, root="", entries=None):
    response = client.post("/api/ingestion/imports", json={"request_key": key, "name": name,
        "description": "Synthetic", "target_id": target_id})
    assert response.status_code == 200, response.text
    job = response.json()
    data = archive(tmp_path / f"{key}.zip", entries or [("birds/a.wav", wav_bytes(sample))]).read_bytes()
    uploaded = client.put(f"/api/ingestion/imports/{job['id']}/archive", content=data,
                          headers={"Content-Type": "application/zip"})
    assert uploaded.status_code == 200, uploaded.text
    preview = client.post(f"/api/ingestion/imports/{job['id']}/preview", json={"root": root})
    assert preview.status_code == 200, preview.text
    return preview.json()


def confirm(client, job):
    return client.post(f"/api/ingestion/imports/{job['id']}/confirm", json={"preview_token": job["preview_token"]})


def test_import_is_local_queryable_downloadable_and_replayable(imports, tmp_path):
    client, service, _, _ = imports
    job = prepare(client, tmp_path)
    assert job["status"] == "ready"
    response = confirm(client, job)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "imported"
    assert result["sync_status"] == "pending"
    assert result["added_count"] == 1
    assert confirm(client, job).json() == result
    datasets = client.get("/api/ingestion/imports/datasets").json()["datasets"]
    assert len(datasets) == 1
    assert datasets[0]["file_count"] == 1
    files = client.get(f"/api/ingestion/imports/datasets/{result['dataset_id']}/files").json()["files"]
    assert len(files) == 1
    downloaded = client.get(f"/api/ingestion/imports/datasets/{result['dataset_id']}/files/{files[0]['sha256']}")
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == files[0]["sha256"]
    assert downloaded.content == wav_bytes()
    assert not (service.root.parent / "raw").exists()


def test_duplicate_and_label_conflict_do_not_change_published_membership(imports, tmp_path):
    client, _, _, _ = imports
    first = confirm(client, prepare(client, tmp_path)).json()
    target = first["dataset_id"]
    before = client.get(f"/api/ingestion/imports/datasets/{target}/files").json()
    duplicate = prepare(client, tmp_path, key="repeat", target_id=target,
                        entries=[("wrapper/birds/renamed.wav", wav_bytes())], root="wrapper")
    assert duplicate["preview"]["new_count"] == 0
    assert duplicate["preview"]["duplicate_collection"] is True
    repeated = confirm(client, duplicate)
    assert repeated.status_code == 200
    assert repeated.json()["added_count"] == 0
    conflict = prepare(client, tmp_path, key="conflict", target_id=target,
                       entries=[("motor/a.wav", wav_bytes())])
    assert conflict["status"] == "needs_correction"
    assert confirm(client, conflict).status_code == 409
    assert client.get(f"/api/ingestion/imports/datasets/{target}/files").json() == before


def test_stale_preview_and_changed_request_are_rejected(imports, tmp_path):
    client, _, _, _ = imports
    target = confirm(client, prepare(client, tmp_path)).json()["dataset_id"]
    older = prepare(client, tmp_path, key="older", target_id=target, sample=2)
    newer = prepare(client, tmp_path, key="newer", target_id=target, sample=3)
    assert confirm(client, newer).status_code == 200
    assert confirm(client, older).status_code == 409
    preview = client.post(f"/api/ingestion/imports/{older['id']}/preview", json={"root": ""}).json()
    assert confirm(client, older).status_code == 409
    assert confirm(client, preview).json()["added_count"] == 1
    changed = client.post("/api/ingestion/imports", json={"request_key": "older", "name": "Changed"})
    assert changed.status_code == 409


def test_owner_is_required_for_every_import_and_dataset_operation(imports, tmp_path):
    from app.routes.dataset_imports import get_import_user
    client, _, app, _ = imports
    job = prepare(client, tmp_path)
    target = confirm(client, job).json()["dataset_id"]
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.get("/api/ingestion/imports").json() == {"imports": []}
    assert client.get("/api/ingestion/imports/datasets").json() == {"datasets": []}
    for method, path, body in [
        ("get", f"/{job['id']}", None), ("post", f"/{job['id']}/preview", {"root": ""}),
        ("post", f"/{job['id']}/confirm", {"preview_token": job["preview_token"]}),
        ("post", f"/{job['id']}/cancel", None), ("get", f"/datasets/{target}/files", None),
        ("get", f"/datasets/{target}/files/{'a'*64}", None),
    ]:
        response = client.request(method, "/api/ingestion/imports" + path, json=body)
        assert response.status_code == 404
    assert client.post("/api/ingestion/imports", json={"request_key": "foreign", "name": "X", "target_id": target}).status_code == 404
    app.dependency_overrides.pop(get_import_user)
    assert client.get("/api/ingestion/imports").status_code == 401
    assert client.post("/api/ingestion/imports", json={"request_key": "unauth", "name": "X"}).status_code == 401


def test_cancel_expiry_and_cleanup_never_delete_confirmed_files(imports, tmp_path, monkeypatch):
    import time
    client, service, _, _ = imports
    confirmed = confirm(client, prepare(client, tmp_path)).json()
    job = prepare(client, tmp_path, key="cancel")
    assert client.post(f"/api/ingestion/imports/{job['id']}/cancel").json()["status"] == "cancelled"
    assert not service.stage(SimpleNamespace(id=job["id"])).exists()
    assert confirm(client, job).status_code == 409
    expired = prepare(client, tmp_path, key="expire")
    now = time.time()
    monkeypatch.setattr("app.services.dataset_imports.time.time", lambda: now + service.limits.ttl_seconds + 1)
    assert confirm(client, expired).status_code == 410
    assert client.get(f"/api/ingestion/imports/{expired['id']}").json()["status"] == "cancelled"
    assert client.get(f"/api/ingestion/imports/{confirmed['id']}").json()["status"] == "imported"
    assert (service.root / "objects" / confirmed["id"]).is_dir()


@pytest.mark.parametrize("boundary", ["before_move", "after_move", "database_publish"])
def test_interrupted_confirmation_recovers_without_hiding_previous_content(imports, tmp_path, monkeypatch, boundary):
    from sqlalchemy import event
    from app.models.dataset_import import DatasetImport
    from app.services import dataset_imports as module
    client, service, _, sessions = imports
    first = confirm(client, prepare(client, tmp_path)).json()
    target = first["dataset_id"]
    previous = client.get(f"/api/ingestion/imports/datasets/{target}/files").json()
    pending = prepare(client, tmp_path, key="pending", target_id=target, sample=2)
    original_rename, original_directory = module.os.rename, module._durable_directory

    def fail_move(*args):
        raise OSError("induced move failure")
    def fail_after_move(path):
        if path == service.root / "objects":
            raise OSError("induced directory fsync failure")
        return original_directory(path)
    def fail_publication(session):
        if any(isinstance(row, DatasetImport) and row.id == pending["id"] and row.status == "imported" for row in session.dirty):
            raise RuntimeError("induced publication failure")
    if boundary == "before_move":
        monkeypatch.setattr(module.os, "rename", fail_move)
    elif boundary == "after_move":
        monkeypatch.setattr(module, "_durable_directory", fail_after_move)
    else:
        event.listen(sessions.class_, "before_commit", fail_publication)
    try:
        assert confirm(client, pending).status_code == 500
        assert client.get(f"/api/ingestion/imports/{pending['id']}").json()["status"] == "committing"
        assert client.get(f"/api/ingestion/imports/datasets/{target}/files").json() == previous
        competing = prepare(client, tmp_path, key="competing", target_id=target, sample=3)
        assert confirm(client, competing).status_code == 409
    finally:
        monkeypatch.setattr(module.os, "rename", original_rename)
        monkeypatch.setattr(module, "_durable_directory", original_directory)
        if boundary == "database_publish":
            event.remove(sessions.class_, "before_commit", fail_publication)
    recovered = confirm(client, pending)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["added_count"] == 1
    assert confirm(client, pending).json() == recovered.json()
    assert len(client.get(f"/api/ingestion/imports/datasets/{target}/files").json()["files"]) == 2


def test_storage_lock_rejects_simultaneous_confirmation_and_preserves_counts(imports, tmp_path):
    client, service, _, sessions = imports
    job = prepare(client, tmp_path)
    with sessions() as db, service.mutation(db):
        assert confirm(client, job).status_code == 409
    assert confirm(client, job).json()["added_count"] == 1
    assert confirm(client, job).json()["added_count"] == 1


def test_archive_retry_payload_mismatch_and_server_receive_limit(imports, tmp_path):
    from dataclasses import replace
    client, service, _, _ = imports
    job = prepare(client, tmp_path)
    data = archive(tmp_path / "same.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    path = f"/api/ingestion/imports/{job['id']}/archive"
    assert client.put(path, content=data, headers={"Content-Type": "application/zip"}).json() == job
    before = client.get(f"/api/ingestion/imports/{job['id']}").json()
    assert client.put(path, content=b"changed", headers={"Content-Type": "application/zip"}).status_code == 409
    assert client.get(f"/api/ingestion/imports/{job['id']}").json() == before
    service.limits = replace(service.limits, received_bytes=1)
    assert client.put(path, content=data, headers={"Content-Type": "application/zip"}).status_code == 413
    assert client.get(f"/api/ingestion/imports/{job['id']}").json() == before


def test_same_collection_in_new_named_request_does_not_create_duplicate_dataset(imports, tmp_path):
    client, _, _, _ = imports
    target = confirm(client, prepare(client, tmp_path)).json()["dataset_id"]
    repeated = prepare(client, tmp_path, key="renamed", name="Renamed",
                       entries=[("wrapper/birds/new.wav", wav_bytes())], root="wrapper")
    result = confirm(client, repeated)
    assert result.status_code == 200
    assert result.json()["added_count"] == 0
    assert result.json()["dataset_id"] == target
    assert len(client.get("/api/ingestion/imports/datasets").json()["datasets"]) == 1


def test_downloadable_example_is_an_importable_synthetic_zip(imports, tmp_path):
    client, _, _, _ = imports
    example = client.get("/api/ingestion/imports/example.zip")
    assert example.status_code == 200
    assert example.headers["content-type"] == "application/zip"
    from app.services.dataset_zip import validate_zip, ImportLimits
    source = tmp_path / "example.zip"
    source.write_bytes(example.content)
    result = validate_zip(source, tmp_path / "example", root="aves", limits=ImportLimits())
    assert result["errors"] == []
    assert result["unique_count"] == 2
    assert result["classes"] == ["chucao", "colilarga"]


def test_active_admission_limit_and_expired_staging_cleanup(imports, tmp_path, monkeypatch):
    from dataclasses import replace
    import time
    client, service, _, _ = imports
    service.limits = replace(service.limits, concurrent_imports=1)
    first = prepare(client, tmp_path)
    extra = client.post("/api/ingestion/imports", json={"request_key": "second", "name": "Other"})
    assert extra.status_code == 429
    imported = confirm(client, first).json()
    assert client.post("/api/ingestion/imports", json={"request_key": "second", "name": "Other"}).status_code == 200
    now = time.time()
    monkeypatch.setattr("app.services.dataset_imports.time.time", lambda: now + service.limits.ttl_seconds + 1)
    assert client.post("/api/ingestion/imports", json={"request_key": "third", "name": "Third"}).status_code == 200
    assert not (service.root / "staging" / imported["id"]).exists()
    assert (service.root / "objects" / imported["id"]).is_dir()
