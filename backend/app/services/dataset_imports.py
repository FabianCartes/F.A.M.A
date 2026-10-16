"""Durable local-first imports; a journal reconciles database and filesystem.

All mutations use the same nonblocking POSIX lock across API workers. Confirmed
files are outside legacy discovery. Only database-published membership is visible.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import time
import uuid

from fastapi import HTTPException
from app.models.dataset_import import DatasetImport, ImportedDataset
from app.services.dataset_zip import ImportLimits, validate_zip


def reject(code, message):
    raise HTTPException(code, message)


def digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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
    def mutation(self, db):
        self._initialize()
        fd = os.open(self.root / "mutation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                reject(409, "Hay otra importación en curso. Reintenta después.")
            db.expire_all()
            self._cleanup(db)
            yield
        except BaseException:
            db.rollback()
            raise
        finally:
            os.close(fd)

    def _cleanup(self, db):
        expired = db.query(DatasetImport).filter(
            DatasetImport.created_at < time.time() - self.limits.ttl_seconds,
            DatasetImport.status.in_(["receiving", "validating", "ready", "needs_correction", "failed", "cancelled"])
        ).all()
        for row in expired:
            row.status, row.error = "cancelled", "expired"
        if expired:
            db.commit()
        for row in expired:
            if self.stage(row).exists():
                shutil.rmtree(self.stage(row))
        # A committed import may retain its received archive or duplicate staging
        # bytes. These are temporary; its published objects are never cleaned.
        confirmed = db.query(DatasetImport).filter(
            DatasetImport.created_at < time.time() - self.limits.ttl_seconds,
            DatasetImport.status == "imported").all()
        for row in confirmed:
            if self.stage(row).exists():
                shutil.rmtree(self.stage(row))

    def job(self, db, owner, job_id):
        row = db.query(DatasetImport).filter_by(id=job_id, owner_id=owner).first()
        if row is None:
            reject(404, "Importación no encontrada.")
        return row

    def dataset(self, db, owner, dataset_id):
        row = db.query(ImportedDataset).filter_by(id=dataset_id, owner_id=owner).first()
        if row is None:
            reject(404, "Dataset no encontrado o no autorizado.")
        return row

    def view(self, row):
        return {"id": row.id, "status": row.status, "sync_status": row.sync_status,
                "dataset_id": row.dataset_id, "added_count": row.added_count,
                "preview_token": row.preview_token, "preview": row.preview,
                "error": row.error}

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
            db.commit()
            return self.view(row)

    def space(self):
        if shutil.disk_usage(self.root).free < self.limits.free_bytes:
            reject(507, "Espacio disponible insuficiente. Libera espacio o consulta al administrador.")

    def stage(self, row):
        return self.root / "staging" / row.id

    def preview(self, db, owner, job_id, root):
        with self.mutation(db):
            row = self.job(db, owner, job_id)
            if row.status not in ("validating", "needs_correction", "ready") or not row.archive_sha256:
                reject(409, "La importación no admite una nueva vista previa.")
            source = self.stage(row) / "archive.zip"
            if digest_file(source) != row.archive_sha256:
                reject(409, "El archivo recibido cambió. Crea una nueva importación.")
            row.status = "validating"
            db.commit()
            staging = self.stage(row) / "files"
            if staging.exists():
                shutil.rmtree(staging)
            result = validate_zip(source, staging, root=root, limits=self.limits)
            target = self.dataset(db, owner, row.request["target_id"]) if row.request.get("target_id") else None
            equivalent = next((previous for previous in db.query(DatasetImport).filter_by(owner_id=owner, status="imported").all()
                               if previous.dataset_id and previous.preview.get("fingerprint") == result["fingerprint"]), None)
            result["duplicate_collection"] = equivalent is not None
            if target is None and equivalent:
                target = self.dataset(db, owner, equivalent.dataset_id)
            result["resolved_target_id"] = target.id if target else None
            existing = {f["sha256"]: f for f in target.files} if target else {}
            for file in result["files"]:
                old = existing.get(file["sha256"])
                file["existing"] = old is not None
                if old and old["class_name"] != file["class_name"]:
                    result["errors"].append({"path": file["original_path"], "code": "label_conflict",
                        "action": "Corrige la clase: este contenido ya existe con otra etiqueta."})
            result["new_count"] = sum(not f["duplicate"] and not f["existing"] for f in result["files"])
            result["target_revision"] = target.revision if target else None
            result["root"] = root
            row.preview = result
            row.preview_token = uuid.uuid4().hex + uuid.uuid4().hex
            row.status = "needs_correction" if result["errors"] else "ready"
            db.commit()
            return self.view(row)

    def confirm(self, db, owner, job_id, token):
        with self.mutation(db):
            row = self.job(db, owner, job_id)
            if row.error == "expired":
                reject(410, "La importación venció. Crea una nueva solicitud.")
            if not row.preview_token or token != row.preview_token:
                reject(409, "La vista previa cambió. Revísala antes de confirmar.")
            if row.status == "imported":
                return self.view(row)
            if row.status not in ("ready", "committing"):
                reject(409, "La importación no está lista para confirmar.")
            target_id = row.preview.get("resolved_target_id")
            target = self.dataset(db, owner, target_id) if target_id else None
            if target and target.revision != row.preview["target_revision"]:
                reject(409, "El dataset cambió. Genera y revisa una nueva vista previa.")
            if target is None:
                equivalent = any(previous.dataset_id and previous.preview.get("fingerprint") == row.preview["fingerprint"]
                                 for previous in db.query(DatasetImport).filter_by(owner_id=owner, status="imported").all())
                if equivalent:
                    reject(409, "La colección ya fue importada. Genera y revisa una nueva vista previa.")
            pending = db.query(DatasetImport).filter_by(owner_id=owner, status="committing").all()
            for other in pending:
                same_target = target and other.dataset_id == target.id
                same_new_name = not target and not other.request.get("target_id") and other.request["name"] == row.request["name"]
                same_collection = other.preview.get("fingerprint") == row.preview["fingerprint"]
                if other.id != row.id and (same_target or same_new_name or same_collection):
                    reject(409, "Hay una confirmación pendiente de recuperación para este destino. Reinténtala primero.")
            selected = [dict(f, import_id=row.id) for f in row.preview["files"]
                        if not f["duplicate"] and not f["existing"]]
            if not selected:
                row.status, row.added_count = "imported", 0
                row.dataset_id = target.id if target else None
                db.commit()
                return self.view(row)
            if target is None:
                # No empty catalog row is committed before files are durable.
                collision = db.query(ImportedDataset).filter_by(owner_id=owner, name=row.request["name"]).first()
                if collision:
                    reject(409, "Ya existe un dataset con ese nombre. Selecciónalo como destino en otra solicitud.")
            row.status = "committing"
            row.dataset_id = target.id if target else row.dataset_id or uuid.uuid4().hex
            db.commit()  # Recovery journal precedes the filesystem publication.
            stage = self.stage(row) / "files"
            destination = self.root / "objects" / row.id
            location = destination if destination.exists() else stage
            for file in selected:
                path = location / file["stored_name"]
                if not path.is_file() or path.is_symlink() or digest_file(path) != file["sha256"]:
                    reject(409, "La copia local no coincide. Conserva el estado y solicita recuperación.")
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            if not destination.exists():
                _durable_directory(stage)
                os.rename(stage, destination)
            # Replay must re-establish durability even if the rename completed
            # before a directory fsync failed in the previous attempt.
            _durable_directory(destination)
            _durable_directory(destination.parent)
            _durable_directory(stage.parent)
            if target is None:
                target = ImportedDataset(id=row.dataset_id, owner_id=owner, name=row.request["name"],
                                         description=row.request["description"], files=[], revision=0)
                db.add(target)
            target.files = list(target.files) + selected
            target.revision += 1
            row.added_count = len(selected)
            row.status = "imported"
            db.commit()  # Membership, counters and terminal result publish together.
            return self.view(row)

    def list_datasets(self, db, owner):
        return [{"id": d.id, "name": d.name, "description": d.description, "revision": d.revision,
                 "file_count": len(d.files), "classes": sorted({f["class_name"] for f in d.files}),
                 "total_size_bytes": sum(f["size_bytes"] for f in d.files)}
                for d in db.query(ImportedDataset).filter_by(owner_id=owner).all()]

    def download(self, db, owner, dataset_id, sha256):
        dataset = self.dataset(db, owner, dataset_id)
        file = next((f for f in dataset.files if f["sha256"] == sha256), None)
        if file is None:
            reject(404, "Audio no encontrado.")
        path = self.root / "objects" / file["import_id"] / file["stored_name"]
        if path.is_symlink() or not path.is_file() or digest_file(path) != sha256:
            reject(409, "Integridad local incorrecta. Solicita recuperación.")
        return path

    def cancel(self, db, owner, job_id):
        with self.mutation(db):
            row = self.job(db, owner, job_id)
            if row.status in ("imported", "committing"):
                reject(409, "No se puede cancelar una importación confirmada o en recuperación.")
            row.status = "cancelled"
            db.commit()
            if self.stage(row).exists():
                shutil.rmtree(self.stage(row))
            return self.view(row)

    def sync(self, db, owner, job_id, storage):
        from app.services.dataset_import_storage import TransientSyncError
        with self.mutation(db):
            row = self.job(db, owner, job_id)
            if row.status != "imported" or not row.dataset_id:
                reject(409, "Confirma una importación con contenido antes de sincronizar.")
            dataset = self.dataset(db, owner, row.dataset_id)
            wanted = {f["sha256"] for f in row.preview["files"]}
            members = [f for f in dataset.files if f["sha256"] in wanted]
            preview = dict(row.preview)
            cursor = preview.get("sync_cursor", 0) if row.sync_status in ("running", "error") else 0
            progress = dict(preview.get("sync_files", {}))
            row.sync_status, row.error = "running", None
            db.commit()
            deadline = time.monotonic() + self.limits.validation_seconds
            for index in range(cursor, len(members)):
                file = members[index]
                key = f"private-imports/{owner}/{dataset.id}/{file['sha256']}.wav"
                try:
                    path = self.download(db, owner, dataset.id, file["sha256"])
                    metadata = {"owner_id": str(owner), "dataset_id": dataset.id,
                                "class_name": file["class_name"]}
                    for attempt in range(3):
                        try:
                            storage.ensure(key, path, file["sha256"], metadata)
                            break
                        except TransientSyncError:
                            if attempt == 2:
                                raise
                            time.sleep(0.05 * 2**attempt)
                    progress[file["sha256"]] = "synced"
                    cursor = index + 1
                except Exception:
                    # Storage exceptions may contain credentials, paths or object names.
                    progress[file["sha256"]] = "error"
                    row.sync_status, row.error = "error", "sync_failed_or_integrity_conflict"
                preview.update(sync_files=progress, sync_cursor=cursor)
                row.preview = dict(preview)
                db.commit()  # Each verified object survives process interruption.
                if row.sync_status == "error" or time.monotonic() >= deadline:
                    return self.view(row)
            row.sync_status = "synced"
            db.commit()
            return self.view(row)
