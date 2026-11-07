"""Public CLI/queue contract for the dedicated sync consumer; no cloud network."""
import json

import pytest

from tests.test_dataset_import_local_worker import queue_store, seed


@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("watch", [False, True])
def test_sync_cli_claims_only_sync_and_preserves_local_jobs(
        queue_store, tmp_path, monkeypatch, capsys, expired, watch):
    from scripts import run_dataset_import_worker as cli
    from app.services import dataset_import_execution
    from app.services.dataset_import_jobs import ImportJobQueue

    engine, sessions = queue_store
    local_ids = [seed(sessions, "preview", 1, expired=expired),
                 seed(sessions, "confirm", 2, expired=expired)]
    sync_id = seed(sessions, "sync", 3)
    public = ImportJobQueue(sessions)
    before = [public.get(i, job) for i, job in enumerate(local_ids, 1)]
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    claimed = []
    class Execution:
        def __init__(self, queue, service, path, *, storage):
            self.queue = queue
            assert storage is not None
        def run_once(self):
            attempt = self.queue.claim(lease_seconds=60)
            claimed.append(attempt["id"] if attempt else None)
            return attempt is not None
    monkeypatch.setattr(dataset_import_execution, "ImportExecution", Execution)
    root, staging = tmp_path / "imports", tmp_path / "attempts"
    root.mkdir(mode=0o700); staging.mkdir(mode=0o700)
    options = []
    if watch:
        import signal
        waits, handlers = [], []
        class Stop:
            def set(self): pass
            def wait(self, seconds):
                waits.append(seconds)
                return True
        monkeypatch.setattr(cli.threading, "Event", Stop)
        monkeypatch.setattr(signal, "signal", lambda number, handler: handlers.append((number, handler)) or "old")
        options = ["--watch", "--poll-seconds", "3"]
    assert cli.main(["--database-url", "sqlite://", "--import-root", str(root),
                     "--staging-root", str(staging), "--sync-only", *options]) == 0
    output = capsys.readouterr()
    assert output.out == '{"claimed": true}\n' and output.err == ""
    assert claimed == [sync_id]
    assert [public.get(i, job) for i, job in enumerate(local_ids, 1)] == before
    assert public.get(3, sync_id)["status"] == "running"
    if watch:
        assert waits == [3]
        assert handlers[-2:] == [(signal.SIGINT, "old"), (signal.SIGTERM, "old")]


@pytest.mark.parametrize("options,message", [
    (["--sync-only", "--local-only"], "argument --local-only: not allowed with argument --sync-only"),
    (["--sync-only", "--cleanup-only"], "argument --cleanup-only: not allowed with argument --sync-only"),
    (["--sync-only", "--watch", "--poll-seconds", "nan"], "--poll-seconds requires --watch and a finite value between 1 and 3600"),
    (["--sync-only", "--watch", "--poll-seconds", "0"], "--poll-seconds requires --watch and a finite value between 1 and 3600"),
    (["--sync-only", "--watch", "--poll-seconds", "3601"], "--poll-seconds requires --watch and a finite value between 1 and 3600"),
])
def test_invalid_sync_options_reject_before_connection_and_preserve_queue(
        queue_store, monkeypatch, capsys, options, message):
    import sys
    from scripts.run_dataset_import_worker import main
    from app.services.dataset_import_jobs import ImportJobQueue
    _, sessions = queue_store
    identity = seed(sessions, "sync", 1)
    queue = ImportJobQueue(sessions)
    before = queue.get(1, identity)
    counts = queue.active_counts(1)
    connections = []
    def forbidden(*a, **kw):
        connections.append(True)
        raise AssertionError("Rejected options must not connect")
    monkeypatch.setattr("sqlalchemy.create_engine", forbidden)
    monkeypatch.setattr(sys, "argv", ["import-worker"])
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "sqlite://", "--import-root", "/unused",
              "--staging-root", "/unused", *options])
    output = capsys.readouterr()
    assert error.value.code == 2 and output.out == ""
    assert output.err.startswith("usage: import-worker ")
    assert output.err.endswith("import-worker: error: " + message + "\n")
    assert connections == []
    assert queue.get(1, identity) == before
    assert queue.active_counts(1) == counts
