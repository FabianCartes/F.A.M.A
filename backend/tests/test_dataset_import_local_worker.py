"""Local-only worker public interfaces, synthetic memory database, no HTTPX."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def queue_store():
    from scripts.migrate_dataset_imports import create_import_tables
    from scripts.migrate_dataset_import_jobs import migrate_jobs

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    create_import_tables(engine)
    migrate_jobs(engine, writers_stopped=True)
    yield engine, sessionmaker(bind=engine)
    engine.dispose()


def seed(sessions, kind, number, *, expired=False):
    from app.models.dataset_import import DatasetImport
    from app.models.dataset_import_job import ImportJob

    identity = f"{number:032x}"
    with sessions.begin() as db:
        db.add(DatasetImport(id=identity, owner_id=number, request_key=identity,
                             request={}, status="validating", created_at=number))
        db.flush()
        db.add(ImportJob(id=identity, owner_id=number, import_id=identity, kind=kind,
                         request_key="synthetic", parameters={}, parameters_sha256="0" * 64,
                         status="running" if expired else "queued", stage="queued", progress=0,
                         result={}, attempt=1 if expired else 0, token=1 if expired else 0,
                         lease_until=99 if expired else None,
                         heartbeat_at=90 if expired else None,
                         created_at=number, updated_at=number))
    return identity


@pytest.mark.parametrize("expired", [False, True])
def test_default_claim_skips_retired_jobs_without_mutating_them(queue_store, expired):
    from app.services.dataset_import_jobs import ImportJobQueue

    _, sessions = queue_store
    cloud = seed(sessions, "sync", 1, expired=expired)
    preview = seed(sessions, "preview", 2)
    confirm = seed(sessions, "confirm", 3)
    queue = ImportJobQueue(sessions, clock=lambda: 100)
    before = queue.get(1, cloud)
    assert queue.claim(lease_seconds=60)["id"] == preview
    assert queue.claim(lease_seconds=60)["id"] == confirm
    assert queue.claim(lease_seconds=60) is None
    assert queue.get(1, cloud) == before


def test_default_queue_reclaims_local_work_and_preserves_fencing(queue_store):
    from app.services.dataset_import_jobs import ImportJobQueue

    _, sessions = queue_store
    identity = seed(sessions, "preview", 1, expired=True)
    queue = ImportJobQueue(sessions, clock=lambda: 100)
    attempt = queue.claim(lease_seconds=60)
    assert attempt["id"] == identity
    assert attempt["attempt"] == 2 and attempt["token"] == 2
    assert attempt["lease_until"] == 160


@pytest.mark.parametrize("invalid", [(), ("unknown",), ("sync",), "preview"])
def test_invalid_claim_filter_is_rejected_before_database_access(invalid):
    from app.services.dataset_import_jobs import ImportJobQueue

    def forbidden():
        raise AssertionError("Invalid configuration must not open the database")
    with pytest.raises(ValueError):
        ImportJobQueue(forbidden, allowed_kinds=invalid)


def cli_fixture(queue_store, tmp_path, monkeypatch):
    from scripts import run_dataset_import_worker as cli
    from app.services import dataset_import_execution

    engine, _ = queue_store
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    root, staging = tmp_path / "imports", tmp_path / "attempts"
    root.mkdir(mode=0o700)
    staging.mkdir(mode=0o700)
    calls = []
    class Execution:
        def __init__(self, queue, service, path):
            assert queue.allowed_kinds is None
        def run_once(self):
            calls.append("attempt")
            return False
    monkeypatch.setattr(dataset_import_execution, "ImportExecution", Execution)
    args = ["--database-url", "sqlite://", "--import-root", str(root),
            "--staging-root", str(staging)]
    return cli, args, calls


@pytest.mark.parametrize("options", [[], ["--local-only"]])
def test_cli_one_attempt_keeps_existing_output_and_local_storage_contract(
        queue_store, tmp_path, monkeypatch, capsys, options):
    cli, args, calls = cli_fixture(queue_store, tmp_path, monkeypatch)
    assert cli.main(args + options) == 0
    assert calls == ["attempt"]
    assert json.loads(capsys.readouterr().out) == {"claimed": False}


def test_watch_waits_and_restores_signal_handlers(queue_store, tmp_path, monkeypatch, capsys):
    import signal
    import threading

    cli, args, calls = cli_fixture(queue_store, tmp_path, monkeypatch)
    handlers = []
    monkeypatch.setattr(signal, "signal", lambda number, handler: handlers.append((number, handler)) or "old")
    class Stop:
        def set(self):
            pass
        def wait(self, seconds):
            calls.append(("wait", seconds))
            return True
    monkeypatch.setattr(threading, "Event", Stop)
    assert cli.main(args + ["--watch", "--poll-seconds", "3"]) == 0
    assert calls == ["attempt", ("wait", 3)]
    assert json.loads(capsys.readouterr().out) == {"claimed": False}
    assert handlers[-2:] == [(signal.SIGINT, "old"), (signal.SIGTERM, "old")]


@pytest.mark.parametrize("options", [
    ["--sync-only"], ["--poll-seconds", "2"],
    ["--watch", "--poll-seconds", "nan"],
    ["--watch", "--poll-seconds", "0"],
    ["--watch", "--poll-seconds", "3601"],
    ["--watch", "--poll-seconds", "inf"],
])
def test_invalid_watch_configuration_never_opens_database(monkeypatch, options):
    from scripts.run_dataset_import_worker import main

    def forbidden(*args, **kwargs):
        raise AssertionError("Argument rejection must precede database access")
    monkeypatch.setattr("sqlalchemy.create_engine", forbidden)
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "sqlite://", "--import-root", "/unused",
              "--staging-root", "/unused", *options])
    assert error.value.code == 2
