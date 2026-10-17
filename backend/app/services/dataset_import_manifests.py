"""Recoverable full-revision sync. Transfers never hold database sessions or gates."""
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import PurePosixPath

from fastapi import HTTPException
from sqlalchemy import func, insert, literal, select

from app.models.dataset_import_metadata import DatasetMember, DatasetSummary, ImportFile
from app.models.dataset_import_revision import DatasetRevision, RevisionObject
from app.services.dataset_import_records import dataset_quota, identifier
from app.services.dataset_import_storage import IntegrityConflict, TransientSyncError
from app.services.dataset_imports import digest_file


@dataclass(frozen=True)
class SyncLimits:
    # Concurrency is intentionally one: bounded I/O without abandoned futures.
    files: int = 32
    bytes: int = 256 * 1024**2

    def __post_init__(self):
        if type(self.files) is not int or not 1 <= self.files <= 200:
            raise ValueError("Sync batch count must be in [1, 200]")
        if type(self.bytes) is not int or not 1 <= self.bytes <= 15 * 1024**3:
            raise ValueError("Sync batch bytes must be in [1, 15 GiB]")

    @classmethod
    def from_environment(cls):
        return cls(int(os.environ.get("FAMA_IMPORT_SYNC_BATCH_FILES", "32")),
                   int(os.environ.get("FAMA_IMPORT_SYNC_BATCH_BYTES", str(256 * 1024**2))))


def _retry(call, *args):
    for retry in range(3):
        try:
            return call(*args)
        except TransientSyncError:
            if retry == 2:
                raise
            time.sleep(0.05 * 2**retry)


def _generation(value):
    if not isinstance(value, str) or not value or len(value) > 100 or not value.isascii() or not value.isprintable():
        raise IntegrityConflict("Invalid object generation")
    return value


def _freeze(execution, attempt):
    with execution.queue.publication(attempt) as (db, job):
        source = execution._source(db, attempt)
        if source.status != "imported" or not source.dataset_id:
            raise HTTPException(409, "Confirma una importación con contenido antes de sincronizar.")
        dataset = execution.service.dataset(db, source.owner_id, source.dataset_id)
        if job.expected_revision is None:
            job.expected_revision = dataset.revision
        revision = db.query(DatasetRevision).filter_by(dataset_id=dataset.id, revision=job.expected_revision).first()
        if revision is None:
            if dataset.revision != job.expected_revision:
                raise IntegrityConflict("Bound revision is unavailable")
            dataset_quota(db, dataset, 0, 0, execution.service.limits)
            summary = db.get(DatasetSummary, dataset.id)
            revision = DatasetRevision(id=identifier(), dataset_id=dataset.id, revision=dataset.revision,
                owner_id=source.owner_id, name=dataset.name, description=dataset.description,
                file_count=summary.file_count, total_size_bytes=summary.total_size_bytes)
            db.add(revision)
            db.flush()
            fields = ("source_import_id", "stored_name", "class_name", "original_path", "relative_path", "sha256", "size_bytes")
            # One INSERT SELECT freezes membership atomically without a Python
            # collection of all members, under the same gate as confirmation.
            key_prefix = f"private-imports/{source.owner_id}/{dataset.id}/"
            db.execute(insert(RevisionObject).from_select(
                ["revision_id", "member_id", *fields, "object_key", "object_generation"],
                select(literal(revision.id), DatasetMember.id,
                       *(getattr(DatasetMember, name) for name in fields),
                       literal(key_prefix) + DatasetMember.sha256 + literal(".wav"), DatasetMember.object_generation
                ).where(DatasetMember.dataset_id == dataset.id)))
        if revision.owner_id != source.owner_id:
            raise IntegrityConflict("Revision owner mismatch")
        source.sync_status, source.error = "running", None
        return revision.id


def _batch(sessions, revision_id, cursor, limits):
    with sessions() as db:
        candidates = db.query(RevisionObject).filter(RevisionObject.revision_id == revision_id,
            RevisionObject.member_id > cursor).order_by(RevisionObject.member_id).limit(limits.files).all()
        result, size = [], 0
        for row in candidates:
            if row.size_bytes > limits.bytes:
                raise IntegrityConflict("Object exceeds configured sync batch byte limit")
            if result and size + row.size_bytes > limits.bytes:
                break
            result.append({column.name: getattr(row, column.name) for column in RevisionObject.__table__.columns})
            size += row.size_bytes
        return result


