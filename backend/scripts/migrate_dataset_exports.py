"""Explicit additive export/session tables; never migrate on HTTP or worker startup."""
import argparse

from scripts.migrate_dataset_import_jobs import JobMigrationError, _verify_table


def migrate_exports(engine, *, writers_stopped=False):
    if writers_stopped is not True:
        raise JobMigrationError("stop_writers_before_export_migration")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise JobMigrationError("unsupported_export_database")
    from app.models.dataset_export import EXPORT_MODELS
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.exec_driver_sql("LOCK TABLE imported_dataset IN SHARE ROW EXCLUSIVE MODE")
        for model in EXPORT_MODELS:
            model.__table__.create(connection, checkfirst=True)
            _verify_table(connection, model.__table__)
    return {"version": 1, "verified": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit maintenance database; no ambient credentials.")
    parser.add_argument("--writers-stopped", action="store_true", required=True,
                        help="Acknowledge that API and import/export workers are stopped.")
    args = parser.parse_args(argv)
    engine = None
    try:
        from sqlalchemy import create_engine
        from app.database import normalize_database_url
        engine = create_engine(normalize_database_url(args.database_url))
        migrate_exports(engine, writers_stopped=args.writers_stopped)
    except Exception:
        parser.exit(1, "Export migration failed; preserve state and inspect the maintenance procedure.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print('{"version": 1, "verified": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
