"""The operator CLI executes one durable attempt, never starts an API or migrates."""
import json

import pytest

from tests.test_dataset_import_api import imports
from tests.test_dataset_import_async_api import uploaded


def command(imports, monkeypatch):
    from scripts import run_dataset_import_worker as cli
    client, service, _, sessions = imports
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *args, **kwargs: sessions.kw["bind"])
    # The CLI owns its real engine, but this fixture shares one in-memory DB
    # with HTTP. Retain it for post-command observations; fixture teardown owns it.
    monkeypatch.setattr(sessions.kw["bind"], "dispose", lambda: None)
    return cli.main, ["--database-url", "sqlite://", "--import-root", str(service.root),
                      "--staging-root", str(client.execution.root)]


def test_cli_processes_one_job_and_reports_claim_not_domain_success(imports, tmp_path, monkeypatch, capsys):
    main, args = command(imports, monkeypatch)
    client, _, _, _ = imports
    source = uploaded(client, tmp_path)
    job = client.post(f"/api/ingestion/imports/{source}/preview", json={"request_key": "cli", "root": ""}).json()
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"claimed": True}
    assert client.get(job["status_url"]).json()["status"] == "succeeded"
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"claimed": False}


def test_cli_help_and_missing_arguments_do_not_connect(monkeypatch, capsys):
    from scripts.run_dataset_import_worker import main
    def forbidden(*args, **kwargs):
        raise AssertionError("No database access during argument parsing")
    monkeypatch.setattr("sqlalchemy.create_engine", forbidden)
    with pytest.raises(SystemExit) as exit:
        main(["--help"])
    assert exit.value.code == 0
    assert "--staging-root" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exit:
        main([])
    assert exit.value.code == 2


def test_cli_invalid_root_preserves_queue_and_sanitizes_failure(imports, monkeypatch, capsys):
    main, args = command(imports, monkeypatch)
    args[-1] += "/private-missing"
    with pytest.raises(SystemExit) as exit:
        main(args)
    assert exit.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Import worker unavailable; preserve state and inspect the operation manual.\n"
    assert imports[0].execution.queue.active_counts(1) == {"global": 0, "owner": 0}


def test_cli_database_failure_never_echoes_url(monkeypatch, tmp_path, capsys):
    from scripts.run_dataset_import_worker import main
    def fail(*args, **kwargs):
        raise RuntimeError("postgresql://private:secret@internal/db")
    monkeypatch.setattr("sqlalchemy.create_engine", fail)
    with pytest.raises(SystemExit) as exit:
        main(["--database-url", "postgresql://private:secret@internal/db",
              "--import-root", str(tmp_path), "--staging-root", str(tmp_path)])
    assert exit.value.code == 1
    assert "secret" not in capsys.readouterr().err


def test_cli_does_not_repair_missing_migration(imports, monkeypatch):
    main, args = command(imports, monkeypatch)
    engine = imports[3].kw["bind"]
    with engine.begin() as db:
        db.exec_driver_sql("DELETE FROM dataset_import_job_gate")
    with engine.connect() as db:
        before = "\n".join(db.connection.driver_connection.iterdump())
    with pytest.raises(SystemExit) as exit:
        main(args)
    assert exit.value.code == 1
    with engine.connect() as db:
        assert "\n".join(db.connection.driver_connection.iterdump()) == before


@pytest.mark.parametrize("invalid", ["relative", "public", "symlink"])
def test_cli_root_rejection_preserves_database(imports, tmp_path, monkeypatch, capsys, invalid):
    main, args = command(imports, monkeypatch)
    uploaded(imports[0], tmp_path)
    engine = imports[3].kw["bind"]
    root = tmp_path / "candidate-root"
    root.mkdir(mode=0o700)
    if invalid == "relative":
        root = "relative"
    elif invalid == "public":
        root.chmod(0o755)
    else:
        link = tmp_path / "linked-root"
        link.symlink_to(root, target_is_directory=True)
        root = link
    def snapshot():
        with engine.connect() as db:
            return tuple(db.connection.driver_connection.iterdump())
    before = snapshot()
    args[-1] = str(root)
    with pytest.raises(SystemExit) as exit:
        main(args)
    assert exit.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Import worker unavailable; preserve state and inspect the operation manual.\n"
    assert snapshot() == before


def test_cli_claimed_does_not_mean_execution_succeeded(imports, tmp_path, monkeypatch, capsys):
    main, args = command(imports, monkeypatch)
    client, service, _, _ = imports
    source = uploaded(client, tmp_path)
    job = client.post(f"/api/ingestion/imports/{source}/preview", json={"request_key": "fault", "root": ""}).json()
    (service.root / "staging" / source / "archive.zip").write_bytes(b"corrupted synthetic archive")
    assert main(args) == 0
    assert capsys.readouterr().out == '{"claimed": true}\n'
    state = client.get(job["status_url"]).json()
    assert state["status"] == "failed"
    assert state["error"] == {"code": "execution_failed"}
