"""Explicit additive receipt migration; stop API/worker writers before applying."""
import argparse

from sqlalchemy import inspect, select


def migrate_receipts(engine, *, writers_stopped=False):
    if writers_stopped is not True:
        raise ValueError("stop_writers_before_receipt_migration")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise ValueError("unsupported_receipt_database")
    from app.models.dataset_import_receipt import RECEIPT_MODELS, ImportReceiptSchema
    from scripts.migrate_dataset_import_jobs import _verify_table

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("LOCK TABLE dataset_import IN SHARE ROW EXCLUSIVE MODE")
        inspector = inspect(conn)
        if not inspector.has_table("dataset_import") or not inspector.has_table("dataset_import_job_gate"):
            raise ValueError("receipt_migration_requires_import_and_job_schema")
        for model in RECEIPT_MODELS:
            model.__table__.create(conn, checkfirst=True)
            _verify_table(conn, model.__table__)
        table = ImportReceiptSchema.__table__
        rows = conn.execute(select(table)).mappings().all()
        if not rows:
            conn.execute(table.insert(), dict(id=1, version=1))
        elif len(rows) != 1 or rows[0]["id"] != 1 or rows[0]["version"] != 1:
            raise ValueError("incompatible_receipt_version")
    return {"version": 1, "verified": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit target; no dotenv or ambient URL.")
    parser.add_argument("--writers-stopped", action="store_true", required=True,
                        help="Acknowledge API and import workers are stopped; back up before applying.")
    args = parser.parse_args(argv)
    engine = None
    try:
        from sqlalchemy import create_engine
        from app.database import normalize_database_url
        engine = create_engine(normalize_database_url(args.database_url))
        migrate_receipts(engine, writers_stopped=args.writers_stopped)
    except Exception:
        parser.exit(1, "Receipt migration failed; preserve state and inspect the maintenance procedure.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print('{"version": 1, "verified": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
