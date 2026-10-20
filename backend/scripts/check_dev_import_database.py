"""Read-only readiness, not a migration planner or an automatic repair."""
import argparse
import json
import os
from pathlib import Path


def verify(engine):
    from sqlalchemy import inspect, select
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_metadata import (
        BACKFILL_MODELS, MetadataBackfill, ImportSummary, DatasetSummary,
    )
    from app.models.dataset_import_job import JOB_MODELS, ImportJobGate
    from app.models.dataset_import_receipt import RECEIPT_MODELS, ImportReceiptSchema
    from app.models.dataset_import_chunk import CHUNK_MODELS, ImportChunkSchema
    from scripts.migrate_dataset_import_jobs import _verify_table

    with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        models = (DatasetImport, ImportedDataset, *BACKFILL_MODELS,
                  *JOB_MODELS, *RECEIPT_MODELS, *CHUNK_MODELS)
        if not {model.__tablename__ for model in models} <= set(inspect(connection).get_table_names()):
            raise ValueError("Missing import tables")
        for model in models:
            _verify_table(connection, model.__table__)
        for model in (MetadataBackfill, ImportJobGate, ImportReceiptSchema, ImportChunkSchema):
            if connection.execute(select(model.version)).scalars().all() != [1]:
                raise ValueError("Missing verified import schema marker")
        for source, summary, key in ((DatasetImport, ImportSummary, ImportSummary.import_id),
                                     (ImportedDataset, DatasetSummary, DatasetSummary.dataset_id)):
            if connection.execute(select(source.id).outerjoin(summary, source.id == key)
                                  .where(key.is_(None)).limit(1)).first():
                raise ValueError("Missing normalized summary; operator reconciliation required")
    return {"ready": True, "verification": "import_schema_and_markers"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-config", action="store_true",
                        help="Emit verified local worker configuration for the host launcher only.")
    args = parser.parse_args(argv)
    engine = None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        from app.database import normalize_database_url
        from app.services.dataset_import_worker import _private_root

        if os.environ.get("FAMA_ENV") != "development" or os.environ.get("FAMA_IMPORT_DEV_MODE") != "1":
            raise ValueError("Development mode required")
        url = make_url(normalize_database_url(os.environ["DATABASE_URL"]))
        if (url.drivername not in ("postgresql", "postgresql+psycopg2")
                or url.host != "db" or url.port not in (None, 5432)
                or not url.database or url.query):
            raise ValueError("Expected the Compose development database")
        root = _private_root(os.environ["FAMA_IMPORT_ROOT"])
        # Reject the normal /app/data mount or a caller-selected store.
        if root.parts[-3:] != ("backend", "data-dev", "dataset-imports"):
            raise ValueError("Expected the physical development import root")
        engine = create_engine(normalize_database_url(os.environ["DATABASE_URL"]),
                               connect_args={"connect_timeout": 5})
        result = verify(engine)
        if args.worker_config:
            # Captured by the host launcher, never print this payload in logs.
            result = {"database_url": url.set(host="172.30.253.30", port=5432)
                      .render_as_string(hide_password=False), "import_root": str(root),
                      "limits_environment": {key: value for key, value in os.environ.items()
                                             if key.startswith("FAMA_IMPORT_")}}
    except Exception:
        parser.exit(1, "Development imports are not ready. Preserve data; inspect the schema and "
                    "authorize pending migrations separately. No migration or backfill was applied.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
