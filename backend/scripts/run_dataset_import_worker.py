"""Execute at most one durable import attempt; supervision belongs to the caller."""
import argparse
import json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit migrated database; no ambient URL or migration.")
    parser.add_argument("--import-root", required=True, help="Existing private physical absolute import root shared with the API.")
    parser.add_argument("--staging-root", required=True, help="Existing private attempt root, stable across restarts, on the same filesystem.")
    args = parser.parse_args(argv)
    engine = None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import normalize_database_url
        from app.services.dataset_import_execution import ImportExecution
        from app.services.dataset_import_jobs import ImportJobQueue
        from app.services.dataset_import_storage import GCSImportStorage
        from app.services.dataset_import_worker import _private_root
        from app.services.dataset_imports import DatasetImports

        root, staging = _private_root(args.import_root), _private_root(args.staging_root)
        if root.stat().st_dev != staging.stat().st_dev:
            raise ValueError("Publication requires the same filesystem")
        engine = create_engine(normalize_database_url(args.database_url))
        queue = ImportJobQueue(sessionmaker(bind=engine))
        execution = ImportExecution(queue, DatasetImports(root), staging, storage=GCSImportStorage())
        claimed = execution.run_once()
    except Exception:
        # Connection/driver/paths may contain secrets. Domain errors live in job state.
        parser.exit(1, "Import worker unavailable; preserve state and inspect the operation manual.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps({"claimed": claimed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
