"""Explicit maintenance migration, no real database or implicit backfill."""
import pytest
from sqlalchemy import create_engine, inspect, text


def test_revision_migration_is_explicit_additive_and_replayable():
    from scripts.migrate_dataset_import_revisions import migrate_revisions
    from scripts.migrate_dataset_import_jobs import JobMigrationError
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO preserved VALUES ('synthetic original')"))
    with pytest.raises(JobMigrationError, match="stop_writers"):
        migrate_revisions(engine)
    assert inspect(engine).get_table_names() == ["preserved"]
    assert migrate_revisions(engine, writers_stopped=True) == {"version": 1, "verified": True}
    assert migrate_revisions(engine, writers_stopped=True) == {"version": 1, "verified": True}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM preserved")).scalars().all() == ["synthetic original"]
        assert conn.execute(text("SELECT COUNT(*) FROM imported_dataset_revision")).scalar_one() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM imported_dataset_revision_object")).scalar_one() == 0
    engine.dispose()


def test_incompatible_revision_schema_rolls_back_all_additions():
    from scripts.migrate_dataset_import_revisions import migrate_revisions
    from scripts.migrate_dataset_import_jobs import JobMigrationError
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE imported_dataset_revision_object (original TEXT)"))
        conn.execute(text("INSERT INTO imported_dataset_revision_object VALUES ('retained')"))
    with pytest.raises(JobMigrationError, match="incompatible_job_schema"):
        migrate_revisions(engine, writers_stopped=True)
    assert inspect(engine).get_table_names() == ["imported_dataset_revision_object"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT original FROM imported_dataset_revision_object")).scalar_one() == "retained"
    engine.dispose()


def test_revision_cli_requires_explicit_target_and_maintenance_before_database_access(monkeypatch):
    from scripts.migrate_dataset_import_revisions import main
    import sqlalchemy
    calls = []
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: calls.append(a))
    for args in ([], ["--writers-stopped"], ["--database-url", "sqlite://"]):
        with pytest.raises(SystemExit) as error:
            main(args)
        assert error.value.code == 2
    assert calls == []
