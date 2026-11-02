"""Opt-in lifecycle through public HTTP/service operations; synthetic local bytes."""
from types import SimpleNamespace

import pytest

from tests.test_dataset_import_api import imports
from app.models.dataset_storage import StorageSchema, StoragePool
from app.services.dataset_storage import PhysicalStorage, UNAVAILABLE


@pytest.fixture
def physical(imports, monkeypatch, request):
    client, service, app, sessions = imports
    from tests.test_dataset_import_receipts import migrate
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    migrate(sessions)
    migrate_chunks(sessions.kw["bind"], writers_stopped=True)
    attempts = service.attempt_root
    roots = dict(imports=service.root, objects=service.root / "objects", attempts=attempts,
                 manifests=attempts, scratch=attempts, exports=attempts)
    policy = PhysicalStorage(roots=roots, pools=dict.fromkeys(roots, "ssd"), free_floors={"ssd": 1024},
                             manifest_bytes=getattr(request, "param", 64 * 1024**2))
    from app.services.dataset_imports import DatasetImports
    configured = DatasetImports(service.root, limits=service.limits, storage_policy=policy)
    from app.routes.dataset_imports import get_import_service
    app.dependency_overrides[get_import_service] = lambda: configured
    client.execution.service = configured
    configured.attempt_root = attempts
    space = SimpleNamespace(free=10**12)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda path: space)
    with sessions() as db:
        db.add(StorageSchema(id=1, version=1, state="active"))
        db.add(StoragePool(id="ssd", configuration_sha256=policy.configuration_sha256, free_floor_bytes=1024))
        db.commit()
    return client, configured, sessions, space


def create(client, key="one"):
    response = client.post("/api/ingestion/imports", json={"request_key": key, "name": key})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def reserve(client, identity, size=100):
    return client.post(f"/api/ingestion/imports/{identity}/receipt", json={"name": "small.zip", "size_bytes": size})


def test_receipt_reserves_archive_and_two_expansions_atomically(physical):
    client, service, sessions, space = physical
    identity = create(client)
    envelope = 100 + 2 * service.limits.expanded_bytes
    space.free = envelope + 1024 - 1
    rejected = reserve(client, identity)
    assert rejected.status_code == 507, rejected.text
    assert not service.stage(SimpleNamespace(id=identity)).exists()
    assert client.get(f"/api/ingestion/imports/{identity}/receipt").status_code == 404
    space.free += 1
    accepted = reserve(client, identity)
    assert accepted.status_code == 200, accepted.text
    # Logical receipt compatibility remains one expanded allowance.
    assert accepted.json()["reserved_bytes"] == 100 + service.limits.expanded_bytes
    assert reserve(client, identity).json() == accepted.json()


@pytest.mark.parametrize("operation", ["append", "finalize"])
def test_chunks_require_exact_live_archive_grant_before_writes(physical, operation):
    from sqlalchemy import update
    from app.models.dataset_storage import StorageGrant
    from tests.test_dataset_import_chunks import put
    client, service, sessions, space = physical
    identity = create(client)
    url = f"/api/ingestion/imports/{identity}/receipt"
    assert reserve(client, identity, 4).status_code == 200
    if operation == "finalize":
        assert put(client, url, 0, b"abcd").status_code == 200
    stage = service.stage(SimpleNamespace(id=identity))
    before = {p.name: p.read_bytes() for p in stage.iterdir()} if stage.exists() else {}
    receipt_before = client.get(url).json()
    # Fixture fault injection only; outcomes are observed through public calls.
    with sessions() as db:
        db.execute(update(StorageGrant).where(StorageGrant.resource_id == identity,
            StorageGrant.phase == "archive").values(token=9))
        db.commit()
    response = put(client, url, 0, b"abcd") if operation == "append" else client.post(url + "/finalize")
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": UNAVAILABLE}
    assert client.get(url).json() == receipt_before
    assert ({p.name: p.read_bytes() for p in stage.iterdir()} if stage.exists() else {}) == before
    assert client.post(f"/api/ingestion/imports/{identity}/cancel").status_code == 200
    second = create(client, "second")
    space.free = 4 + 2 * service.limits.expanded_bytes + 1024
    promised = reserve(client, second, 4)
    assert promised.status_code == 507, promised.text
    assert promised.json() == {"detail": "Espacio físico insuficiente."}


