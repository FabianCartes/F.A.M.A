"""Explicit fresh manual-test initialization; never repair or repeat a legacy backfill."""
import argparse
import json


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


def initialize(engine, *, writers_stopped=False):
    from sqlalchemy import inspect
    if writers_stopped is not True:
        raise ValueError("Stop all writers before initialization")
    if inspect(engine).get_table_names():
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
    verify(engine)
    return {"prepared": True, "stages": ["application", "imports", "metadata", "jobs", "receipts", "chunks"]}


def verify(engine):
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
    return {"prepared": True, "verification": "schema_and_markers"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit fama_zip_manual PostgreSQL target only.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--initialize", action="store_true", help="Initialize an empty dedicated schema once.")
    action.add_argument("--check", action="store_true", help="Read-only schema/version verification, no backfill.")
    parser.add_argument("--writers-stopped", action="store_true", help="Acknowledge stopped API and external worker.")
    args = parser.parse_args(argv)
    from sqlalchemy.engine import make_url
    try:
        url = make_url(args.database_url)
        valid = (url.drivername in ("postgresql", "postgresql+psycopg2")
                 and url.database == "fama_zip_manual" and not url.query
                 and (url.host, url.port) in (("db", 5432), ("172.30.252.30", 5432)))
    except Exception:
        valid = False
    if not valid:
        parser.error("Target must be the dedicated local fama_zip_manual PostgreSQL database")
    if args.initialize != args.writers_stopped:
        parser.error("--initialize requires --writers-stopped; --check does not accept it")
    engine = None
    try:
        from sqlalchemy import create_engine
        from app.database import normalize_database_url
        engine = create_engine(normalize_database_url(args.database_url))
        result = initialize(engine, writers_stopped=True) if args.initialize else verify(engine)
    except Exception:
        parser.exit(1, "Manual database preparation failed; preserve state. Do not repeat backfill on a nonempty schema.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
