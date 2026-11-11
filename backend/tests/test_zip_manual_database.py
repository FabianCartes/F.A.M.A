"""Fresh synthetic initialization is explicit; checking never repeats backfill."""
import pytest
from sqlalchemy import create_engine, inspect


def test_internal_bridge_database_is_explicit_local_target(monkeypatch, capsys):
    from scripts.prepare_zip_manual_database import main
    calls = []
    def stop(url):
        calls.append(url)
        raise RuntimeError("No connection opened")
    monkeypatch.setattr("sqlalchemy.create_engine", stop)
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "postgresql+psycopg2://zip_manual:public@172.30.252.30:5432/fama_zip_manual", "--check"])
    assert error.value.code == 1
    assert len(calls) == 1


def test_fresh_initialization_applies_the_alembic_head_and_checks_read_only():
    from app.schema import HEAD
    from scripts.prepare_zip_manual_database import initialize, verify

    engine = create_engine("sqlite://")
    try:
        assert initialize(engine, writers_stopped=True) == {"prepared": True, "stages": ["migrations"]}
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalars().all() == [HEAD]
        assert "triad_composition" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            before = tuple(connection.connection.driver_connection.iterdump())
        assert verify(engine) == {"prepared": True, "verification": "schema_and_markers"}
        assert verify(engine, training_development=True) == {
            "prepared": True, "verification": "training_schema_and_markers"}
        with engine.connect() as connection:
            assert tuple(connection.connection.driver_connection.iterdump()) == before
        with pytest.raises(ValueError, match="nonempty"):
            initialize(engine, writers_stopped=True)
        with engine.connect() as connection:
            assert tuple(connection.connection.driver_connection.iterdump()) == before
    finally:
        engine.dispose()


def test_check_rejects_a_schema_that_is_not_the_current_revision():
    from scripts.prepare_zip_manual_database import verify
    from tests.schema_support import migrated_engine

    engine = migrated_engine("0004_integration")
    try:
        with pytest.raises(ValueError, match="current"):
            verify(engine)
    finally:
        engine.dispose()


def test_missing_writer_acknowledgement_preserves_empty_database():
    from scripts.prepare_zip_manual_database import initialize

    engine = create_engine("sqlite://")
    try:
        with pytest.raises(ValueError, match="writers"):
            initialize(engine)
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("flag", ["--check", "--initialize", "--writers-stopped"])
def test_boolean_option_value_never_appears_in_parser_output(monkeypatch, capsys, flag):
    import sys
    from scripts.prepare_zip_manual_database import main

    monkeypatch.setattr(sys, "argv", ["zip-cli"])
    monkeypatch.setenv("COLUMNS", "80")
    secret = "synthetic-parser-secret"
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "postgresql://fictional:fake@db:5432/fama_zip_manual",
              f"{flag}={secret}"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "usage: zip-cli [-h] --database-url DATABASE_URL (--initialize | --check)\n"
        "               [--writers-stopped]\n"
        "zip-cli: error: boolean options do not accept values\n"
    )
    assert secret not in output.err