@pytest.mark.parametrize("configured,state", [(False, "active"), (True, "prepared")])
def test_incompatible_writer_configuration_fails_before_payload(physical, configured, state):
    client, service, sessions, _ = physical
    identity = create(client)
    if not configured:
        service.storage_policy = None
    with sessions() as db:
        db.get(StorageSchema, 1).state = state
        db.commit()
    response = reserve(client, identity)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": UNAVAILABLE}
    assert not service.stage(SimpleNamespace(id=identity)).exists()


def sealed(physical, tmp_path, key="one"):
    from tests.test_dataset_zip_validation import archive, wav_bytes
    from tests.test_dataset_import_chunks import put
    client, service, sessions, space = physical
    identity = create(client, key)
    data = archive(tmp_path / f"{key}.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert reserve(client, identity, len(data)).status_code == 200
    url = f"/api/ingestion/imports/{identity}/receipt"
    assert put(client, url, 0, data).status_code == 200
    assert client.post(url + "/finalize").status_code == 200
    return identity, len(data)


def test_attempt_rejects_missing_initial_authority_without_extraction(physical, tmp_path):
    from sqlalchemy import update
    from app.models.dataset_storage import StorageGrant
    from tests.test_dataset_import_api import operation
    client, service, sessions, space = physical
    identity, _ = sealed(physical, tmp_path)
    with sessions() as db:
        db.execute(update(StorageGrant).where(StorageGrant.resource_id == identity,
            StorageGrant.phase == "initial").values(policy_sha256="0" * 64))
        db.commit()
    response = operation(client, identity, "preview", {"root": ""})
    assert response.json()["status"] == "failed", response.text
    assert response.json()["error"] == {"code": "execution_failed"}
    assert not list(service.attempt_root.glob("*/files"))


def test_preview_confirm_transfer_and_cleanup_retain_published_charge(physical, tmp_path):
    from tests.test_dataset_import_api import operation, confirm
    client, service, sessions, space = physical
    identity, size = sealed(physical, tmp_path)
    space.free = size + 2 * service.limits.expanded_bytes + 1024
    preview = operation(client, identity, "preview", {"root": ""}).json()
    assert preview["status"] == "ready", preview
    published = confirm(client, preview).json()
    assert published["status"] == "imported", published
    assert (service.root / "objects" / identity).is_dir()
    # Publication alone cannot promise that staging or retained bytes vanished.
    second = create(client, "second")
    assert reserve(client, second).status_code == 507
    with sessions() as db:
        assert service.cleanup(db)["completed"] == 1
    assert not service.stage(SimpleNamespace(id=identity)).exists()
    assert not list(service.attempt_root.glob("*-*-*"))
    from tests.test_dataset_zip_validation import wav_bytes
    retained = len(wav_bytes())
    space.free = 100 + 2 * service.limits.expanded_bytes + 1024 + retained - 1
    assert reserve(client, second).status_code == 507
    space.free += 1
    assert reserve(client, second).status_code == 200


def test_unconfigured_active_service_cannot_create_import(physical):
    client, service, sessions, _ = physical
    service.storage_policy = None
    before = sorted(p.name for p in service.root.iterdir())
    response = client.post("/api/ingestion/imports", json={"request_key": "unsafe", "name": "Unsafe"})
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": UNAVAILABLE}
    assert sorted(p.name for p in service.root.iterdir()) == before


def test_physical_whole_body_upload_is_refused_without_unreserved_writes(physical):
    client, service, sessions, _ = physical
    identity = create(client)
    response = client.put(f"/api/ingestion/imports/{identity}/archive", content=b"unsafe",
                          headers={"Content-Type": "application/zip"})
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": UNAVAILABLE}
    assert not service.stage(SimpleNamespace(id=identity)).exists()
    assert client.post(f"/api/ingestion/imports/{identity}/cancel").json()["status"] == "cancelled"


def test_physical_exports_are_refused_before_admission(physical, tmp_path):
    from fastapi import HTTPException
    from app.services.dataset_exports import ExportQueue
    from tests.test_dataset_import_api import operation, confirm
    client, service, sessions, _ = physical
    identity, _ = sealed(physical, tmp_path)
    job = operation(client, identity, "preview", {"root": ""}).json()
    dataset = confirm(client, job).json()["dataset_id"]
    queue = ExportQueue(sessions, service)
    with pytest.raises(HTTPException) as error:
        queue.admit(1, dataset, 1, "unsafe")
    assert error.value.status_code == 503
    assert error.value.detail == "Las exportaciones no están habilitadas con presupuesto físico."
    assert queue.list(1, dataset) == {"exports": []}
    with pytest.raises(HTTPException) as claim:
        queue.claim(lease_seconds=60)
    assert claim.value.status_code == 503
    assert claim.value.detail == error.value.detail


@pytest.mark.parametrize("physical", [32], indirect=True)
def test_manifest_writer_cannot_exceed_charged_envelope(physical, tmp_path):
    from tests.test_dataset_import_manifests import ManifestObjects
    from tests.test_dataset_import_api import operation, confirm
    client, service, sessions, space = physical
    identity, _ = sealed(physical, tmp_path)
    job = operation(client, identity, "preview", {"root": ""}).json()
    confirm(client, job)
    storage = ManifestObjects()
    from app.routes.dataset_imports import get_import_storage
    client.import_app.dependency_overrides[get_import_storage] = lambda: storage
    response = operation(client, identity, "sync")
    assert response.json()["status"] == "failed", response.text
    assert response.json()["error"] == {"code": "execution_failed"}
    assert not any(key.endswith(".json") for key in storage.objects)
    assert all(p.stat().st_size <= 32 for p in service.attempt_root.glob("*/manifest.json"))


def test_manifest_writer_rechecks_floor_after_object_transfer(physical, tmp_path):
    from tests.test_dataset_import_manifests import ManifestObjects
    from tests.test_dataset_import_api import operation, confirm
    client, service, sessions, space = physical
    identity, _ = sealed(physical, tmp_path)
    job = operation(client, identity, "preview", {"root": ""}).json()
    confirm(client, job)
    class FallingSpace(ManifestObjects):
        def ensure(self, *args):
            result = super().ensure(*args)
            space.free = 1023
            return result
    storage = FallingSpace()
    from app.routes.dataset_imports import get_import_storage
    client.import_app.dependency_overrides[get_import_storage] = lambda: storage
    response = operation(client, identity, "sync")
    assert response.json()["status"] == "failed", response.text
    assert not any(key.endswith(".json") for key in storage.objects)
    assert not list(service.attempt_root.glob("*/manifest.json"))


def test_cleanup_refuses_wrong_attempt_root_before_deletion_or_release(physical, tmp_path):
    from fastapi import HTTPException
    client, service, sessions, space = physical
    identity, size = sealed(physical, tmp_path)
    assert client.post(f"/api/ingestion/imports/{identity}/cancel").status_code == 200
    wrong = tmp_path / "unrelated-attempts"
    wrong.mkdir(mode=0o700)
    with sessions() as db, pytest.raises(HTTPException) as error:
        service.cleanup(db, attempt_root=wrong)
    assert error.value.status_code == 503
    assert error.value.detail == UNAVAILABLE
    assert (service.stage(SimpleNamespace(id=identity)) / "archive.zip").is_file()
    second = create(client, "second")
    space.free = size + 2 * service.limits.expanded_bytes + 1024
    assert reserve(client, second).status_code == 507


def test_cleanup_cannot_retire_unwinding_writer_even_after_cancellation(physical, tmp_path):
    import fcntl
    import os
    from tests.test_dataset_import_api import operation
    client, service, sessions, space = physical
    identity, size = sealed(physical, tmp_path)
    preview = operation(client, identity, "preview", {"root": ""}).json()
    assert preview["status"] == "ready"
    directory = next(service.attempt_root.glob("*-*-*"))
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert client.post(f"/api/ingestion/imports/{identity}/cancel").status_code == 200
        with sessions() as db:
            assert service.cleanup(db) == {"completed": 0, "failed": 0}
        second = create(client, "second")
        space.free = size + 2 * service.limits.expanded_bytes + 1024
        assert reserve(client, second).status_code == 507
        assert directory.is_dir()
        assert (service.stage(SimpleNamespace(id=identity)) / "archive.zip").is_file()
    finally:
        os.close(fd)
    with sessions() as db:
        assert service.cleanup(db)["completed"] == 1
    assert reserve(client, second).status_code == 200


def test_sync_after_cleanup_needs_only_manifest_not_retired_archive(physical, tmp_path):
    from tests.test_dataset_import_manifests import ManifestObjects
    from tests.test_dataset_import_api import operation, confirm
    from app.routes.dataset_imports import get_import_storage
    client, service, sessions, space = physical
    identity, _ = sealed(physical, tmp_path)
    preview = operation(client, identity, "preview", {"root": ""}).json()
    confirm(client, preview)
    with sessions() as db:
        assert service.cleanup(db)["completed"] == 1
    storage = ManifestObjects()
    client.import_app.dependency_overrides[get_import_storage] = lambda: storage
    result = operation(client, identity, "sync")
    assert result.json().get("sync_status") == "synced", result.text
    assert any(key.endswith(".json") for key in storage.objects)


@pytest.mark.parametrize("free", [1023, 1026])
def test_chunk_append_rechecks_physical_floor_without_acknowledging_bytes(physical, free):
    from tests.test_dataset_import_chunks import put
    client, service, sessions, space = physical
    identity = create(client)
    assert reserve(client, identity, 4).status_code == 200
    url = f"/api/ingestion/imports/{identity}/receipt"
    before = client.get(url).json()
    space.free = free
    rejected = put(client, url, 0, b"abcd")
    assert rejected.status_code == 507, rejected.text
    assert rejected.json() == {"detail": "Espacio físico insuficiente."}
    assert client.get(url).json() == before
    path = service.stage(SimpleNamespace(id=identity)) / "receiving.part"
    assert not path.exists() or path.stat().st_size == 0
    space.free = 10**12
    assert put(client, url, 0, b"abcd").json()["received_bytes"] == 4


def test_busy_reviewed_preview_keeps_its_charge_until_actual_unlock(physical, tmp_path):
    import fcntl
    import os
    from tests.test_dataset_import_api import operation, confirm
    client, service, sessions, space = physical
    identity, size = sealed(physical, tmp_path)
    preview = operation(client, identity, "preview", {"root": ""}).json()
    space.free = size + 2 * service.limits.expanded_bytes + 1024
    directory = next(service.attempt_root.glob("*-*-*"))
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rejected = confirm(client, preview)
        assert rejected.json()["status"] == "failed", rejected.text
        assert not (service.root / "objects" / identity).exists()
        assert list((directory / "files").iterdir())
    finally:
        os.close(fd)
    accepted = confirm(client, preview)
    assert accepted.json()["status"] == "imported", accepted.text


def test_failed_deletion_durability_keeps_full_charge_until_retry(physical, tmp_path, monkeypatch):
    from app.services import dataset_imports
    client, service, sessions, space = physical
    identity, size = sealed(physical, tmp_path)
    assert client.post(f"/api/ingestion/imports/{identity}/cancel").status_code == 200
    second = create(client, "second")
    durable = dataset_imports._durable_directory
    def fail_root(path):
        if path == service.attempt_root:
            raise OSError("synthetic directory fsync failure")
        return durable(path)
    with monkeypatch.context() as patch:
        patch.setattr(dataset_imports, "_durable_directory", fail_root)
        with sessions() as db:
            assert service.cleanup(db) == {"completed": 0, "failed": 1}
    space.free = size + 2 * service.limits.expanded_bytes + 1024
    assert reserve(client, second).status_code == 507
    with sessions() as db:
        assert service.cleanup(db)["completed"] == 1
    assert reserve(client, second).status_code == 200
