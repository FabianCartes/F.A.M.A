"""Fresh synthetic initialization is explicit; checking never repeats backfill."""
import pytest
from sqlalchemy import create_engine, inspect


def test_postgres_evaluation_spelling_uses_existing_strict_matcher(monkeypatch):
    from sqlalchemy.dialects import postgresql
    from scripts.prepare_zip_manual_database import _verify_application_table
    from scripts.migrate_model_evaluations import _POSTGRES_CATALOG_CHECKS
    from app.models.training import ModelEvaluation
    from scripts import migrate_dataset_import_jobs

    checks = [{"name": name, "sqltext": sql} for name, sql in _POSTGRES_CATALOG_CHECKS.items()]
    class Inspector:
        def get_check_constraints(self, name):
            assert name == "model_evaluation"
            return checks
    connection = type("Connection", (), {"dialect": postgresql.dialect()})()
    monkeypatch.setattr("sqlalchemy.inspect", lambda value: Inspector())
    tables = []
    monkeypatch.setattr(migrate_dataset_import_jobs, "_verify_table", lambda conn, table: tables.append(table))
    _verify_application_table(connection, ModelEvaluation.__table__)
    assert tables[0] is not ModelEvaluation.__table__
    assert not any(type(item).__name__ == "CheckConstraint" for item in tables[0].constraints)
    checks[0] = dict(checks[0], sqltext="status IS NOT NULL")
    with pytest.raises(ValueError):
        _verify_application_table(connection, ModelEvaluation.__table__)


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


def test_fresh_initialization_runs_ordered_existing_stages_and_checks_read_only(monkeypatch):
    from scripts.prepare_zip_manual_database import initialize, verify
    from scripts import migrate_dataset_import_metadata

    engine = create_engine("sqlite://")
    try:
        assert initialize(engine, writers_stopped=True) == {
            "prepared": True, "stages": ["application", "imports", "metadata", "jobs", "receipts", "chunks"]}
        with engine.connect() as connection:
            before = tuple(connection.connection.driver_connection.iterdump())
        def forbidden(*args, **kwargs):
            raise AssertionError("Verification must never repeat legacy backfill")
        monkeypatch.setattr(migrate_dataset_import_metadata, "migrate_metadata", forbidden)
        assert verify(engine) == {"prepared": True, "verification": "schema_and_markers"}
        with engine.connect() as connection:
            assert tuple(connection.connection.driver_connection.iterdump()) == before
        with pytest.raises(ValueError, match="nonempty"):
            initialize(engine, writers_stopped=True)
        with engine.connect() as connection:
            assert tuple(connection.connection.driver_connection.iterdump()) == before
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
