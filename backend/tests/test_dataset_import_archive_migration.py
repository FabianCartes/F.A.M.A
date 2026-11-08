"""Additive migration exercised on a synthetic legacy schema only."""
import pytest
from sqlalchemy import create_engine, text
from scripts.migrate_dataset_import_archive import migrate_archive, validate_archive


def test_archive_migration_preserves_existing_rows_and_is_idempotent():
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE imported_dataset (id VARCHAR(32) PRIMARY KEY, revision INTEGER NOT NULL)'))
            connection.execute(text("INSERT INTO imported_dataset VALUES ('existing', 7)"))
        with pytest.raises(RuntimeError, match='writers'):
            migrate_archive(engine)
        migrate_archive(engine, writers_stopped=True)
        migrate_archive(engine, writers_stopped=True)
        with engine.connect() as connection:
            validate_archive(connection)
            assert connection.execute(text('SELECT id, revision, archived FROM imported_dataset')).one() == ('existing', 7, 0)
    finally:
        engine.dispose()


def test_archive_migration_refuses_incompatible_existing_column():
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE imported_dataset (id TEXT, archived TEXT)'))
        with pytest.raises(RuntimeError, match='Incompatible'):
            migrate_archive(engine, writers_stopped=True)
    finally:
        engine.dispose()
