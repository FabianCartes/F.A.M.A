"""Synthetic publication/cleanup behavior through HTTP and explicit maintenance."""
from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_dataset_zip_validation import wav_bytes
import pytest


def test_cancel_schedules_cleanup_without_deleting_in_http(imports, tmp_path):
    client, service, _, sessions = imports
    source = prepare(client, tmp_path)
    archive = service.root / "staging" / source["id"] / "archive.zip"
    original = archive.read_bytes()
    cancelled = client.post(f"/api/ingestion/imports/{source['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert archive.read_bytes() == original
    with sessions() as db:
        service.cleanup(db, attempt_root=client.execution.root)
    assert not archive.exists()
    assert list(client.execution.root.iterdir()) == []
    assert client.get(f"/api/ingestion/imports/{source['id']}").json()["status"] == "cancelled"


def test_publication_contains_only_new_objects(imports, tmp_path):
    client, service, _, _ = imports
    first = confirm(client, prepare(client, tmp_path)).json()
    second = prepare(client, tmp_path, key="mixed", target_id=first["dataset_id"], entries=[
        ("birds/existing.wav", wav_bytes()), ("birds/new.wav", wav_bytes(2)),
        ("birds/internal.wav", wav_bytes(2))])
    result = confirm(client, second).json()
    assert result["status"] == "imported"
    assert result["added_count"] == 1
    objects = list((service.root / "objects" / second["id"]).iterdir())
    assert len(objects) == 1
    assert objects[0].read_bytes() == wav_bytes(2)


@pytest.mark.parametrize("duplicate", [False, True])
def test_success_reclaims_all_staging_without_ttl_and_preserves_download(imports, tmp_path, duplicate):
    client, service, _, sessions = imports
    source = prepare(client, tmp_path)
    first = confirm(client, source).json()
    if duplicate:
        source = prepare(client, tmp_path, key="duplicate", target_id=first["dataset_id"])
        assert confirm(client, source).json()["added_count"] == 0
    files_url = f"/api/ingestion/imports/datasets/{first['dataset_id']}/files"
    before = client.get(files_url).json()
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 2 if duplicate else 1, "failed": 0}
    assert not (service.root / "staging" / source["id"]).exists()
    assert list(client.execution.root.iterdir()) == []
    assert client.get(files_url).json() == before
    assert client.get(files_url + "/" + before["files"][0]["sha256"]).content == wav_bytes()
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 0, "failed": 0}


def test_failed_deletion_blocks_new_work_and_is_retryable_without_failing_success(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_cleanup as cleanup
    client, service, _, sessions = imports
    source = prepare(client, tmp_path)
    published = confirm(client, source).json()
    url = f"/api/ingestion/imports/{source['id']}"
    remove = cleanup.shutil.rmtree
    calls = []

    def interrupted(path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("synthetic partial deletion")
        remove(path)

    with monkeypatch.context() as patch:
        patch.setattr(cleanup.shutil, "rmtree", interrupted)
        with sessions() as db:
            assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 0, "failed": 1}
    assert client.get(url).json() == published
    assert client.post(url + "/sync", json={"request_key": "during-delete"}).status_code == 409
    assert client.post(url + "/confirm", json={"request_key": "during-delete",
        "preview_token": source["preview_token"]}).status_code == 409
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 1, "failed": 0}
    assert list(client.execution.root.iterdir()) == []
    assert client.get(url).json() == published
    assert confirm(client, source).json()["added_count"] == 1


def test_cleanup_recovers_expired_receipt_but_not_recent_useful_activity(imports, tmp_path, monkeypatch):
    import hashlib
    from app.services import dataset_import_cleanup as cleanup
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    client, service, _, sessions = imports
    migrate_receipts(sessions.kw["bind"], writers_stopped=True)
    migrate_chunks(sessions.kw["bind"], writers_stopped=True)
    base = "/api/ingestion/imports"
    source = client.post(base, json={"request_key": "activity", "name": "Activity"}).json()["id"]
    url = base + "/" + source
    from tests.test_dataset_zip_validation import archive
    data = archive(tmp_path / "receipt.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.post(url + "/receipt", json={"name": "receipt.zip", "size_bytes": len(data)}).status_code == 200
    assert client.put(url + "/receipt/chunks/0", content=data, headers={
        "Content-Type": "application/octet-stream", "X-Chunk-Offset": "0",
        "X-Chunk-SHA256": hashlib.sha256(data).hexdigest()}).status_code == 200
    assert client.post(url + "/receipt/finalize").status_code == 200
    now = cleanup.time.time()
    monkeypatch.setattr(cleanup.time, "time", lambda: now + service.limits.ttl_seconds - 1)
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root)["completed"] == 0
    # Polling must not extend activity. Expiry is measured from durable work.
    assert client.get(url).status_code == 200
    monkeypatch.setattr(cleanup.time, "time", lambda: now + service.limits.ttl_seconds + 10)
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root)["completed"] == 1
    assert client.get(url).json()["status"] == "cancelled"
    assert client.get(url + "/receipt").json()["reserved_bytes"] == 0