@pytest.mark.parametrize(
    "host,database,extra,actual,expected_status",
    [
        ("172.30.253.30", "fama_training_dev_20250102030405", [], None, 2),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development"], None, 2),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456"], None, 2),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "not-decimal", "--expected-database-oid", "789"], None, 2),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "0", "--expected-database-oid", "789"], None, 2),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "0789"], None, 2),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "0"], None, 2),
        ("172.30.253.30", "fama_training_dev_20250102030405?dbname=fama_zip_manual", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], None, 2),
        ("remote.invalid", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], None, 2),
        ("172.30.253.30", "fama_training_dev_2025010203040", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], None, 2),
        ("172.30.253.30", "fama_zip_manual", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], None, 2),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], ("fama_training_dev_20250102030405", 789, 123456), 0),
        ("db", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], ("fama_training_dev_20250102030405", 789, 123456), 0),
        ("172.30.252.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], ("fama_training_dev_20250102030405", 789, 123456), 0),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], ("fama_training_dev_20250102030405", 790, 123456), 1),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], ("fama_training_dev_20250102030405", 789, 123457), 1),
        ("172.30.253.30", "fama_training_dev_20250102030405", ["--training-development", "--expected-system-id", "123456", "--expected-database-oid", "789"], ("fama_training_dev_20250102030406", 789, 123456), 1),
    ],
)
def test_training_development_target_requires_matching_connected_identity(
    monkeypatch, capsys, host, database, extra, actual, expected_status
):
    from scripts import prepare_zip_manual_database as prepare

    calls = []

    class Result:
        def __init__(self, values):
            self.values = values

        def scalar(self):
            return self.values[0]

        scalar_one = scalar
        scalar_one_or_none = scalar

        def one(self):
            return self.values

        first = one
        fetchone = one
        one_or_none = one

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, *args, **kwargs):
            sql = str(statement).lower()
            assert sql.lstrip().startswith("select"), "Identity preflight must be read-only"
            calls.append(sql)
            # Only return facts requested by the statement, in SELECT-list order.
            projection = sql.split(" from ", 1)[0]
            fields = []
            for expression in projection.removeprefix("select ").split(","):
                if "system_identifier" in expression:
                    fields.append(actual[2])
                elif "oid" in expression:
                    fields.append(actual[1])
                elif "current_database" in expression or "datname" in expression:
                    fields.append(actual[0])
                else:
                    raise AssertionError(f"Unexpected identity query: {sql}")
            return Result(tuple(fields))

    class Cursor:
        def execute(self, statement):
            calls.append(statement.lower())

        def fetchone(self):
            return actual

        def close(self):
            pass

    class Engine:
        def cursor(self):
            return Cursor()

        def connect(self):
            self.checkout(self, None, None)
            return Connection()

        def dispose(self):
            pass

    def listen(engine, name, callback):
        assert name == "checkout"
        engine.checkout = callback

    monkeypatch.setattr("sqlalchemy.event.listen", listen)

    def create_engine(url):
        assert actual is not None, "Rejected URL must not open a connection"
        return Engine()

    def initialize(engine, *, writers_stopped, training_development=False):
        assert writers_stopped is True
        assert training_development is ("--training-development" in extra)
        calls.append("initialize")
        return {"prepared": True}

    monkeypatch.setattr("sqlalchemy.create_engine", create_engine)
    monkeypatch.setattr(prepare, "initialize", initialize)
    url = f"postgresql://fictional:fake-secret@{host}:5432/{database}"
    args = ["--database-url", url, "--initialize", "--writers-stopped", *extra]
    if expected_status:
        with pytest.raises(SystemExit) as error:
            prepare.main(args)
        assert error.value.code == expected_status
    else:
        assert prepare.main(args) == 0
    output = capsys.readouterr()
    assert "fake-secret" not in output.err + output.out
    assert ("initialize" in calls) is (expected_status == 0)
    if actual is not None:
        queries = " ".join(call for call in calls if call != "initialize")
        assert "system_identifier" in queries
        assert "oid" in queries
        assert "current_database" in queries or "datname" in queries


