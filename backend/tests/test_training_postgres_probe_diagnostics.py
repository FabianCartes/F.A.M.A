"""Public probe CLI diagnostics; no Docker, database, or network access."""
import json
import sys
from types import ModuleType

import pytest


def test_main_reports_sanitized_structured_failure(monkeypatch, capsys):
    from scripts import training_postgres_probe as probe

    database = "fama_training_dev_20260401123456"
    private_message = (
        "fake-secret password=synthetic-password "
        "postgresql://probe:synthetic-password@private.example.test/private_db"
    )
    calls = []

    def failed_proof(target):
        calls.append(target)
        raise RuntimeError(private_message)

    # Isolate CLI error rendering from the owned-cluster proof. This does not
    # simulate PostgreSQL denial or change which SQLSTATEs count as rejection.
    monkeypatch.setattr(probe, "prove", failed_proof)

    assert probe.main(["--database", database]) == 1
    assert calls == [database]
    output = capsys.readouterr()
    assert output.out == ""
    for private_value in (
        "fake-secret", "password", "synthetic-password", "postgresql://",
        "private.example.test", "private_db",
    ):
        assert private_value not in output.err

    # Unknown/unclassified failures still need safe, machine-readable context;
    # arbitrary exception messages and class names must not become diagnostics.
    assert output.err.lstrip().startswith("{"), "missing structured failure diagnostic"
    assert json.loads(output.err) == {
        "phase": "unknown",
        "category": "unexpected_error",
        "sqlstate_present": False,
    }


def test_main_success_output_is_unchanged(monkeypatch, capsys):
    from scripts import training_postgres_probe as probe

    result = {"database": "fama_training_dev_20260401123456", "quarantined": True}
    calls = []

    def successful_proof(database):
        calls.append(database)
        return result

    monkeypatch.setattr(probe, "prove", successful_proof)
    assert probe.main(["--database", result["database"]]) == 0
    assert calls == [result["database"]]
    output = capsys.readouterr()
    assert output.out == '{"database": "fama_training_dev_20260401123456", "quarantined": true}\n'
    assert output.err == ""


@pytest.mark.parametrize("cleanup_fails", [False, True], ids=["denial", "cleanup"])
def test_main_reports_permission_rejection_failure_from_prove(monkeypatch, capsys, cleanup_fails):
    import sqlalchemy
    from sqlalchemy.exc import OperationalError
    from scripts import training_postgres_probe as probe

    database = "fama_training_dev_20260401123456"
    private_message = (
        "fake-secret password=synthetic-password "
        "postgresql://probe:synthetic-password@private.example.test/private_db"
    )

    class DriverFailure(Exception):
        pgcode = None

    failure = OperationalError("private SQL " + private_message, {}, DriverFailure(private_message))
    statements = []
    bootstrap_calls = []
    denied_attempts = []
    disposed = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement, parameters=None):
            statements.append(str(statement))
            # This fixture provides no permission catalog evidence. The newly
            # required catalog read fails without SQLSTATE too; fail closed
            # before trying writer credentials, not by accepting error text.
            if "FROM pg_roles" in str(statement):
                raise failure
            if cleanup_fails and str(statement) == f'ALTER DATABASE "{database}" ALLOW_CONNECTIONS false':
                raise RuntimeError(private_message)
            return self

        def one(self):
            return database, 789, 123456

    class Engine:
        def __init__(self, kind):
            self.kind = kind

        def connect(self):
            if self.kind == "denied":
                denied_attempts.append(True)
                raise failure
            return Connection()

        def dispose(self):
            disposed.append(self.kind)

    engines = []

    def create_engine(url, **kwargs):
        if url.username == "fama_probe_writer":
            kind = "denied"
        elif url.database == "postgres":
            kind = "admin"
        else:
            kind = "target"
        engines.append(kind)
        return Engine(kind)

    # Replace only external boundaries: run the real prove(), without loading
    # the application bootstrap or creating a SQLAlchemy/DBAPI connection.
    bootstrap = ModuleType("scripts.prepare_zip_manual_database")

    def initialize(args):
        bootstrap_calls.append(args)
        raise AssertionError("Initialization must not follow an unclassified denial")

    bootstrap.main = initialize
    monkeypatch.setitem(sys.modules, bootstrap.__name__, bootstrap)
    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine)

    assert probe.main(["--database", database]) == 1
    # Establish the intended failure path before asking for new diagnostics.
    assert engines == ["admin", "target"]
    assert denied_attempts == []
    assert bootstrap_calls == []
    assert disposed == (["target"] if cleanup_fails else ["target", "admin"])
    assert statements[-1] == f'ALTER DATABASE "{database}" ALLOW_CONNECTIONS false'
    output = capsys.readouterr()
    assert output.out == ""
    for private_value in (
        "fake-secret", "password", "synthetic-password", "postgresql://",
        "private.example.test", "private_db", "DriverFailure", "private SQL",
    ):
        assert private_value not in output.err
    assert output.err.lstrip().startswith("{"), "missing structured failure diagnostic"
    assert json.loads(output.err) == {
        "phase": "cleanup" if cleanup_fails else "permission_rejection",
        "category": "unexpected_error" if cleanup_fails else "operational_error",
        "sqlstate_present": False,
    }
