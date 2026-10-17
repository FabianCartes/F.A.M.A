"""Durable cleanup intent, serialized with admission and recoverable after exit.

The database state blocks new work; the per-import flock owns deletion until
process exit. No lease can authorize a second cleaner while the first still
holds that lock. Only staging is removable, never published objects.
"""
import re
import os
import fcntl
from contextlib import ExitStack
import shutil
import time

from fastapi import HTTPException

from app.models.dataset_import import DatasetImport
from app.models.dataset_import_job import ImportJob
from app.models.dataset_import_metadata import ImportSummary
from app.services.dataset_import_jobs import ACTIVE, _gate


KEY = "_cleanup"


def state(db, identity):
    summary = db.get(ImportSummary, identity)
    return dict(summary.preview.get(KEY, {})) if summary else {}


def request(db, identity):
    """Caller owns the queue gate; intent commits with cancellation/publication."""
    summary = db.get(ImportSummary, identity)
    current = state(db, identity)
    if current.get("state") != "deleting":
        summary.preview = dict(summary.preview, **{KEY: {"state": "pending"}})


def require_available(db, identity):
    from app.services.dataset_imports import reject
    if state(db, identity).get("state") == "deleting":
        reject(409, "La limpieza está en curso. Conserva el estado y reintenta después.")


def run(service, db, *, attempt_root):
    from app.services.dataset_imports import _durable_directory
    from app.services.dataset_import_worker import _private_root
    from app.services.dataset_import_chunks import protects_cleanup
    from app.services.dataset_import_receipts import release_receipt

    # Validate the operator-owned root before claiming or changing any state.
    root = _private_root(attempt_root) if attempt_root is not None else None
    candidates = [identity for (identity,) in db.query(DatasetImport.id)]
    db.rollback()
    outcomes = {"completed": 0, "failed": 0}
    for identity in candidates:
        try:
            with service.mutation(db, identity), ExitStack() as locks:
                _gate(db)
                source = db.get(DatasetImport, identity)
                summary = db.get(ImportSummary, identity)
                current = state(db, identity)
                active = db.query(ImportJob.id).filter(ImportJob.import_id == identity,
                    ImportJob.status.in_(ACTIVE)).first()
                # Expired execution is still recoverable work, not garbage.
                if active or source.status == "committing":
                    db.rollback()
                    continue
                cutoff = time.time() - service.limits.ttl_seconds
                terminal = source.status in ("imported", "cancelled")
                useful = max(source.created_at, summary.preview.get("_activity_at", 0))
                if not terminal and (useful >= cutoff or protects_cleanup(service, db, source, cutoff)):
                    db.rollback()
                    continue
                if root is None and summary.preview.get("staging_attempt"):
                    # Without the stable attempt root, reclamation is unproven.
                    db.rollback()
                    continue
                jobs = [job_id for (job_id,) in db.query(ImportJob.id).filter_by(import_id=identity)]
                paths = [service.stage(source)]
                if root is not None:
                    for job_id in jobs:
                        for path in root.glob(job_id + "-*"):
                            if re.fullmatch(re.escape(job_id) + r"-[1-9][0-9]*-[1-9][0-9]*", path.name):
                                paths.append(path)
                if current.get("state") == "done" and not any(path.exists() or path.is_symlink() for path in paths):
                    db.rollback()
                    continue
                for path in paths:
                    if not path.exists() or path.is_symlink():
                        continue
                    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    locks.callback(os.close, fd)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        from app.services.dataset_imports import reject
                        reject(409, "Un intento todavía está finalizando; reintenta la limpieza después.")
                if not terminal:
                    source.status, source.error = "cancelled", "expired"
                summary.preview = dict(summary.preview, **{KEY: {"state": "deleting"}})
                db.commit()  # Durable fence; no DB lock spans recursive deletion.
                try:
                    for path in paths:
                        if path.is_symlink():
                            raise OSError("Staging link refused")
                        if path.exists():
                            shutil.rmtree(path)
                        if path.parent.exists():
                            _durable_directory(path.parent)
                    # A retry may discover no children after the last rmtree
                    # succeeded but its parent fsync failed. The stable root
                    # remains a durability obligation independent of discovery.
                    if root is not None:
                        _durable_directory(root)
                    _gate(db)
                    summary = db.get(ImportSummary, identity)
                    summary.preview = dict(summary.preview, **{KEY: {"state": "done"}})
                    release_receipt(db, identity)
                    db.commit()
                    outcomes["completed"] += 1
                except OSError:
                    db.rollback()
                    _gate(db)
                    summary = db.get(ImportSummary, identity)
                    summary.preview = dict(summary.preview, **{KEY: {
                        "state": "deleting", "error": "cleanup_failed"}})
                    db.commit()
                    outcomes["failed"] += 1
        except HTTPException as error:
            if error.status_code != 409:
                raise
    return outcomes
