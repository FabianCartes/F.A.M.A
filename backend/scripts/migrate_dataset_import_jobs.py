"""Explicit additive execution-queue migration, without starting workers."""
import argparse
import re

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select


class JobMigrationError(ValueError):
    pass


def _verify_table(conn, table):
    inspector = inspect(conn)
    columns = {column["name"]: column for column in inspector.get_columns(table.name)}
    if set(columns) != set(table.columns.keys()):
        raise JobMigrationError("incompatible_job_schema")
    for column in table.columns:
        actual = columns[column.name]
        if actual["nullable"] != column.nullable:
            raise JobMigrationError("incompatible_job_nullability")
        effective_type = column.type._variant_mapping.get(conn.dialect.name, column.type)
        if not isinstance(actual["type"], type(effective_type)):
            raise JobMigrationError("incompatible_job_column_type")
    if inspector.get_pk_constraint(table.name)["constrained_columns"] != [column.name for column in table.primary_key]:
        raise JobMigrationError("incompatible_job_primary_key")
    expected_foreign = {(tuple(column.name for column in constraint.columns),
                         tuple(element.column.table.name for element in constraint.elements),
                         tuple(element.column.name for element in constraint.elements))
                        for constraint in table.foreign_key_constraints}
    actual_foreign = {(tuple(item["constrained_columns"]),
                       (item["referred_table"],) * len(item["referred_columns"]),
                       tuple(item["referred_columns"]))
                      for item in inspector.get_foreign_keys(table.name)}
    if actual_foreign != expected_foreign:
        raise JobMigrationError("incompatible_job_foreign_keys")
    def normalize(sql):
        # PostgreSQL renders varchar IN checks as text = ANY (ARRAY[...]).
        # Compare the equivalent reflected form without weakening the values.
        sql = re.sub(r"::(?:character varying|text)(?:\[\])?", "", sql.lower())
        sql = "".join(sql.split()).replace("(", "").replace(")", "")
        return sql.replace("=anyarray[", "in").replace("]", "")
    actual_checks = {normalize(check["sqltext"]) for check in inspector.get_check_constraints(table.name)}
    expected_checks = {normalize(str(check.sqltext)) for check in table.constraints
                       if isinstance(check, CheckConstraint)}
    if not expected_checks.issubset(actual_checks):
        raise JobMigrationError("incompatible_job_constraints")
    actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
    expected_unique = {tuple(column.name for column in item.columns) for item in table.constraints
                       if isinstance(item, UniqueConstraint)}
    if not expected_unique.issubset(actual_unique):
        raise JobMigrationError("incompatible_job_uniqueness")
    indexes = {item["name"]: item for item in inspector.get_indexes(table.name)}
    for index in table.indexes:
        actual = indexes.get(index.name)
        if (actual is None or bool(actual["unique"]) != index.unique
                or actual["column_names"] != [column.name for column in index.columns]):
            raise JobMigrationError("incompatible_job_indexes")
        predicate = index.dialect_options[conn.dialect.name].get("where")
        actual_predicate = actual.get("dialect_options", {}).get(conn.dialect.name + "_where")
        if predicate is not None and (actual_predicate is None
                or normalize(str(actual_predicate)) != normalize(str(predicate))):
            raise JobMigrationError("incompatible_job_index_predicate")


def migrate_jobs(engine, *, writers_stopped=False):
    if writers_stopped is not True:
        raise JobMigrationError("stop_writers_before_job_migration")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise JobMigrationError("unsupported_job_database")
    from app.models.dataset_import_job import JOB_MODELS, ImportJobGate

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("LOCK TABLE dataset_import IN SHARE ROW EXCLUSIVE MODE")
        for model in JOB_MODELS:
            table = model.__table__
            table.create(conn, checkfirst=True)
            _verify_table(conn, table)
        if engine.dialect.name == "postgresql":
            conn.exec_driver_sql("LOCK TABLE dataset_import_job_gate, dataset_import_job IN SHARE ROW EXCLUSIVE MODE")
        gate = ImportJobGate.__table__
        rows = conn.execute(select(gate)).mappings().all()
        if not rows:
            conn.execute(gate.insert(), dict(id=1, version=1, generation=0))
        elif len(rows) != 1 or rows[0]["id"] != 1 or rows[0]["version"] != 1:
            raise JobMigrationError("incompatible_job_version")
    return {"version": 1, "verified": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create durable import job tables during maintenance; no worker startup.")
    parser.add_argument("--database-url", required=True, help="Explicit target database; never inferred from ambient credentials.")
    parser.add_argument("--writers-stopped", action="store_true", required=True,
                        help="Acknowledge that API and import workers are stopped.")
    args = parser.parse_args(argv)
    engine = None
    try:
        from sqlalchemy import create_engine
        from app.database import normalize_database_url
        engine = create_engine(normalize_database_url(args.database_url))
        migrate_jobs(engine, writers_stopped=args.writers_stopped)
    except Exception:
        # Do not echo connection URLs, exception messages, paths or credentials.
        parser.exit(1, "Job migration failed; preserve state and inspect the maintenance procedure.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print('{"version": 1, "verified": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
