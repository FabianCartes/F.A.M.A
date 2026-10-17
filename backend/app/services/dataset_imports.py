"""Durable local-first imports; a journal reconciles database and filesystem.

HTTP handles receipt and bounded reads; durable execution owns publication.
Confirmed files are outside legacy discovery. Only DB membership is visible.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import unicodedata
import shutil
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import object_session
from app.models.dataset_import import DatasetImport, ImportedDataset
from app.models.dataset_import_metadata import (
    DatasetMember, DatasetSummary, ImportClass, ImportFile, ImportIssue, ImportSummary,
)
from app.services.dataset_import_records import (
    page, public_file, required_summary,
)
from app.services.dataset_zip import ImportLimits


def reject(code, message):
    raise HTTPException(code, message)


def digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical_path(value):
    return unicodedata.normalize("NFC", value).casefold()


def _durable_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class DatasetImports:
    def __init__(self, root, *, limits=None):
        self.root = Path(root)
        self.limits = limits or ImportLimits.from_environment()

    def _initialize(self):
        if not self.root.is_absolute() or self.root != self.root.resolve():
            reject(503, "El almacenamiento de importaciones no es una ruta física válida.")
        for parent in (self.root, *self.root.parents):
            if parent.is_symlink():
                reject(503, "El almacenamiento de importaciones no admite enlaces.")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ("staging", "objects"):
            path = self.root / name
            if path.is_symlink():
                reject(503, "Almacenamiento no válido.")
            path.mkdir(mode=0o700, exist_ok=True)
        # mkdir(parents=True) may have introduced any ancestor. Re-sync the
        # entire physical chain on every attempt, including recovery after a
        # prior failed fsync; existence alone is not durability evidence.
        for directory in (self.root, *self.root.parents):
            _durable_directory(directory)

    @contextmanager
    def mutation(self, db, key=None):
        self._initialize()
        lock_name = "mutation.lock" if key is None else "import-" + hashlib.sha256(key.encode()).hexdigest() + ".lock"
        fd = os.open(self.root / lock_name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                reject(409, "Hay otra importación en curso. Reintenta después.")
            db.expire_all()
            # Refuse a partially prepared store before cleanup or any new write.
            missing_job = db.query(DatasetImport.id).outerjoin(ImportSummary,
                ImportSummary.import_id == DatasetImport.id).filter(ImportSummary.import_id.is_(None)).first()
            missing_dataset = db.query(ImportedDataset.id).outerjoin(DatasetSummary,
                DatasetSummary.dataset_id == ImportedDataset.id).filter(DatasetSummary.dataset_id.is_(None)).first()
            if missing_job or missing_dataset:
                reject(503, "Los metadatos requieren migración verificada antes de continuar.")
            yield
        except BaseException:
            db.rollback()
            raise
        finally:
            os.close(fd)

    def cleanup(self, db, *, attempt_root=None):
        """Explicit maintenance only; never invoked as an HTTP side effect.

        Acquire the same import lock as receipt, then the queue gate, never the
        reverse. Busy receipt is skipped without expiration. Retain every active
        job (including expired leases) and every publication journal. Commit
        terminal cancellation before deletion while keeping the import lock.
        Persisted cleanup intent distinguishes promise release from reclamation.
        """
        from app.services.dataset_import_cleanup import run
        return run(self, db, attempt_root=attempt_root or getattr(self, "attempt_root", None))

    def job(self, db, owner, job_id):
        row = db.query(DatasetImport).filter_by(id=job_id, owner_id=owner).first()
        if row is None:
            reject(404, "Importación no encontrada.")
        required_summary(db, ImportSummary, row.id)
        return row

    def require_idle(self, db, import_id):
        """Protect source mutation against already admitted/recoverable work."""
        from app.models.dataset_import_job import ImportJob
        from app.services.dataset_import_jobs import ACTIVE, _gate
        _gate(db)
        from app.services.dataset_import_cleanup import require_available
        require_available(db, import_id)
        if db.query(ImportJob.id).filter(ImportJob.import_id == import_id, ImportJob.status.in_(ACTIVE)).first():
            reject(409, "La importación tiene un trabajo activo. Consulta su estado antes de modificarla.")

    def dataset(self, db, owner, dataset_id):
        row = db.query(ImportedDataset).filter_by(id=dataset_id, owner_id=owner).first()
        if row is None:
            reject(404, "Dataset no encontrado o no autorizado.")
        required_summary(db, DatasetSummary, row.id)
        return row

    def view(self, row):
        db = object_session(row)
        summary = required_summary(db, ImportSummary, row.id)
        preview = dict(summary.preview, file_count=summary.file_count, class_count=summary.class_count,
                       error_count=summary.error_count, warning_count=summary.warning_count,
                       total_size_bytes=summary.total_size_bytes)
        preview.pop("staging_attempt", None)
        preview.pop("_cleanup", None)
        preview.pop("_activity_at", None)
        execution_id = preview.pop("execution_id", None)
        execution = None
        if execution_id:
            from app.models.dataset_import_job import ImportJob
            from app.services.dataset_import_jobs import _snapshot, public_job
            job = db.get(ImportJob, execution_id)
            if job and job.import_id == row.id and job.owner_id == row.owner_id:
                execution = public_job(_snapshot(job))
        preview["synced_count"] = db.query(func.count(func.distinct(ImportFile.sha256))).filter(
            ImportFile.import_id == row.id, ImportFile.sync_status == "synced").scalar()
        return {"id": row.id, "status": row.status, "sync_status": row.sync_status,
                "dataset_id": row.dataset_id, "added_count": row.added_count,
                "preview_token": row.preview_token, "preview": preview,
                "error": row.error, "execution": execution,
                "details": {name: f"/api/ingestion/imports/{row.id}/{name}" for name in ("files", "classes", "issues")},
                "issue_sample": [dict(path=issue.path, code=issue.code, severity=issue.severity, action=issue.action)
                    for issue in db.query(ImportIssue).filter_by(import_id=row.id).order_by(ImportIssue.id).limit(5)]}

    def create(self, db, owner, payload):
        with self.mutation(db):
            prior = db.query(DatasetImport).filter_by(owner_id=owner, request_key=payload["request_key"]).first()
            if prior:
                if prior.request != payload:
                    reject(409, "La solicitud ya existe con otro destino o contenido.")
                return self.view(prior)
            if payload.get("target_id"):
                self.dataset(db, owner, payload["target_id"])
            active_count = db.query(DatasetImport).filter(DatasetImport.status.in_(
                ["receiving", "validating", "needs_correction", "ready", "committing"])).count()
            if active_count >= self.limits.concurrent_imports:
                reject(429, "Se alcanzó el límite de importaciones activas. Finaliza o cancela una solicitud.")
            row = DatasetImport(id=uuid.uuid4().hex, owner_id=owner, request_key=payload["request_key"],
                                request=payload, status="receiving", created_at=time.time(),
                                preview={}, added_count=0, sync_status="pending")
            db.add(row)
            db.flush()
            db.add(ImportSummary(import_id=row.id, preview={}, file_count=0, class_count=0,
                                 error_count=0, warning_count=0, total_size_bytes=0))
            db.commit()
            return self.view(row)

    def space(self):
        if shutil.disk_usage(self.root).free < self.limits.free_bytes:
            reject(507, "Espacio disponible insuficiente. Libera espacio o consulta al administrador.")

    def stage(self, row):
        return self.root / "staging" / row.id

    def list_datasets(self, db, owner, **pagination):
        def serialize(dataset):
            summary = required_summary(db, DatasetSummary, dataset.id)
            return dict(id=dataset.id, name=dataset.name, description=dataset.description,
                        revision=dataset.revision, file_count=summary.file_count,
                        class_count=summary.class_count, total_size_bytes=summary.total_size_bytes)
        return page(db.query(ImportedDataset).filter_by(owner_id=owner), ImportedDataset.id,
                    scope=f"datasets:{owner}", snapshot="catalog", key="datasets", serialize=serialize, **pagination)

    def list_jobs(self, db, owner, **pagination):
        return page(db.query(DatasetImport).filter_by(owner_id=owner), DatasetImport.id,
                    scope=f"imports:{owner}", snapshot="history", key="imports", serialize=self.view, **pagination)

    def review_page(self, db, owner, job_id, collection, **pagination):
        row = self.job(db, owner, job_id)
        model, column, serialize = {
            "files": (ImportFile, ImportFile.ordinal, public_file),
            "classes": (ImportClass, ImportClass.ordinal, lambda r: r.class_name),
            "issues": (ImportIssue, ImportIssue.id, lambda r: dict(id=r.id, severity=r.severity,
                path=r.path, code=r.code, action=r.action)),
        }[collection]
        snapshot = row.preview_token
        result = page(db.query(model).filter_by(import_id=row.id), column, scope=f"{row.id}:{collection}",
                      snapshot=snapshot, key=collection, serialize=serialize, **pagination)
        db.refresh(row)
        if row.preview_token != snapshot:
            reject(409, "La vista previa cambió. Consulta de nuevo la primera página.")
        return result

    def dataset_page(self, db, owner, dataset_id, **pagination):
        dataset = self.dataset(db, owner, dataset_id)
        return page(db.query(DatasetMember).filter(DatasetMember.dataset_id == dataset.id,
                    DatasetMember.dataset_revision <= dataset.revision), DatasetMember.id,
                    scope=f"{dataset.id}:files", snapshot=dataset.revision, key="files", serialize=public_file, **pagination)

    def download(self, db, owner, dataset_id, sha256):
        dataset = self.dataset(db, owner, dataset_id)
        file = db.query(DatasetMember).filter_by(dataset_id=dataset.id, sha256=sha256).first()
        if file is None:
            reject(404, "Audio no encontrado.")
        path = self.root / "objects" / file.source_import_id / file.stored_name
        if path.is_symlink() or not path.is_file() or digest_file(path) != sha256:
            reject(409, "Integridad local incorrecta. Solicita recuperación.")
        return path

    def cancel(self, db, owner, job_id):
        with self.mutation(db, job_id):
            row = self.job(db, owner, job_id)
            self.require_idle(db, job_id)
            if row.status in ("imported", "committing"):
                reject(409, "No se puede cancelar una importación confirmada o en recuperación.")
            row.status = "cancelled"
            from app.services.dataset_import_cleanup import request
            request(db, job_id)
            db.commit()
            from app.services.dataset_import_receipts import release_receipt
            release_receipt(db, job_id)
            return self.view(row)
