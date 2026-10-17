"""Explicit additive export schema against synthetic memory-only databases."""
import pytest
from sqlalchemy import create_engine, inspect


def test_export_migration_requires_maintenance_and_is_idempotent():
    from scripts.migrate_dataset_exports import migrate_exports
    from scripts.migrate_dataset_import_jobs import JobMigrationError
    from app.database import Base
    from app.models.dataset_import import ImportedDataset
    engine = create_engine("sqlite://")
    try:
        ImportedDataset.__table__.create(engine)
        with pytest.raises(JobMigrationError, match="stop_writers"):
            migrate_exports(engine)
        assert not inspect(engine).has_table("dataset_export")
        first = migrate_exports(engine, writers_stopped=True)
        assert first == {"version": 1, "verified": True}
        assert migrate_exports(engine, writers_stopped=True) == first
        assert set(inspect(engine).get_table_names()) == {"imported_dataset", "dataset_export", "dataset_export_session"}
    finally:
        engine.dispose()


def test_export_migration_rejects_incompatible_schema_without_replacing_it():
    from scripts.migrate_dataset_exports import migrate_exports
    from scripts.migrate_dataset_import_jobs import JobMigrationError
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE imported_dataset (id VARCHAR(32) PRIMARY KEY)")
            connection.exec_driver_sql("CREATE TABLE dataset_export (id VARCHAR(32) PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO dataset_export VALUES ('preserve')")
        with pytest.raises(JobMigrationError):
            migrate_exports(engine, writers_stopped=True)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT * FROM dataset_export").all() == [("preserve",)]
        assert not inspect(engine).has_table("dataset_export_session")
    finally:
        engine.dispose()


@pytest.mark.parametrize("module_name,options", [
    ("scripts.migrate_dataset_exports", ["--database-url", "--writers-stopped"]),
    ("scripts.run_dataset_export_worker", ["--database-url", "--import-root", "--export-root", "--cleanup-only"]),
])
def test_export_clis_require_explicit_inputs_before_database_access(module_name, options, monkeypatch, capsys):
    import importlib
    import sqlalchemy
    module = importlib.import_module(module_name)
    def forbidden(*args, **kwargs):
        raise AssertionError("No database access is authorized by help or missing inputs")
    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    with pytest.raises(SystemExit) as missing:
        module.main([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as help_result:
        module.main(["--help"])
    assert help_result.value.code == 0
    output = capsys.readouterr().out
    assert all(option in output for option in options)