def _checkpoint(execution, attempt, revision_id, verified):
    with execution.queue.publication(attempt) as (db, job):
        execution._source(db, attempt)
        revision = db.get(DatasetRevision, revision_id)
        for item, generation in verified:
            row = db.get(RevisionObject, (revision_id, item["member_id"]))
            if row.object_generation is not None and row.object_generation != generation:
                raise IntegrityConflict("Previously verified generation changed")
            row.object_generation = generation
            row.verified_sha256, row.verified_size_bytes = row.sha256, row.size_bytes
            member = db.get(DatasetMember, row.member_id)
            if member is not None:
                member.sync_status, member.object_key, member.object_generation = "synced", row.object_key, generation
            db.query(ImportFile).filter_by(import_id=attempt["import_id"], sha256=row.sha256).update({"sync_status": "synced"})
        db.flush()
        count, size = db.query(func.count(RevisionObject.member_id),
            func.coalesce(func.sum(RevisionObject.size_bytes), 0)).filter_by(revision_id=revision_id).filter(
                RevisionObject.object_generation.is_not(None),
                RevisionObject.verified_sha256 == RevisionObject.sha256,
                RevisionObject.verified_size_bytes == RevisionObject.size_bytes).one()
        revision.verified_count, revision.verified_bytes = count, size
        job.progress = max(job.progress, min(99, count * 99 // max(1, revision.file_count)))


def _safe_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or any(p in ("", ".", "..") for p in value.split("/")):
        raise IntegrityConflict("Unsafe manifest path")
    return value


def _write_manifest(sessions, revision_id, path):
    with sessions() as db:
        row = db.get(DatasetRevision, revision_id)
        header = dict(schema_version=1, dataset_id=row.dataset_id, dataset_revision=row.revision,
                      name=row.name, description=row.description, file_count=row.file_count,
                      total_size_bytes=row.total_size_bytes)
    # Line-delimited entries inside a standard JSON array allow bounded readers.
    count = total = 0
    cursor = ""
    with path.open("wb") as stream:
        stream.write(json.dumps(header, ensure_ascii=True, sort_keys=True).encode()[:-1] + b', "files": [\n')
        while True:
            batch = _batch(sessions, revision_id, cursor, SyncLimits(bytes=15 * 1024**3))
            if not batch:
                break
            for item in batch:
                if (not item["object_generation"] or item["verified_sha256"] != item["sha256"]
                        or item["verified_size_bytes"] != item["size_bytes"]):
                    raise IntegrityConflict("Incomplete revision")
                entry = {name: item[name] for name in ("class_name", "original_path", "relative_path", "source_import_id",
                    "size_bytes", "sha256", "object_key", "object_generation")}
                _safe_path(entry["original_path"])
                _safe_path(entry["relative_path"])
                if count:
                    stream.write(b",\n")
                stream.write(json.dumps(entry, ensure_ascii=True, sort_keys=True).encode())
                count += 1
                total += item["size_bytes"]
            cursor = batch[-1]["member_id"]
        stream.write(b"\n]}\n")
    if count != header["file_count"] or total != header["total_size_bytes"]:
        raise IntegrityConflict("Manifest totals mismatch")
    return header, digest_file(path), path.stat().st_size


def synchronize(execution, attempt, staging):
    if execution.storage is None:
        raise RuntimeError("An explicit storage adapter is required for sync")
    limits = SyncLimits.from_environment()
    revision_id = _freeze(execution, attempt)
    cursor = ""
    while True:
        batch = _batch(execution.queue.sessions, revision_id, cursor, limits)
        if not batch:
            break
        verified = []
        try:
            for item in batch:
                path = execution.service.root / "objects" / item["source_import_id"] / item["stored_name"]
                if (path.is_symlink() or not path.is_file() or path.stat().st_size != item["size_bytes"]
                        or digest_file(path) != item["sha256"]):
                    raise IntegrityConflict("Local original-byte integrity mismatch")
                # Verify the fence immediately before starting each transfer;
                # a lost lease cannot checkpoint or publish the returned result.
                with execution.queue.publication(attempt):
                    pass
                generation = _generation(_retry(execution.storage.ensure, item["object_key"], path, item["sha256"],
                    {"owner_id": str(attempt["owner_id"]), "dataset_id": item["object_key"].split("/")[2],
                     "class_name": item["class_name"]}))
                if item["object_generation"] is not None and item["object_generation"] != generation:
                    raise IntegrityConflict("Previously verified generation changed")
                verified.append((item, generation))
        finally:
            if verified:
                _checkpoint(execution, attempt, revision_id, verified)
        cursor = batch[-1]["member_id"]
    path = staging / "manifest.json"
    header, digest, size = _write_manifest(execution.queue.sessions, revision_id, path)
    key = f"private-imports/{attempt['owner_id']}/{header['dataset_id']}/revisions/{header['dataset_revision']}/{digest}.json"
    with execution.queue.publication(attempt):
        pass
    generation = _generation(_retry(execution.storage.ensure_manifest, key, path, digest,
        {"owner_id": str(attempt["owner_id"]), "dataset_id": header["dataset_id"],
         "dataset_revision": str(header["dataset_revision"])}))
    with execution.queue.publication(attempt) as (db, job):
        source = execution._source(db, attempt)
        revision = db.get(DatasetRevision, revision_id)
        identity = (key, generation, digest, size)
        if revision.status == "complete" and identity != (revision.manifest_key,
                revision.manifest_generation, revision.manifest_sha256, revision.manifest_size_bytes):
            raise IntegrityConflict("Immutable manifest identity changed")
        revision.manifest_key, revision.manifest_generation, revision.manifest_sha256, revision.manifest_size_bytes = identity
        revision.status = "complete"
        # Success is explicitly revision-scoped; a concurrent new revision must
        # never inherit this old snapshot's completion.
        dataset = execution.service.dataset(db, source.owner_id, source.dataset_id)
        source.sync_status = "synced" if dataset.revision == revision.revision else "pending"
        from app.services.dataset_import_cleanup import request
        request(db, source.id)
        result = {"dataset_id": revision.dataset_id, "dataset_revision": revision.revision,
                  "synced_count": revision.file_count}
        execution.queue.complete_publication(db, job, result)
    return result


def authorized_reference(service, db, owner, dataset_id, revision):
    service.dataset(db, owner, dataset_id)
    row = db.query(DatasetRevision).filter_by(dataset_id=dataset_id, revision=revision, owner_id=owner).first()
    if row is None:
        raise HTTPException(404, "Revisión no encontrada.")
    return dict(dataset_id=row.dataset_id, dataset_revision=row.revision, status=row.status,
                file_count=row.file_count, total_size_bytes=row.total_size_bytes,
                verified_count=row.verified_count, verified_bytes=row.verified_bytes,
                manifest=(dict(object_key=row.manifest_key, object_generation=row.manifest_generation,
                               sha256=row.manifest_sha256, size_bytes=row.manifest_size_bytes)
                          if row.status == "complete" else None))
