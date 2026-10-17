"""Run one durable export attempt or explicit export cleanup; no implicit migration."""
import argparse
import json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit migrated database URL.")
    parser.add_argument("--import-root", required=True, help="Private physical import root shared with the API.")
    parser.add_argument("--export-root", required=True, help="Private physical export root shared with the download server.")
    parser.add_argument("--cleanup-only", action="store_true", help="Reclaim expired/failed attempts, without cloud operations.")
    args = parser.parse_args(argv)
    engine = None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import normalize_database_url
        from app.services.dataset_imports import DatasetImports
        from app.services.dataset_import_storage import GCSImportStorage
        from app.services.dataset_import_worker import _private_root
        from app.services.dataset_exports import ExportExecution, ExportQueue
        root, imports = _private_root(args.export_root), _private_root(args.import_root)
        engine = create_engine(normalize_database_url(args.database_url))
        queue = ExportQueue(sessionmaker(bind=engine), DatasetImports(imports))
        result = queue.cleanup(root) if args.cleanup_only else {
            "claimed": ExportExecution(queue, root, storage=GCSImportStorage()).run_once()}
    except Exception:
        parser.exit(1, "Export worker unavailable; preserve state and inspect the operation manual.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
