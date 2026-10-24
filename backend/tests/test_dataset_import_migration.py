"""Additive migration never rewrites legacy rows and is idempotent."""
from sqlalchemy import create_engine, inspect, text


def test_migration_creates_only_new_tables_and_preserves_existing_rows():
    from scripts.migrate_dataset_imports import create_import_tables
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE legacy_fixture (id INTEGER PRIMARY KEY, value TEXT)"))
        connection.execute(text("INSERT INTO legacy_fixture VALUES (1, 'unchanged')"))
        create_import_tables(connection)
        create_import_tables(connection)
        assert set(inspect(connection).get_table_names()) == {"legacy_fixture", "imported_dataset", "dataset_import"}
        assert connection.execute(text("SELECT * FROM legacy_fixture")).all() == [(1, "unchanged")]
    engine.dispose()