def test_new_preview_is_useful_activity_for_old_import(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_cleanup as cleanup
    from tests.test_dataset_import_api import operation
    client, service, _, sessions = imports
    source = prepare(client, tmp_path)
    now = cleanup.time.time()
    monkeypatch.setattr(cleanup.time, "time", lambda: now + service.limits.ttl_seconds + 10)
    assert operation(client, source["id"], "preview", {"root": ""}).json()["status"] == "ready"
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root)["completed"] == 0
    assert client.get(f"/api/ingestion/imports/{source['id']}").json()["status"] == "ready"


def test_new_upload_is_useful_activity_for_old_import(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_cleanup as cleanup
    from tests.test_dataset_zip_validation import archive
    client, service, _, sessions = imports
    source = client.post("/api/ingestion/imports", json={"request_key": "delayed-upload", "name": "Delayed"}).json()
    now = cleanup.time.time()
    monkeypatch.setattr(cleanup.time, "time", lambda: now + service.limits.ttl_seconds + 10)
    data = archive(tmp_path / "replacement.zip", [("birds/new.wav", wav_bytes(2))]).read_bytes()
    assert client.put(f"/api/ingestion/imports/{source['id']}/archive", content=data,
        headers={"Content-Type": "application/zip"}).status_code == 200
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root)["completed"] == 0


def test_cleanup_cli_is_explicit_and_does_not_execute_jobs(imports, tmp_path, monkeypatch, capsys):
    import json
    from tests.test_dataset_import_worker_cli import command
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    assert client.post(f"/api/ingestion/imports/{source['id']}/cancel").status_code == 200
    other = prepare(client, tmp_path, key="other")
    admitted = client.post(f"/api/ingestion/imports/{other['id']}/preview",
        json={"request_key": "pending", "root": ""}).json()
    main, args = command(imports, monkeypatch)
    assert main(args + ["--cleanup-only"]) == 0
    assert json.loads(capsys.readouterr().out) == {"completed": 1, "failed": 0}
    assert client.get(admitted["status_url"]).json()["status"] == "queued"
    assert not (service.root / "staging" / source["id"]).exists()


@pytest.mark.parametrize("lease", ["queued", "live", "expired"])
def test_cleanup_preserves_execution_until_recovery_is_evaluated(imports, tmp_path, monkeypatch, lease):
    from app.services import dataset_import_cleanup as cleanup
    client, service, _, sessions = imports
    source = prepare(client, tmp_path)
    queue = client.execution.queue
    queue.clock = lambda: 100.0
    job = queue.admit(1, source["id"], "preview", "lease-protection", {"root": ""})
    if lease != "queued":
        assert queue.claim(lease_seconds=10)["id"] == job["id"]
    if lease == "expired":
        queue.clock = lambda: 200.0
    before = (service.root / "staging" / source["id"] / "archive.zip").read_bytes()
    monkeypatch.setattr(cleanup.time, "time", lambda: 10**12)
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 0, "failed": 0}
    assert (service.root / "staging" / source["id"] / "archive.zip").read_bytes() == before
    assert client.get(f"/api/ingestion/imports/{source['id']}").json()["status"] == "ready"


def test_cleanup_and_receipt_resume_are_exclusive_without_holding_db_gate(imports, monkeypatch):
    import threading
    from app.services import dataset_import_cleanup as cleanup
    from tests.test_dataset_import_chunks import prepared, put
    from tests.test_dataset_import_receipts import dump
    client, service, _, sessions = imports
    url = prepared(imports, monkeypatch)
    assert put(client, url, 0, b"abcd").status_code == 200
    # Expiration claims the receiving receipt, then deletion blocks on a barrier.
    monkeypatch.setattr(cleanup.time, "time", lambda: 10**12)
    entered, release = threading.Event(), threading.Event()
    remove = cleanup.shutil.rmtree
    outcomes = []

    def blocked(path):
        entered.set()
        assert release.wait(5)
        remove(path)

    def clean():
        with sessions() as db:
            outcomes.append(service.cleanup(db, attempt_root=client.execution.root))

    with monkeypatch.context() as patch:
        patch.setattr(cleanup.shutil, "rmtree", blocked)
        thread = threading.Thread(target=clean)
        thread.start()
        try:
            assert entered.wait(5)
            before = dump(sessions)
            assert put(client, url, 1, b"efgh").status_code == 409
            assert client.post(url + "/finalize").status_code == 409
            assert client.post(url, json={"name": "input.zip", "size_bytes": 10}).status_code == 409
            assert dump(sessions) == before
            with sessions() as db:
                assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 0, "failed": 0}
            # Independent admission can acquire the queue gate during rmtree.
            assert client.post("/api/ingestion/imports", json={"request_key": "unrelated", "name": "Unrelated"}).status_code == 200
            assert client.get(url).status_code == 200
        finally:
            release.set()
            thread.join(5)
    assert not thread.is_alive()
    assert outcomes == [{"completed": 1, "failed": 0}]
    assert client.get(url).json()["reserved_bytes"] == 0
