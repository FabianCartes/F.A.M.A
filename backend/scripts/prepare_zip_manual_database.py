"""Explicit fresh manual-test initialization; never repair or repeat a legacy backfill."""
import argparse
import json
import re
import sys


def _application_models():
    from app import models
    return tuple(getattr(models, name) for name in models.__all__
                 if name not in ("ImportedDataset", "DatasetImport"))


def _verify_application_table(connection, table):
    from sqlalchemy import CheckConstraint, MetaData, inspect
    from scripts.migrate_dataset_import_jobs import _verify_table

    if table.name != "model_evaluation":
        _verify_table(connection, table)
        return
    # Reuse this table's existing bounded PostgreSQL catalog spellings, not the
    # queue verifier's simpler IN normalization. No DDL or metadata mutation.
    from scripts.migrate_model_evaluations import _checks_match
    if not _checks_match(table, connection.dialect, inspect(connection).get_check_constraints(table.name)):
        raise ValueError("Incompatible evaluation check constraints")
    metadata = MetaData()
    table.metadata.tables["modelo"].to_metadata(metadata)
    structural = table.to_metadata(metadata)
    for constraint in tuple(structural.constraints):
        if isinstance(constraint, CheckConstraint):
            structural.constraints.remove(constraint)
    _verify_table(connection, structural)


