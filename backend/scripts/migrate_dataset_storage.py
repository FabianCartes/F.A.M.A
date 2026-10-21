"""Inspect or explicitly prepare physical-budget metadata; never activate writers."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import CheckConstraint, func, inspect, select


def _normalized_check(sql):
    # PostgreSQL reflects varchar IN as text = ANY (ARRAY[...]). The ledger
    # uses only simple checks; require the exact set, not a permissive subset.
    sql = re.sub(r"::(?:character varying|text)(?:\[\])?", "", str(sql).lower())
    sql = "".join(sql.split()).replace("(", "").replace(")", "")
    return sql.replace("=anyarray[", "in").replace("]", "")


def _verify_storage_table(conn, table):
    from scripts.migrate_dataset_import_jobs import _verify_table

    _verify_table(conn, table)
    expected = {_normalized_check(item.sqltext) for item in table.constraints
                if isinstance(item, CheckConstraint)}
    actual = {_normalized_check(item["sqltext"]) for item in inspect(conn).get_check_constraints(table.name)}
    if actual != expected:
        raise ValueError("incompatible_storage_checks")


def _inspect(conn):
    from app.models.dataset_storage import STORAGE_MODELS, StorageGrant, StoragePool, StorageSchema

    present = [inspect(conn).has_table(model.__tablename__) for model in STORAGE_MODELS]
    if not any(present):
        return {"version": 1, "state": "absent", "schema_verified": False,
                "pools": 0, "live_grants": 0}
    if not all(present):
        raise ValueError("incomplete_storage_schema")
    for model in STORAGE_MODELS:
        _verify_storage_table(conn, model.__table__)
    rows = conn.execute(select(StorageSchema.__table__)).mappings().all()
    pools = conn.scalar(select(func.count()).select_from(StoragePool.__table__))
    grants = conn.scalar(select(func.count()).select_from(StorageGrant.__table__))
    if not rows and pools == 0 and grants == 0:
        return {"version": 1, "state": "uninitialized", "schema_verified": False,
                "pools": 0, "live_grants": 0}
    if (len(rows) != 1 or rows[0]["id"] != 1 or rows[0]["version"] != 1
            or rows[0]["state"] not in ("prepared", "active")):
        raise ValueError("incompatible_storage_version")
    return {"version": 1, "state": rows[0]["state"], "schema_verified": True,
            "pools": pools,
            "live_grants": conn.scalar(select(func.count()).select_from(
                StorageGrant.__table__).where(StorageGrant.state == "live"))}


def inspect_storage(engine):
    """Read existing metadata without preparing or reconciling any writers."""
    with engine.connect() as conn:
        return dict(_inspect(conn), action="inspect")


def migrate_storage(engine, *, writers_stopped=False):
    """Prepare empty additive metadata; never adopt existing work or enable a pool."""
    if writers_stopped is not True:
        raise ValueError("stop_writers_before_storage_migration")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise ValueError("unsupported_storage_database")
    from app.models.dataset_import_job import ImportJobGate
    from app.models.dataset_storage import STORAGE_MODELS, StorageSchema
    from scripts.migrate_dataset_import_jobs import _verify_table

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("LOCK TABLE dataset_import_job_gate IN SHARE ROW EXCLUSIVE MODE")
        _verify_table(conn, ImportJobGate.__table__)
        gates = conn.execute(select(ImportJobGate.__table__)).mappings().all()
        if len(gates) != 1 or gates[0]["id"] != 1 or gates[0]["version"] != 1:
            raise ValueError("storage_requires_verified_job_gate")
        current = _inspect(conn)
        if current["state"] == "absent":
            for model in STORAGE_MODELS:
                model.__table__.create(conn)
        if current["state"] in ("absent", "uninitialized"):
            conn.execute(StorageSchema.__table__.insert(), {"id": 1, "version": 1, "state": "prepared"})
        return dict(_inspect(conn), action="prepare")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True,
                        help="Explicit database target; never read dotenv or ambient credentials.")
    parser.add_argument("--apply", action="store_true",
                        help="Prepare additive tables only; default is read-only inspection.")
    parser.add_argument("--writers-stopped", action="store_true",
                        help="Required with --apply: acknowledge all participating writers are stopped.")
    args = parser.parse_args(argv)
    if args.apply != args.writers_stopped:
        parser.error("--apply and --writers-stopped must be supplied together")
    engine = None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        from app.database import normalize_database_url
        url = make_url(normalize_database_url(args.database_url))
        if url.get_backend_name() not in ("sqlite", "postgresql"):
            raise ValueError("unsupported_storage_database")
        if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
            # Never let an inspection create an empty file by connecting to a
            # misspelled target. URI options are deliberately not accepted.
            path = Path(url.database)
            if url.query or not path.is_file():
                raise ValueError("existing_sqlite_file_required")
            if not args.apply:
                url = url.set(database="file:" + quote(str(path.resolve()), safe="/"),
                              query={"mode": "ro", "uri": "true"})
        engine = create_engine(url)
        result = (migrate_storage(engine, writers_stopped=args.writers_stopped)
                  if args.apply else inspect_storage(engine))
    except Exception:
        parser.exit(1, "Storage maintenance failed; preserve state and inspect the maintenance procedure.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