def test_training_development_rejects_identity_change_before_ddl(monkeypatch):
    from sqlalchemy import create_mock_engine
    from scripts.prepare_zip_manual_database import main

    expected = ("fama_training_dev_20250102030405", 789, 123456)
    old_identity = ("fama_training_dev_20250102030405", 790, 123456)
    old_target = ["existing old database content"]
    before = tuple(old_target)
    identity_queries = []
    ddl = []
    checkouts = []

    class Result:
        def __init__(self, value):
            self.value = value

        def one(self):
            return self.value

        def scalar_one(self):
            return self.value

    class Connection:
        def __init__(self, identity):
            self.identity = identity

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, *args, **kwargs):
            sql = str(statement).lower()
            if "system_identifier" in sql and "oid" in sql:
                identity_queries.append(self.identity)
                return Result(self.identity)
            if "select exists" in sql:
                return Result(False)
            raise AssertionError(f"Unexpected query: {sql}")

    def execute_ddl(statement, *args, **kwargs):
        # SQLAlchemy's mock PostgreSQL engine compiles actual emitted DDL;
        # model its effect on the subsequently connected, synthetic old target.
        ddl.append(str(statement.compile(dialect=mock_engine.dialect)))
        old_target.append("DDL executed")
        raise RuntimeError("Synthetic old target must not receive DDL")

    mock_engine = create_mock_engine("postgresql://", execute_ddl)

    class Cursor:
        def __init__(self, identity):
            self.identity = identity

        def execute(self, statement):
            assert "system_identifier" in statement.lower()

        def fetchone(self):
            identity_queries.append(self.identity)
            return self.identity

        def close(self):
            pass

    class Engine:
        dialect = mock_engine.dialect

        def begin(self):
            return self.connect()

        def connect(self):
            identity = expected if not checkouts else old_identity
            checkouts.append(identity)
            dbapi_connection = type("DBAPIConnection", (), {
                "cursor": lambda self: Cursor(identity),
            })()
            self.checkout(dbapi_connection, None, None)
            return Connection(identity)

        def _run_ddl_visitor(self, *args, **kwargs):
            # The synthetic target reports an empty schema; mock connections
            # cannot perform PostgreSQL catalog inspection for checkfirst.
            kwargs["checkfirst"] = False
            return mock_engine._run_ddl_visitor(*args, **kwargs)

        def dispose(self):
            pass

    def listen(engine, name, callback):
        assert name == "checkout"
        engine.checkout = callback

    monkeypatch.setattr("sqlalchemy.event.listen", listen)
    monkeypatch.setattr("sqlalchemy.create_engine", lambda url: Engine())
    with pytest.raises(SystemExit) as error:
        main([
            "--database-url", "postgresql://fictional:fake@db:5432/" + expected[0],
            "--initialize", "--writers-stopped", "--training-development",
            "--expected-system-id", "123456", "--expected-database-oid", "789",
        ])
    assert error.value.code == 1
    assert identity_queries and identity_queries[0] == expected
    assert old_identity in checkouts
    assert ddl == []
    assert tuple(old_target) == before


@pytest.mark.parametrize("url,action,message", [
    ("postgresql://fictional:fake-secret@remote.invalid:5432/fama_zip_manual", ["--check"],
     "Target must be the dedicated local fama_zip_manual PostgreSQL database"),
    ("postgresql://fictional:fake-secret@db:5432/fama_zip_manual", ["--initialize"],
     "--initialize requires --writers-stopped; --check does not accept it"),
    ("postgresql://fictional:fake-secret@db:5432/fama_zip_manual", ["--check", "--writers-stopped"],
     "--initialize requires --writers-stopped; --check does not accept it"),
])
def test_legacy_cli_preserves_exact_rejection_output(monkeypatch, capsys, url, action, message):
    import sys
    from scripts.prepare_zip_manual_database import main

    monkeypatch.setattr(sys, "argv", ["zip-cli"])
    monkeypatch.setenv("COLUMNS", "80")
    with pytest.raises(SystemExit) as error:
        main(["--database-url", url, *action])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "usage: zip-cli [-h] --database-url DATABASE_URL (--initialize | --check)\n"
        "               [--writers-stopped]\n"
        f"zip-cli: error: {message}\n"
    )
    assert "fake-secret" not in output.err


def test_legacy_cli_rejects_identity_flags_without_opt_in(monkeypatch, capsys):
    import sys
    from scripts.prepare_zip_manual_database import main

    monkeypatch.setattr(sys, "argv", ["zip-cli"])
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "postgresql://fictional:fake-secret@db:5432/fama_zip_manual",
              "--check", "--expected-system-id", "123456"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "unrecognized arguments" in output.err
    assert "fake-secret" not in output.err + output.out


@pytest.mark.parametrize("url", [
    "postgresql://secret:do-not-print@127.0.0.1:55432/fama_db",
    "postgresql://secret:do-not-print@remote.invalid/fama_zip_manual",
    "sqlite:///real-database.db",
])
def test_operator_cli_rejects_other_targets_before_connecting(monkeypatch, capsys, url):
    from scripts.prepare_zip_manual_database import main

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid target must not connect")
    monkeypatch.setattr("sqlalchemy.create_engine", forbidden)
    with pytest.raises(SystemExit) as error:
        main(["--database-url", url, "--check"])
    assert error.value.code == 2
    assert "do-not-print" not in capsys.readouterr().err
