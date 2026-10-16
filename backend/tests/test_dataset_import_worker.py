"""Public execution operations; synthetic clocks and event barriers only."""
import pytest

from tests.test_dataset_import_api import imports
from tests.test_dataset_import_jobs import queue_fixture


def test_claim_recovery_fences_every_stale_write_and_preserves_capacity(imports):
    from app.services.dataset_import_jobs import LeaseLost

    queue, source = queue_fixture(imports)
    job = queue.admit(1, source, "preview", "one", {"root": ""})
    first = queue.claim(lease_seconds=10)
    assert first["id"] == job["id"]
    assert (first["attempt"], first["token"]) == (1, 1)
    assert queue.claim(lease_seconds=10) is None
    queue.progress(first, stage="validating", progress=25)
    queue.clock = lambda: 110.0
    before = queue.get(1, job["id"])

    def dump():
        with queue.sessions.kw["bind"].connect() as connection:
            return "\n".join(connection.connection.driver_connection.iterdump())

    for operation in (lambda: queue.heartbeat(first, lease_seconds=10),
                      lambda: queue.progress(first, stage="validating", progress=50),
                      lambda: queue.finish(first, result={"added_count": 9})):
        persisted = dump()
        with pytest.raises(LeaseLost):
            operation()
        assert dump() == persisted
        assert queue.get(1, job["id"]) == before
        assert queue.active_counts(1) == {"global": 1, "owner": 1}
    second = queue.claim(lease_seconds=10)
    assert (second["attempt"], second["token"]) == (2, 2)
    queue.finish(second, result={"added_count": 2})
    current = queue.get(1, job["id"])
    with pytest.raises(LeaseLost):
        queue.finish(first, result={"added_count": 9})
    assert queue.get(1, job["id"]) == current
    assert current["result"] == {"added_count": 2}
    assert queue.active_counts(1) == {"global": 0, "owner": 0}


def test_worker_runs_callback_without_transaction_and_uses_private_attempt_staging(imports, tmp_path):
    from app.services.dataset_import_worker import ImportJobWorker

    queue, source = queue_fixture(imports)
    job = queue.admit(1, source, "preview", "one", {"root": ""})
    paths = []

    def execute(attempt, staging, report):
        paths.append(staging)
        assert staging.is_dir() and staging.stat().st_mode & 0o777 == 0o700
        assert queue.get(1, job["id"])["status"] == "running"
        report(stage="validating", progress=20)
        return {"added_count": 2}

    worker = ImportJobWorker(queue, tmp_path, execute, lease_seconds=10)
    assert worker.run_once() is True
    assert worker.run_once() is False
    assert queue.get(1, job["id"])["result"] == {"added_count": 2}
    assert job["id"] in paths[0].name and "-1-1" in paths[0].name


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), True, 3601])
def test_invalid_lease_changes_nothing(imports, duration):
    queue, source = queue_fixture(imports)
    job = queue.admit(1, source, "preview", "one", {"root": ""})
    with pytest.raises(ValueError):
        queue.claim(lease_seconds=duration)
    assert queue.get(1, job["id"]) == job


def test_separate_heartbeat_keeps_blocked_executor_current(imports, tmp_path):
    import threading
    from app.services.dataset_import_worker import ImportJobWorker

    queue, source = queue_fixture(imports)
    job = queue.admit(1, source, "preview", "one", {"root": ""})
    entered, tick, renewed, release = (threading.Event() for _ in range(4))
    errors = []

    def wait(stop, interval):
        assert tick.wait(5)
        tick.clear()
        if release.is_set():
            return True
        return False

    def execute(attempt, staging, report):
        entered.set()
        assert renewed.wait(5)
        # Heartbeat has committed using another session while this was blocked.
        assert queue.get(1, job["id"])["heartbeat_at"] == 105
        queue.clock = lambda: 110.0
        assert queue.claim(lease_seconds=10) is None
        release.set()
        tick.set()
        return {"added_count": 1}

    original = queue.heartbeat

    def heartbeat(*args, **kwargs):
        original(*args, **kwargs)
        renewed.set()

    queue.heartbeat = heartbeat
    worker = ImportJobWorker(queue, tmp_path, execute, lease_seconds=10, heartbeat_wait=wait)

    def run():
        try:
            worker.run_once()
        except Exception as error:
            errors.append(type(error).__name__)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(5)
        queue.clock = lambda: 105.0
        tick.set()
        thread.join(10)
        assert not thread.is_alive() and errors == []
        assert queue.get(1, job["id"])["status"] == "succeeded"
    finally:
        release.set()
        renewed.set()
        tick.set()
        thread.join(5)


