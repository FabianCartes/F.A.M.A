"""Real durable operations through public worker and authenticated HTTP reads."""
from pathlib import Path

import pytest

from tests.test_dataset_import_api import imports, prepare


def executor(imports, tmp_path):
    from scripts.migrate_dataset_import_jobs import migrate_jobs
    from app.services.dataset_import_execution import ImportExecution
    from app.services.dataset_import_jobs import ImportJobQueue
    client, service, _, sessions = imports
    migrate_jobs(sessions.kw["bind"], writers_stopped=True)
    queue = ImportJobQueue(sessions, clock=lambda: 100.0)
    root = client.execution.root
    return queue, ImportExecution(queue, service, root)


@pytest.mark.parametrize("imports", [True], indirect=True)
def test_worker_reports_sandbox_refusal_without_publishing(imports, tmp_path, monkeypatch):
    import subprocess
    from tests.test_dataset_zip_validation import archive, wav_bytes

    client, _, _, _ = imports
    base = "/api/ingestion/imports"
    source = client.post(base, json={"request_key": "sandbox-refusal", "name": "Refused"}).json()["id"]
    data = archive(tmp_path / "input.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"{base}/{source}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200

    def unavailable(*args, **kwargs):
        raise OSError("synthetic missing sandbox")

    monkeypatch.setattr(subprocess, "Popen", unavailable)
    admitted = client.post(f"{base}/{source}/preview", json={"request_key": "refused-preview", "root": ""})
    assert admitted.status_code == 202
    assert client.execution.run_once()
    state = client.get(f"{base}/{source}").json()
    assert state["status"] == "needs_correction"
    issues = client.get(f"{base}/{source}/issues").json()["issues"]
    assert [issue["code"] for issue in issues] == ["sandbox_unavailable"]
    assert client.get(base + "/datasets").json()["datasets"] == []
    assert client.post(f"{base}/{source}/confirm", json={"request_key": "denied", "preview_token": state["preview_token"]}).status_code == 409


def test_real_preview_and_confirm_publish_readable_dataset(imports, tmp_path):
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    queue, execution = executor(imports, tmp_path)
    admitted = queue.admit(1, source["id"], "preview", "preview-2", {"root": ""})
    assert execution.run_once()
    assert queue.get(1, admitted["id"])["status"] == "succeeded"
    reviewed = client.get(f"/api/ingestion/imports/{source['id']}").json()
    assert reviewed["status"] == "ready"
    confirmation = queue.admit(1, source["id"], "confirm", "confirm", {
        "preview_token": reviewed["preview_token"]})
    assert execution.run_once()
    result = queue.get(1, confirmation["id"])
    assert result["status"] == "succeeded", result
    assert result["result"]["added_count"] == 1
    dataset = result["result"]["dataset_id"]
    files = client.get(f"/api/ingestion/imports/datasets/{dataset}/files").json()["files"]
    assert len(files) == 1
    downloaded = client.get(f"/api/ingestion/imports/datasets/{dataset}/files/{files[0]['sha256']}")
    assert downloaded.status_code == 200
    assert not (service.stage(type("Source", (), {"id": source["id"]})()) / "files").is_symlink()


def test_expired_attempt_cannot_publish_real_preview(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    before = client.get(f"/api/ingestion/imports/{source['id']}").json()
    queue, execution = executor(imports, tmp_path)
    job = queue.admit(1, source["id"], "preview", "stale", {"root": ""})
    validate = module.validate_zip

    def expire(*args, **kwargs):
        result = validate(*args, **kwargs)
        queue.clock = lambda: 200.0
        return result

    monkeypatch.setattr(module, "validate_zip", expire)
    assert execution.run_once()
    after = client.get(f"/api/ingestion/imports/{source['id']}").json()
    assert {k: v for k, v in after.items() if k != "execution"} == {k: v for k, v in before.items() if k != "execution"}
    assert queue.get(1, job["id"])["status"] == "running"
    assert list(execution.root.glob("*"))


def test_stale_confirmation_cannot_rename_or_publish_membership(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    queue, execution = executor(imports, tmp_path)
    admitted = queue.admit(1, source["id"], "confirm", "confirm", {"preview_token": source["preview_token"]})
    digest = module.digest_file

    def expire(path):
        result = digest(path)
        queue.clock = lambda: 200.0
        return result

    monkeypatch.setattr(module, "digest_file", expire)
    assert execution.run_once()
    assert not (service.root / "objects" / source["id"]).exists()
    assert client.get("/api/ingestion/imports/datasets").json()["datasets"] == []
    assert queue.get(1, admitted["id"])["status"] == "running"


def test_rename_before_commit_recovers_without_duplicate_membership(imports, tmp_path, monkeypatch):
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    queue, execution = executor(imports, tmp_path)
    job = queue.admit(1, source["id"], "confirm", "confirm", {"preview_token": source["preview_token"]})
    durable = module._durable_directory

    def crash(path):
        if path == service.root / "objects":
            raise OSError("synthetic interruption after rename")
        return durable(path)

    monkeypatch.setattr(module, "_durable_directory", crash)
    assert execution.run_once()
    assert queue.get(1, job["id"])["status"] == "failed"
    assert (service.root / "objects" / source["id"]).is_dir()
    assert client.get(f"/api/ingestion/imports/{source['id']}").json()["status"] == "committing"
    assert client.get("/api/ingestion/imports/datasets").json()["datasets"] == []
    monkeypatch.setattr(module, "_durable_directory", durable)
    retry = queue.admit(1, source["id"], "confirm", "recover", {"preview_token": source["preview_token"]})
    assert execution.run_once()
    result = queue.get(1, retry["id"])
    assert result["status"] == "succeeded", result
    dataset = result["result"]["dataset_id"]
    assert len(client.get(f"/api/ingestion/imports/datasets/{dataset}/files").json()["files"]) == 1
    replay = queue.admit(1, source["id"], "confirm", "replay", {"preview_token": source["preview_token"]})
    assert execution.run_once()
    assert queue.get(1, replay["id"])["result"] == result["result"]


def test_cleanup_protects_queued_and_recoverable_work_and_is_not_triggered_by_http(imports, tmp_path, monkeypatch):
    from app.services import dataset_imports as module
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    queue, execution = executor(imports, tmp_path)
    queue.admit(1, source["id"], "preview", "pending", {"root": ""})
    monkeypatch.setattr(module.time, "time", lambda: 10**12)
    with queue.sessions() as db:
        service.cleanup(db)
    assert client.get(f"/api/ingestion/imports/{source['id']}").json()["status"] == "ready"
    assert (service.root / "staging" / source["id"] / "archive.zip").is_file()
    assert client.post("/api/ingestion/imports", json={"request_key": "other", "name": "Other"}).status_code == 200
    assert (service.root / "staging" / source["id"] / "archive.zip").is_file()


def test_sync_rechecks_previously_synced_content_and_keeps_network_outside_publication(imports, tmp_path):
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    queue, execution = executor(imports, tmp_path)
    confirmation = queue.admit(1, source["id"], "confirm", "confirm", {"preview_token": source["preview_token"]})
    assert execution.run_once()
    dataset = queue.get(1, confirmation["id"])["result"]["dataset_id"]

    class Storage:
        calls = 0

        def ensure(self, *args):
            self.calls += 1
            # Claim needs the gate: a held publication transaction would block
            # or corrupt this independent operation on the synthetic DB.
            assert queue.claim(lease_seconds=10) is None
            assert client.get(f"/api/ingestion/imports/datasets/{dataset}/files").status_code == 200
            return "generation-1"

    storage = execution.storage = Storage()
    first = queue.admit(1, source["id"], "sync", "sync-1", {})
    assert execution.run_once()
    assert queue.get(1, first["id"])["status"] == "succeeded"
    assert storage.calls == 1
    second = queue.admit(1, source["id"], "sync", "sync-2", {})
    assert execution.run_once()
    assert queue.get(1, second["id"])["status"] == "succeeded"
    assert storage.calls == 2


def test_http_cancel_and_upload_cannot_delete_or_replace_active_source(imports, tmp_path):
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    queue, _ = executor(imports, tmp_path)
    queue.admit(1, source["id"], "preview", "pending", {"root": ""})
    before = (service.root / "staging" / source["id"] / "archive.zip").read_bytes()
    assert client.post(f"/api/ingestion/imports/{source['id']}/cancel").status_code == 409
    assert client.put(f"/api/ingestion/imports/{source['id']}/archive", content=before,
                      headers={"Content-Type": "application/zip"}).status_code == 409
    assert (service.root / "staging" / source["id"] / "archive.zip").read_bytes() == before


def test_replaced_real_validator_cannot_overwrite_successor_preview(imports, tmp_path, monkeypatch):
    import threading
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    source = prepare(client, tmp_path)
    queue, first = executor(imports, tmp_path)
    first.worker.heartbeat_wait = lambda stop, interval: stop.wait()
    queue.admit(1, source["id"], "preview", "recovery", {"root": ""})
    blocked, release = threading.Event(), threading.Event()
    original = module.validate_zip
    paths = []

    def validate(archive, staging, **kwargs):
        paths.append(staging)
        result = original(archive, staging, **kwargs)
        if len(paths) == 1:
            blocked.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(module, "validate_zip", validate)
    thread = threading.Thread(target=first.run_once)
    thread.start()
    try:
        assert blocked.wait(5)
        # Queries and unrelated admission remain available during decoding.
        assert client.get(f"/api/ingestion/imports/{source['id']}/files").status_code == 200
        assert client.post("/api/ingestion/imports", json={"request_key": "independent", "name": "Independent"}).status_code == 200
        queue.clock = lambda: 200.0
        second = module.ImportExecution(queue, service, first.root)
        assert second.run_once()
        successor = client.get(f"/api/ingestion/imports/{source['id']}").json()
        assert successor["execution"]["status"] == "succeeded"
        assert paths[0] != paths[1]
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert client.get(f"/api/ingestion/imports/{source['id']}").json() == successor


def test_cleanup_preserves_inflight_receipt(imports, tmp_path, monkeypatch):
    import threading
    from app.services import dataset_imports as module
    from tests.test_dataset_zip_validation import archive, wav_bytes
    client, service, _, sessions = imports
    base = "/api/ingestion/imports"
    source = client.post(base, json={"request_key": "inflight", "name": "In flight"}).json()["id"]
    data = archive(tmp_path / "inflight.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    blocked, release = threading.Event(), threading.Event()
    original_space = service.space
    results = []

    def space():
        blocked.set()
        assert release.wait(5)
        original_space()

    monkeypatch.setattr(service, "space", space)
    thread = threading.Thread(target=lambda: results.append(client.put(
        f"{base}/{source}/archive", content=data, headers={"Content-Type": "application/zip"})))
    thread.start()
    try:
        assert blocked.wait(5)
        expired_at = module.time.time() + service.limits.ttl_seconds + 1
        monkeypatch.setattr(module.time, "time", lambda: expired_at)
        with sessions() as db:
            service.cleanup(db)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert len(results) == 1
    assert results[0].status_code == 200, results[0].text
    assert (service.root / "staging" / source / "archive.zip").read_bytes() == data
