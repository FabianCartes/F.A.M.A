"""Explicit additive chunk migration; stop API and worker writers first."""
import argparse

from sqlalchemy import inspect, select


def migrate_chunks(engine, *, writers_stopped=False):
    if writers_stopped is not True:
        raise ValueError("stop_writers_before_chunk_migration")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise ValueError("unsupported_chunk_database")
    from app.models.dataset_import_receipt import ImportReceipt, ImportReceiptSchema
    from app.models.dataset_import_chunk import CHUNK_MODELS, ImportChunkSchema, ImportChunk, ImportChunkActivity
    from scripts.migrate_dataset_import_jobs import _verify_table

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("LOCK TABLE dataset_import IN SHARE ROW EXCLUSIVE MODE")
        if not inspect(conn).has_table(ImportReceiptSchema.__tablename__):
            raise ValueError("chunk_migration_requires_receipt_schema")
        for model in (ImportReceiptSchema, ImportReceipt):
            _verify_table(conn, model.__table__)
        if conn.execute(select(ImportReceiptSchema.version).where(ImportReceiptSchema.id == 1)).scalar() != 1:
            raise ValueError("chunk_migration_requires_receipt_acknowledgement")
        for model in CHUNK_MODELS:
            model.__table__.create(conn, checkfirst=True)
            _verify_table(conn, model.__table__)
        marker = ImportChunkSchema.__table__
        versions = conn.execute(select(marker)).mappings().all()
        if versions and (len(versions) != 1 or dict(versions[0]) != {"id": 1, "version": 1}):
            raise ValueError("incompatible_chunk_version")
        for model in (ImportChunk, ImportChunkActivity):
            orphan = conn.execute(select(model.import_id).outerjoin(ImportReceipt,
                ImportReceipt.import_id == model.import_id).where(ImportReceipt.import_id.is_(None)).limit(1)).first()
            if orphan:
                raise ValueError("incompatible_chunk_reference")
        # Verify a bounded stream of rows, never repair acknowledged progress.
        receipts = conn.execute(select(ImportReceipt.__table__).execution_options(yield_per=200)).mappings()
        for receipt in receipts:
            offset, index = 0, 0
            chunks = conn.execute(select(ImportChunk.__table__).where(
                ImportChunk.import_id == receipt["import_id"]).order_by(ImportChunk.chunk_index)
                .execution_options(yield_per=200)).mappings()
            for chunk in chunks:
                expected = min(receipt["chunk_bytes"], receipt["size_bytes"] - offset)
                if (chunk["chunk_index"] != index or chunk["offset_bytes"] != offset or
                        chunk["length_bytes"] != expected or expected <= 0 or
                        any(c not in "0123456789abcdef" for c in chunk["sha256"])):
                    raise ValueError("incompatible_chunk_prefix")
                offset += expected
                index += 1
            if offset != receipt["received_bytes"] or (receipt["status"] == "sealed" and offset != receipt["size_bytes"]):
                raise ValueError("incompatible_chunk_progress")
            activity = conn.execute(select(ImportChunkActivity.import_id).where(
                ImportChunkActivity.import_id == receipt["import_id"])).scalar()
            if offset and not activity:
                raise ValueError("incompatible_chunk_activity")
        if not versions:
            conn.execute(marker.insert(), {"id": 1, "version": 1})
    return {"version": 1, "verified": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit target; no dotenv or ambient URL.")
    parser.add_argument("--writers-stopped", action="store_true", required=True,
                        help="Acknowledge stopped API/workers and a verified backup before applying.")
    args = parser.parse_args(argv)
    engine = None
    try:
        from sqlalchemy import create_engine
        from app.database import normalize_database_url
        engine = create_engine(normalize_database_url(args.database_url))
        migrate_chunks(engine, writers_stopped=args.writers_stopped)
    except Exception:
        parser.exit(1, "Chunk migration failed; preserve state and inspect the maintenance procedure.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print('{"version": 1, "verified": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
