"""Estado del esquema y operaciones explícitas de migración del operador."""
import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from sqlalchemy import CheckConstraint, MetaData, inspect, text

from app.database_connection import database_engine


@dataclass(frozen=True)
class SchemaStatus:
    code: str
    revision: str | None = None


HEAD = "0003_autonomy"
REVISIONS = ("0001_core", "0002_access", HEAD)


def _check_expression(expression: str) -> str:
    # PostgreSQL refleja IN como = ANY (ARRAY[...]) y añade casts de tipos.
    parts = re.split(r"('(?:[^']|'')*')", expression)
    for index in range(0, len(parts), 2):
        normalized = re.sub(r"::(?:character varying|text|bigint|integer)(?:\[\])?", "", parts[index].lower())
        normalized = re.sub(r"=\s*any\s*\(\s*array\[", " in (", normalized)
        parts[index] = re.sub(r"[\s\[\]()]", "", normalized)
    return "".join(parts)


def _matches_revision(connection, revision: str) -> bool:
    from migrations.schema_0002 import metadata, CORE_TABLES

    expected = metadata
    if revision == HEAD:
        from migrations.schema_0003 import metadata as expected
    if revision == "0001_core":
        expected = MetaData()
        for name in CORE_TABLES:
            metadata.tables[name].to_metadata(expected)
    return matches_schema(connection, expected)


def matches_schema(connection, expected: MetaData) -> bool:
    """Compare a selected frozen schema, including keys and check constraints."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    inspector = inspect(connection)
    if inspector.get_view_names() or inspector.get_materialized_view_names():
        return False
    context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
    if compare_metadata(context, expected):
        return False
    for name, table in expected.tables.items():
        if inspector.get_pk_constraint(name)["constrained_columns"] != [c.name for c in table.primary_key]:
            return False
        actual_checks = {c["name"]: _check_expression(c["sqltext"]) for c in inspector.get_check_constraints(name)}
        expected_checks = {c.name: _check_expression(str(c.sqltext)) for c in table.constraints if isinstance(c, CheckConstraint)}
        if actual_checks != expected_checks:
            return False
    return True


def _inspect_schema(connection) -> SchemaStatus:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if inspector.get_view_names() or (connection.dialect.name == "postgresql" and inspector.get_materialized_view_names()):
        return SchemaStatus("schema_incompatible")
    if not tables:
        return SchemaStatus("schema_empty")
    if "alembic_version" not in tables:
        return SchemaStatus("schema_incompatible")
    revisions = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if len(revisions) != 1 or revisions[0] not in REVISIONS:
        return SchemaStatus("schema_incompatible")
    revision = revisions[0]
    if not _matches_revision(connection, revision):
        return SchemaStatus("schema_incompatible", revision)
    return SchemaStatus("schema_current" if revision == HEAD else "schema_outdated", revision)


def check_schema(database_url: str) -> SchemaStatus:
    engine = None
    try:
        engine = database_engine(database_url)
        if engine.dialect.name != "postgresql":
            return SchemaStatus("database_unsupported")
        with engine.connect() as connection:
            return _inspect_schema(connection)
    except Exception:
        return SchemaStatus("database_unavailable")
    finally:
        if engine is not None:
            engine.dispose()


def upgrade_schema(database_url: str, revision: str = "head") -> SchemaStatus:
    from alembic import command
    from alembic.config import Config

    engine = None
    try:
        engine = database_engine(database_url)
        if engine.dialect.name != "postgresql":
            return SchemaStatus("database_unsupported")
        with engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                if not connection.scalar(text("SELECT pg_try_advisory_xact_lock(5065941)")):
                    return SchemaStatus("migration_busy")
            before = _inspect_schema(connection)
            if before.code not in {"schema_empty", "schema_outdated", "schema_current"}:
                return before
            if revision not in {"head", *REVISIONS}:
                return SchemaStatus("migration_target_invalid")
            if (before.revision in REVISIONS and revision in REVISIONS
                    and REVISIONS.index(revision) < REVISIONS.index(before.revision)):
                return SchemaStatus("migration_target_invalid", before.revision)
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
            after = _inspect_schema(connection)
            if after.code not in {"schema_current", "schema_outdated"}:
                raise RuntimeError("migration_validation_failed")
            return after
    except Exception:
        return SchemaStatus("migration_failed")
    finally:
        if engine is not None:
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migraciones explícitas de F.A.M.A.; no lee archivos .env")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("status")
    upgrade = subparsers.add_parser("upgrade")
    upgrade.add_argument("--apply", action="store_true", required=True)
    upgrade.add_argument("--revision", choices=["head", *REVISIONS], default="head")
    arguments = parser.parse_args()
    # Deliberadamente no se importa configuration ni se carga backend/.env.
    url = os.environ.get("DATABASE_URL")
    if not url:
        status = SchemaStatus("database_configuration_missing")
    elif arguments.operation == "status":
        status = check_schema(url)
    else:
        status = upgrade_schema(url, arguments.revision)
    print(json.dumps(asdict(status)))
    return 0 if status.code in {"schema_empty", "schema_outdated", "schema_current"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
