"""Inventory retained work or explicitly activate a drained physical-budget store.

No legacy work is adopted, cancelled, deleted, or assigned guessed grants.
Activation requires separately authorized maintenance and a qualified root profile.
"""
import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from sqlalchemy import func, select


def inventory(conn):
    from app.models.dataset_export import DatasetExport
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_job import ImportJob, ImportJobGate
    from app.models.dataset_import_metadata import ImportSummary, DatasetSummary
    from app.models.dataset_import_receipt import ImportReceipt
    from app.services.dataset_storage import _verify_schema
    from scripts.migrate_dataset_import_jobs import _verify_table
    from scripts.migrate_dataset_storage import _inspect

    current = _inspect(conn)
    if current["state"] not in ("prepared", "active"):
        raise ValueError("prepare_storage_explicitly")
    _verify_schema(conn)
    for model in (DatasetImport, ImportJob, ImportJobGate, ImportReceipt, DatasetExport,
                  ImportSummary, ImportedDataset, DatasetSummary):
        _verify_table(conn, model.__table__)
    for source, summary, key in ((DatasetImport, ImportSummary, ImportSummary.import_id),
                                (ImportedDataset, DatasetSummary, DatasetSummary.dataset_id)):
        missing = select(source.id).outerjoin(summary, key == source.id).where(key.is_(None)).limit(1)
        if conn.execute(missing).first() is not None:
            raise ValueError("unclassified_missing_summary")

    def count(model, condition):
        return conn.scalar(select(func.count()).select_from(model).where(condition))

    cleanup = 0
    for (preview,) in conn.execute(select(ImportSummary.preview)).yield_per(100):
        if not isinstance(preview, dict):
            raise ValueError("unclassified_import_summary")
        intent = preview.get("_cleanup")
        if intent is not None:
            if not isinstance(intent, dict) or intent.get("state") not in ("pending", "deleting", "done"):
                raise ValueError("unclassified_cleanup")
            cleanup += intent["state"] != "done"
    counts = {
        "recoverable_imports": count(DatasetImport, DatasetImport.status.not_in(("imported", "cancelled"))),
        "active_jobs": count(ImportJob, ImportJob.status.in_(("queued", "running"))),
        "active_receipts": count(ImportReceipt, ImportReceipt.reservation_active.is_(True)),
        "recoverable_exports": count(DatasetExport, DatasetExport.status.not_in(("succeeded", "failed", "expired"))),
        "cleanup_intents": cleanup,
    }
    return dict(current, action="inventory", counts=counts,
                drained=not any(counts.values()) and current["live_grants"] == 0)


@contextmanager
def stopped_directories(policy):
    """Acquire existing callback/download directory locks before the DB gate."""
    with ExitStack() as locks:
        roots = {policy.roots["attempts"], policy.roots["exports"], policy.roots["imports"] / "staging"}
        paths = set(roots)
        for root in roots:
            for index, path in enumerate(root.iterdir()):
                if index >= 100000 or path.is_symlink() or not path.is_dir():
                    raise ValueError("unclassified_or_excessive_staging")
                paths.add(path)
        for path in sorted(paths):
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            locks.callback(os.close, fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("writer_or_download_still_active") from error
        yield


def reconcile_storage(engine, *, policy=None, apply=False, writers_stopped=False):
    """Drain-first only: preserve ambiguous work and leaked grants for operators."""
    if not apply:
        if writers_stopped:
            raise ValueError("writers_stopped_requires_apply")
        with engine.connect() as conn:
            return inventory(conn)
    if writers_stopped is not True:
        raise ValueError("stop_writers_before_storage_reconciliation")
    if policy is None:
        raise ValueError("explicit_qualified_profile_required")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise ValueError("unsupported_storage_database")
    from sqlalchemy.orm import Session
    from app.models.dataset_import_job import ImportJobGate
    from app.models.dataset_storage import StoragePool, StorageSchema
    from scripts.migrate_dataset_import_jobs import _verify_table

    with stopped_directories(policy), engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        _verify_table(conn, ImportJobGate.__table__)
        gates = conn.execute(select(ImportJobGate.__table__).with_for_update()).mappings().all()
        if len(gates) != 1 or gates[0]["id"] != 1 or gates[0]["version"] != 1:
            raise ValueError("storage_requires_verified_job_gate")
        current = inventory(conn)
        if not current["drained"]:
            raise ValueError("storage_reconciliation_required")
        existing = conn.execute(select(StoragePool.__table__)).mappings().all()
        if existing:
            if {row["id"] for row in existing} != set(policy.free_floors):
                raise ValueError("incompatible_storage_pools")
        elif current["state"] == "prepared":
            conn.execute(StoragePool.__table__.insert(), [dict(id=identity,
                configuration_sha256=policy.configuration_sha256, free_floor_bytes=floor)
                for identity, floor in policy.free_floors.items()])
        conn.execute(StorageSchema.__table__.update().where(StorageSchema.id == 1).values(state="active"))
        with Session(bind=conn) as db:
            policy.verify(db, SimpleNamespace(root=policy.roots["imports"], attempt_root=policy.roots["attempts"]))
        return dict(inventory(conn), action="activate")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit existing database; no ambient fallback.")
    parser.add_argument("--profile", help="Explicit private JSON root/pool/floor profile; required with --apply.")
    parser.add_argument("--apply", action="store_true", help="Activate only a drained prepared store; never migrate or backfill.")
    parser.add_argument("--writers-stopped", action="store_true", help="With --apply, acknowledge coordinated shutdown of every writer.")
    args = parser.parse_args(argv)
    if args.apply != args.writers_stopped or args.apply != bool(args.profile):
        parser.error("--apply, --writers-stopped and --profile must be supplied together")
    engine = None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        from app.database import normalize_database_url
        from app.services.dataset_storage import PhysicalStorage
        policy = None
        if args.profile:
            with Path(args.profile).open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("profile_too_large")
            policy = PhysicalStorage(**json.loads(raw))
        url = make_url(normalize_database_url(args.database_url))
        if url.get_backend_name() not in ("sqlite", "postgresql"):
            raise ValueError("unsupported_storage_database")
        if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
            path = Path(url.database)
            if url.query or not path.is_file():
                raise ValueError("existing_sqlite_file_required")
            if not args.apply:
                url = url.set(database="file:" + quote(str(path.resolve()), safe="/"),
                              query={"mode": "ro", "uri": "true"})
        engine = create_engine(url)
        result = reconcile_storage(engine, policy=policy, apply=args.apply, writers_stopped=args.writers_stopped)
    except Exception:
        parser.exit(1, "Storage reconciliation refused; preserve work and inspect the maintenance procedure.\n")
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
