"""Frozen Alembic HEAD against the runtime ORM, on in-memory SQLite only.

PostgreSQL-specific behaviour (types, GRANT, advisory locks) is covered by
test_schema_migrations.py when FAMA_TEST_POSTGRES_URL is provided.
"""
import importlib
import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from tests.schema_support import BACKEND, downgrade, upgrade
# Retired from the code in stage b but kept in the database (decision 11).
RETAINED_TABLES = {"dataset_export", "dataset_export_session",
                   "imported_dataset_revision", "imported_dataset_revision_object"}


def runtime_metadata():
    from app.database import Base
    for module in (BACKEND / "app" / "models").glob("*.py"):
        if module.stem != "__init__":
            importlib.import_module("app.models." + module.stem)
    return Base.metadata


def rows(connection):
    names = sorted(inspect(connection).get_table_names())
    return {name: sorted(map(tuple, connection.execute(text(f'SELECT * FROM "{name}"'))), key=repr)
            for name in names if name != "alembic_version"}


@pytest.fixture
def connection():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def test_head_is_the_frozen_runtime_schema_plus_retained_tables():
    from app.schema import HEAD, REVISIONS
    from migrations.schema_0004 import metadata as previous
    head = importlib.import_module("migrations.schema_" + HEAD.split("_", 1)[0]).metadata
    runtime = runtime_metadata()
    assert HEAD == REVISIONS[-1] == "0005_triad_composition"
    assert set(head.tables) == set(runtime.tables) | RETAINED_TABLES
    assert set(head.tables) >= set(previous.tables)


def test_migrated_head_matches_every_runtime_model(connection):
    from app.schema import _inspect_schema, matches_schema
    from migrations.schema_0004 import metadata as previous
    upgrade(connection, "head")
    expected = MetaData()
    for table in runtime_metadata().sorted_tables:
        table.to_metadata(expected)
    for name in sorted(RETAINED_TABLES):
        previous.tables[name].to_metadata(expected)
    assert matches_schema(connection, expected)
    from app.schema import HEAD
    assert _inspect_schema(connection).code == "schema_current"
    assert _inspect_schema(connection).revision == HEAD


def test_upgrade_from_0004_is_additive_and_preserves_rows(connection):
    from app.schema import HEAD, _inspect_schema
    upgrade(connection, "0004_integration")
    connection.execute(text(
        "INSERT INTO usuario (correo_electronico, hash_contrasena, rol, nombre_completo, activo, fecha_creacion)"
        " VALUES ('owner@example.test', 'x', 'administrador', 'Owner', 1, '2026-01-01 00:00:00')"))
    owner = connection.execute(text("SELECT id_usuario FROM usuario")).scalar_one()
    connection.execute(text(
        "INSERT INTO imported_dataset (id, owner_id, name, description, revision, files)"
        " VALUES ('d' || hex(randomblob(15)), :owner, 'Birds', 'Synthetic', 3, '[]')"), {"owner": owner})
    before = rows(connection)
    tables = set(before)
    upgrade(connection, "head")
    after = rows(connection)
    assert {name: after[name] for name in before} == before
    assert tables < set(after)
    assert _inspect_schema(connection).code == "schema_current"
    assert _inspect_schema(connection).revision == HEAD


def test_downgrade_from_head_fails_explicitly_without_changing_the_schema(connection):
    from app.schema import HEAD
    upgrade(connection, "head")
    before = rows(connection)
    with pytest.raises(RuntimeError, match="recuperación explícita del operador"):
        downgrade(connection, "0004_integration")
    assert rows(connection) == before
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