def initialize(engine, *, writers_stopped=False, training_development=False):
    from sqlalchemy import inspect
    if writers_stopped is not True:
        raise ValueError("Stop all writers before initialization")
    if engine.dialect.name == "postgresql":
        from sqlalchemy import text
        with engine.connect() as connection:
            nonempty = connection.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_namespace n
                    WHERE n.nspname <> 'public'
                      AND n.nspname <> 'information_schema'
                      AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                    UNION ALL
                    SELECT 1 FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 1 FROM pg_catalog.pg_proc p
                    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 1 FROM pg_catalog.pg_type t
                    JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'public'
                    UNION ALL
                    SELECT 1 FROM pg_catalog.pg_largeobject_metadata
                    UNION ALL
                    SELECT 1 FROM pg_catalog.pg_publication
                )
            """)).scalar_one()
        if nonempty is not False:
            raise ValueError("Refusing nonempty schema; use --check, never repeat backfill as repair")
    elif inspect(engine).get_table_names():
        raise ValueError("Refusing nonempty schema; use --check, never repeat backfill as repair")
    from app.database import Base
    from scripts.migrate_dataset_imports import create_import_tables
    from scripts.migrate_dataset_import_metadata import migrate_metadata
    from scripts.migrate_dataset_import_jobs import migrate_jobs
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_import_chunks import migrate_chunks

    basic = [model.__table__ for model in _application_models()]
    Base.metadata.create_all(engine, tables=basic)
    create_import_tables(engine)
    migrate_metadata(engine, writers_stopped=True)
    migrate_jobs(engine, writers_stopped=True)
    migrate_receipts(engine, writers_stopped=True)
    migrate_chunks(engine, writers_stopped=True)
    stages = ["application", "imports", "metadata", "jobs", "receipts", "chunks"]
    if training_development:
        from scripts.migrate_training_snapshots import migrate_snapshots
        from scripts.migrate_imported_training_source import migrate_imported_sources
        from scripts.migrate_web_sessions import migrate_web_sessions
        migrate_snapshots(engine, writers_stopped=True)
        migrate_imported_sources(engine, writers_stopped=True)
        migrate_web_sessions(engine, writers_stopped=True)
        stages.extend(["snapshots", "imported_sources", "web_sessions"])
    verify(engine, training_development=training_development)
    return {"prepared": True, "stages": stages}


def verify(engine, *, training_development=False):
    from sqlalchemy import select
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_metadata import BACKFILL_MODELS, MetadataBackfill
    from app.models.dataset_import_job import JOB_MODELS, ImportJobGate
    from app.models.dataset_import_receipt import RECEIPT_MODELS, ImportReceiptSchema
    from app.models.dataset_import_chunk import CHUNK_MODELS, ImportChunkSchema
    from scripts.migrate_dataset_import_jobs import _verify_table

    with engine.connect() as connection:
        for model in _application_models():
            _verify_application_table(connection, model.__table__)
        for model in (DatasetImport, ImportedDataset, *BACKFILL_MODELS,
                      *JOB_MODELS, *RECEIPT_MODELS, *CHUNK_MODELS):
            _verify_table(connection, model.__table__)
        for model in (MetadataBackfill, ImportJobGate, ImportReceiptSchema, ImportChunkSchema):
            versions = connection.execute(select(model.version)).scalars().all()
            if versions != [1]:
                raise ValueError("Manual import schema requires verified version markers")
    if training_development:
        from app.models.training_snapshot import TrainingSnapshot, SnapshotMember
        from scripts.migrate_imported_training_source import validate_imported_sources
        from scripts.migrate_web_sessions import validate_web_sessions
        with engine.connect() as connection:
            for model in (TrainingSnapshot, SnapshotMember):
                _verify_table(connection, model.__table__)
        validate_imported_sources(engine)
        validate_web_sessions(engine)
    return {"prepared": True, "verification": (
        "training_schema_and_markers" if training_development else "schema_and_markers")}


def _guard_training_development_checkouts(engine, database, system_id, database_oid):
    from sqlalchemy import event

    def verify_checkout(dbapi_connection, connection_record, connection_proxy):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(
                "SELECT current_database(), oid, system_identifier "
                "FROM pg_database CROSS JOIN pg_control_system() "
                "WHERE datname = current_database()"
            )
            row = cursor.fetchone()
            if (row is None or len(row) != 3 or row[0] != database
                    or str(row[1]) != database_oid or str(row[2]) != system_id):
                raise ValueError("Connected database identity mismatch")
        finally:
            cursor.close()

    # Pool checkout runs on every acquisition, including reconnect after
    # invalidation. Use the DBAPI connection directly to avoid recursive checkout.
    event.listen(engine, "checkout", verify_checkout)


def _verify_training_development_identity(engine, database, system_id, database_oid):
    from sqlalchemy import text

    with engine.connect() as connection:
        actual_database, actual_oid, actual_system_id = connection.execute(text(
            "SELECT current_database(), oid, system_identifier "
            "FROM pg_database CROSS JOIN pg_control_system() "
            "WHERE datname = current_database()"
        )).one()
        if (actual_database != database or str(actual_oid) != database_oid
                or str(actual_system_id) != system_id):
            raise ValueError("Connected database identity mismatch")


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # Unknown arguments can contain a URL or another secret.
        if message.startswith("unrecognized arguments:"):
            message = "unrecognized arguments"
        elif "ignored explicit argument" in message:
            message = "boolean options do not accept values"
        super().error(message)


def _extended_cli(argv):
    # Only a standalone option is opt-in; never interpret an option value as one.
    value_options = {"--database-url", "--expected-system-id", "--expected-database-oid"}
    skip_value = False
    for token in argv:
        if skip_value:
            skip_value = False
            continue
        if token == "--":
            break
        if token in value_options:
            skip_value = True
        elif token in ("--training-development", "--help", "-h"):
            return True
    return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extended = _extended_cli(argv)
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit PostgreSQL target; training development requires opt-in and expected identity.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--initialize", action="store_true", help="Initialize an empty dedicated schema once.")
    action.add_argument("--check", action="store_true", help="Read-only schema/version verification, no backfill.")
    parser.add_argument("--writers-stopped", action="store_true", help="Acknowledge stopped API and external worker.")
    if extended:
        parser.add_argument("--training-development", action="store_true", help="Select a generated training database and initialize/check snapshots, model sources and web sessions too; does not create accounts or stop writers.")
        parser.add_argument("--expected-system-id", help="Expected PostgreSQL cluster system identifier.")
        parser.add_argument("--expected-database-oid", help="Expected connected database OID.")
    else:
        parser.set_defaults(training_development=False, expected_system_id=None, expected_database_oid=None)
    args = parser.parse_args(argv)
    from sqlalchemy.engine import make_url
    try:
        url = make_url(args.database_url)
        hosts = (("db", 5432), ("172.30.252.30", 5432))
        if args.training_development:
            hosts += (("172.30.253.30", 5432),)
            target_valid = (re.fullmatch(r"fama_training_dev_[0-9]{14}", url.database or "")
                            and all(value is not None and re.fullmatch(r"[1-9][0-9]*", value)
                                    for value in (args.expected_system_id, args.expected_database_oid)))
        else:
            target_valid = (url.database == "fama_zip_manual"
                            and args.expected_system_id is None and args.expected_database_oid is None)
        valid = (url.drivername in ("postgresql", "postgresql+psycopg2")
                 and target_valid and not url.query and (url.host, url.port) in hosts)
    except Exception:
        valid = False
    if not valid:
        parser.error("Invalid or unauthorized database target" if args.training_development else
                     "Target must be the dedicated local fama_zip_manual PostgreSQL database")
    if args.initialize != args.writers_stopped:
        parser.error("--initialize requires --writers-stopped; --check does not accept it")
    engine = None
    try:
        from sqlalchemy import create_engine
        from app.database import normalize_database_url
        engine = create_engine(normalize_database_url(args.database_url))
        if args.training_development:
            _guard_training_development_checkouts(
                engine, url.database, args.expected_system_id, args.expected_database_oid)
            _verify_training_development_identity(
                engine, url.database, args.expected_system_id, args.expected_database_oid)
        options = {"training_development": True} if args.training_development else {}
        result = initialize(engine, writers_stopped=True, **options) if args.initialize else verify(engine, **options)
    except Exception:
        parser.exit(1, "Manual database preparation failed; preserve state. Do not repeat backfill on a nonempty schema.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