def test_stale_worker_staging_cannot_replace_current_database_result(imports, tmp_path):
    from app.services.dataset_import_worker import ImportJobWorker

    queue, source = queue_fixture(imports)
    job = queue.admit(1, source, "preview", "one", {"root": ""})
    paths = []

    def replacement(attempt, staging, report):
        paths.append(staging)
        return {"added_count": 2}

    def superseded(attempt, staging, report):
        paths.append(staging)
        queue.clock = lambda: 110.0
        assert ImportJobWorker(queue, tmp_path, replacement, lease_seconds=10).run_once()
        with pytest.raises(Exception, match="lease lost"):
            report(stage="validating", progress=99)
        return {"added_count": 9}

    assert ImportJobWorker(queue, tmp_path, superseded, lease_seconds=10).run_once()
    assert len(set(paths)) == 2 and all(path.is_dir() for path in paths)
    assert queue.get(1, job["id"])["result"] == {"added_count": 2}


def test_callback_errors_are_allowlisted_and_release_capacity(imports, tmp_path):
    from app.services.dataset_import_worker import ImportJobWorker

    queue, source = queue_fixture(imports)
    job = queue.admit(1, source, "preview", "one", {"root": ""})

    def execute(*args):
        raise RuntimeError("secret /private/path")

    assert ImportJobWorker(queue, tmp_path, execute).run_once()
    result = queue.get(1, job["id"])
    assert result["status"] == "failed" and result["error"] == {"code": "execution_failed"}
    assert result["result"] == {}
    assert queue.active_counts(1) == {"global": 0, "owner": 0}


def test_independent_job_executes_while_first_callback_is_active(imports, tmp_path):
    from app.services.dataset_import_worker import ImportJobWorker

    queue, source = queue_fixture(imports, owner_limit=2)
    client, service, _, _ = imports
    second_source = client.post("/api/ingestion/imports", json={
        "request_key": "independent", "name": "Other synthetic"}).json()["id"]
    data = (service.root.parent / "queue.zip").read_bytes()
    assert client.put(f"/api/ingestion/imports/{second_source}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    first = queue.admit(1, source, "preview", "first", {"root": ""})
    queue.clock = lambda: 101.0
    second = queue.admit(1, second_source, "preview", "second", {"root": ""})

    def execute(attempt, staging, report):
        assert attempt["id"] == first["id"]
        report(stage="validating", progress=10)
        assert ImportJobWorker(queue, tmp_path, lambda *args: {"added_count": 2}).run_once()
        assert queue.get(1, second["id"])["status"] == "succeeded"
        assert queue.get(1, first["id"])["progress"] == 10
        return {"added_count": 1}

    assert ImportJobWorker(queue, tmp_path, execute).run_once()
    assert queue.get(1, first["id"])["result"] == {"added_count": 1}
    assert queue.active_counts(1) == {"global": 0, "owner": 0}


def test_default_clock_and_rejected_output_are_fail_closed(imports):
    from app.services.dataset_import_jobs import ImportJobQueue

    queue, source = queue_fixture(imports)
    queued = queue.admit(1, source, "preview", "one", {"root": ""})
    recovered = ImportJobQueue(queue.sessions, limits=queue.limits)
    attempt = recovered.claim(lease_seconds=60)
    assert attempt["id"] == queued["id"] and attempt["lease_until"] > attempt["heartbeat_at"]
    recovered.heartbeat(attempt, lease_seconds=60)
    before = recovered.get(1, queued["id"])
    for operation in (lambda: recovered.finish(attempt, error="secret /private/path"),
                      lambda: recovered.finish(attempt, result={"path": "/private"}),
                      lambda: recovered.progress(attempt, stage="secret", progress=2)):
        with pytest.raises(ValueError):
            operation()
        assert recovered.get(1, queued["id"]) == before
