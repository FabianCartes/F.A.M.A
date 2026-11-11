"""Training bootstrap through the public CLI with an in-memory DBAPI adapter."""
import json
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


DATABASE = "fama_training_dev_20250102030405"
IDENTITY_QUERY = "FROM pg_database CROSS JOIN pg_control_system()"
ARGS = ["--database-url", f"postgresql://operator:synthetic@db:5432/{DATABASE}",
        "--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"]
REQUIRED = {"sesion_web", "cuota_acceso", "evento_seguridad", "triad_composition",
            "dataset_import_job", "dataset_import_receipt", "dataset_import_chunk"}


class IdentityCursor:
    """Emulate only PostgreSQL identity reads; schema operations use real SQLite."""
    def __init__(self, cursor):
        self.cursor = cursor
        self.identity = False

    def execute(self, statement, *args):
        self.identity = IDENTITY_QUERY in statement
        if not self.identity:
            self.cursor.execute(statement, *args)
        return self

    @property
    def description(self):
        if self.identity:
            return [(name, None, None, None, None, None, None)
                    for name in ("current_database", "oid", "system_identifier")]
        return self.cursor.description

    def fetchone(self):
        if self.identity:
            self.identity = False
            return DATABASE, 789, 123456
        return self.cursor.fetchone()

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class IdentityConnection:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")

    def cursor(self):
        return IdentityCursor(self.connection.cursor())

    def __getattr__(self, name):
        return getattr(self.connection, name)


@pytest.fixture
def cli(monkeypatch):
    from scripts.prepare_zip_manual_database import main
    engine = create_engine("sqlite://", creator=IdentityConnection, poolclass=StaticPool)
    # CLI owns/disposes its engine; retain the fixture connection between calls.
    connection = engine.raw_connection()
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    try:
        yield main, connection
    finally:
        connection.close()
        engine.pool.dispose()


def dump(connection):
    return tuple(connection.driver_connection.connection.iterdump())


def test_training_cli_initializes_complete_schema_and_checks_without_writes(cli, capsys):
    main, connection = cli
    assert main(ARGS + ["--initialize", "--writers-stopped"]) == 0
    result = json.loads(capsys.readouterr().out)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert REQUIRED <= tables
    assert result["stages"] == ["migrations"]
    before = dump(connection)
    assert main(ARGS + ["--check"]) == 0
    assert json.loads(capsys.readouterr().out)["verification"] == "training_schema_and_markers"
    assert dump(connection) == before
    with pytest.raises(SystemExit) as error:
        main(ARGS + ["--initialize", "--writers-stopped"])
    assert error.value.code == 1
    assert dump(connection) == before


@pytest.mark.parametrize("missing", sorted(REQUIRED))
def test_training_cli_check_rejects_missing_schema_without_repair(cli, capsys, missing):
    main, connection = cli
    assert main(ARGS + ["--initialize", "--writers-stopped"]) == 0
    capsys.readouterr()
    connection.execute(f'DROP TABLE "{missing}"')
    connection.commit()
    before = dump(connection)
    with pytest.raises(SystemExit) as error:
        main(ARGS + ["--check"])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert not output.out
    assert "preserve state" in output.err
    assert dump(connection) == before
