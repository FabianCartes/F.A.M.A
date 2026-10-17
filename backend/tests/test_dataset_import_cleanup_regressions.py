"""Regression probes promoted from independent T5 lifecycle verification."""
import threading
import hashlib

from tests.test_dataset_import_api import imports, prepare, confirm, operation
from tests.test_dataset_import_receipts import dump

BASE = "/api/ingestion/imports"


def cleanup(client, service, sessions):
    with sessions() as db:
        return service.cleanup(db, attempt_root=client.execution.root)


def hashes(service):
    return {str(path.relative_to(service.root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in service.root.rglob("*") if path.is_file()}


def test_retry_preserves_attempt_root_fsync_obligation_after_last_directory_disappears(imports, tmp_path, monkeypatch):
    from app.services import dataset_imports

    client, service, _, sessions = imports
    source = prepare(client, tmp_path)
    published = confirm(client, source).json()
    root = client.execution.root
    durable = dataset_imports._durable_directory
    calls = []

    def fail_empty_attempt_root(path):
        if path == root and not list(root.iterdir()):
            calls.append(path)
            raise OSError("synthetic attempt-root fsync failure after final deletion")
        return durable(path)

    monkeypatch.setattr(dataset_imports, "_durable_directory", fail_empty_attempt_root)
    assert cleanup(client, service, sessions) == {"completed": 0, "failed": 1}
    assert list(root.iterdir()) == []
    assert cleanup(client, service, sessions) == {"completed": 0, "failed": 1}
    assert len(calls) == 2
    assert client.get(BASE + "/" + source["id"]).json() == published
    monkeypatch.setattr(dataset_imports, "_durable_directory", durable)
    assert cleanup(client, service, sessions) == {"completed": 1, "failed": 0}
    assert cleanup(client, service, sessions) == {"completed": 0, "failed": 0}
    assert client.get(BASE + "/" + source["id"]).json() == published


def test_failed_sync_after_completed_cleanup_is_reclaimed(imports, tmp_path):
    from app.routes.dataset_imports import get_import_storage

    client, service, app, sessions = imports
    source = prepare(client, tmp_path)
    published = confirm(client, source).json()
    cleanup(client, service, sessions)
    old = set(client.execution.root.iterdir())

    class UnavailableObjects:
        def ensure(self, *args):
            raise RuntimeError("synthetic storage unavailable")

    app.dependency_overrides[get_import_storage] = lambda: UnavailableObjects()
    failed = operation(client, source["id"], "sync").json()
    assert failed["status"] == "failed"
    new = set(client.execution.root.iterdir()) - old
    assert len(new) == 1
    url = BASE + "/datasets/" + published["dataset_id"] + "/files"
    before = client.get(url).content
    cleanup(client, service, sessions)
    assert client.get(BASE + "/" + source["id"]).json()["status"] == "imported"
    assert client.get(url).content == before
    assert not any(path.exists() for path in new)


def test_timed_out_callback_protects_files_until_it_stops(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_execution as execution

    client, service, _, sessions = imports
    source = prepare(client, tmp_path)
    entered, release = threading.Event(), threading.Event()
    digest, validate = execution.digest_file, execution.validate_zip
    validation_calls = []

    def delayed(path):
        result = digest(path)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(execution, "digest_file", delayed)
    def observed_validation(*args, **kwargs):
        validation_calls.append(args)
        return validate(*args, **kwargs)
    monkeypatch.setattr(execution, "validate_zip", observed_validation)
    response = client.post(BASE + "/" + source["id"] + "/preview",
        json={"request_key": "slow-hash", "root": ""})
    assert response.status_code == 202
    client.execution.worker.execution_seconds = 1
    try:
        assert client.execution.run_once()
        assert entered.is_set()
        assert client.get(response.json()["status_url"]).json()["error"] == {"code": "execution_timeout"}
        monkeypatch.setattr("time.time", lambda: 10**12)
        before = dump(sessions), hashes(service)
        public_before = client.get(BASE + "/" + source["id"]).content
        # Lease loss is not proof that trusted callback file activity stopped.
        assert cleanup(client, service, sessions) == {"completed": 0, "failed": 0}
        assert (dump(sessions), hashes(service)) == before
        assert client.get(BASE + "/" + source["id"]).content == public_before
        assert (service.root / "staging" / source["id"] / "archive.zip").is_file()
    finally:
        release.set()
        client.execution.worker._work.join(5)
    assert not client.execution.worker._work.is_alive()
    assert validation_calls == []
    assert (dump(sessions), hashes(service)) == before
    assert cleanup(client, service, sessions) == {"completed": 1, "failed": 0}
    assert not any(client.execution.root.iterdir())
    assert client.get(BASE + "/" + source["id"]).json()["status"] == "cancelled"
    assert cleanup(client, service, sessions) == {"completed": 0, "failed": 0}
