"""Durable import execution: expensive preparation, then short fenced publication."""
from pathlib import Path, PurePosixPath
import os
import time
import uuid

from sqlalchemy import func, select

from app.models.dataset_import import DatasetImport, ImportedDataset
from app.models.dataset_import_metadata import (
    DatasetMember, DatasetSummary, ImportFile, ImportSummary,
)
from app.services.dataset_import_jobs import LeaseLost
from app.services.dataset_import_records import dataset_quota, identifier, quota_issues, replace_preview, required_summary
from app.services.dataset_import_worker import ImportJobWorker
from app.services.dataset_imports import _canonical_path, _durable_directory, digest_file, reject
from app.services.dataset_zip_sandbox import validate_zip


class ImportExecution:
    """One public worker operation with an injected durable queue and storage.

    Preparation uses attempt-private files and no publication transaction. The
    database gate is acquired only for journal/metadata/rename transitions, in
    the same order as admission and reclaim. Queued jobs, not HTTP, dispatch work.
    """

    def __init__(self, queue, service, staging_root, *, storage=None, **worker_options):
        self.queue, self.service, self.root, self.storage = queue, service, Path(staging_root), storage
        self.worker = ImportJobWorker(queue, self.root, self.execute, **worker_options)

    def run_once(self):
        return self.worker.run_once()

    def _source(self, db, attempt):
        return self.service.job(db, attempt["owner_id"], attempt["import_id"])

    def execute(self, attempt, staging, report):
        self.service._initialize()
        # Owner is loaded from authoritative state, never from client parameters.
        from app.models.dataset_import_job import ImportJob
        with self.queue.sessions() as db:
            persisted = db.get(ImportJob, attempt["id"])
            attempt = dict(attempt, owner_id=persisted.owner_id)
        report(stage={"preview": "validating", "confirm": "verifying", "sync": "syncing"}[attempt["kind"]], progress=1)
        try:
            return {"preview": self.preview, "confirm": self.confirm, "sync": self.sync}[attempt["kind"]](attempt, staging)
        except LeaseLost:
            raise
        except Exception:
            if attempt["kind"] == "sync":
                with self.queue.publication(attempt) as (db, _):
                    source = self._source(db, attempt)
                    source.sync_status, source.error = "error", "sync_failed_or_integrity_conflict"
            raise

    def preview(self, attempt, staging):
        with self.queue.sessions() as db:
            source = self._source(db, attempt)
            if source.status not in ("validating", "needs_correction", "ready"):
                reject(409, "La importación no admite una nueva vista previa.")
            archive = self.service.stage(source) / "archive.zip"
            expected = source.archive_sha256
        if digest_file(archive) != expected:
            reject(409, "El archivo recibido cambió. Crea una nueva importación.")
        root = attempt["parameters"]["root"]
        result = validate_zip(archive, staging / "files", root=root, limits=self.service.limits)
        for file in result["files"]:
            path = staging / "files" / file["stored_name"]
            if path.is_file():
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
        for path in (staging / "files", staging, self.root):
            if path.exists():
                _durable_directory(path)
        with self.queue.publication(attempt) as (db, job):
            source = self._source(db, attempt)
            if source.archive_sha256 != expected or source.status not in ("validating", "needs_correction", "ready"):
                reject(409, "La importación cambió durante la validación.")
            target_id = source.request.get("target_id")
            target = self.service.dataset(db, source.owner_id, target_id) if target_id else None
            equivalent = db.query(DatasetImport).join(ImportSummary, ImportSummary.import_id == DatasetImport.id).filter(
                DatasetImport.owner_id == source.owner_id, DatasetImport.status == "imported",
                DatasetImport.dataset_id.is_not(None), ImportSummary.fingerprint == result["fingerprint"]).first()
            result["duplicate_collection"] = equivalent is not None
            if target is None and equivalent:
                target = self.service.dataset(db, source.owner_id, equivalent.dataset_id)
            occupied = {_canonical_path(path) for (path,) in db.query(DatasetMember.relative_path).filter_by(
                dataset_id=target.id)} if target else set()
            for file in result["files"]:
                old = db.query(DatasetMember).filter_by(dataset_id=target.id, sha256=file["sha256"]).first() if target else None
                file["existing"] = old is not None
                if old and old.class_name != file["class_name"]:
                    result["errors"].append({"path": file["original_path"], "code": "label_conflict",
                        "action": "Corrige la clase: este contenido ya existe con otra etiqueta."})
                relative = file["original_path"][len(root) + 1:] if root else file["original_path"]
                if old:
                    relative = old.relative_path
                elif not file["duplicate"]:
                    original, suffix = PurePosixPath(relative), 0
                    while _canonical_path(relative) in occupied:
                        suffix += 1
                        relative = str(original.with_name(f"{original.stem}-{file['sha256']}-{suffix}{original.suffix}"))
                    occupied.add(_canonical_path(relative))
                file["relative_path"] = relative
            result.update(new_count=sum(not f["duplicate"] and not f["existing"] for f in result["files"]),
                          resolved_target_id=target.id if target else None,
                          target_revision=target.revision if target else None, root=root,
                          staging_attempt=staging.name, execution_id=job.id)
            added = [f for f in result["files"] if not f["duplicate"] and not f["existing"]]
            result["quota"] = dataset_quota(db, target, sum(f["size_bytes"] for f in added),
                                            len(added), self.service.limits)
            result["errors"].extend(quota_issues(result["quota"]))
            replace_preview(db, source, result)
            source.preview_token = uuid.uuid4().hex + uuid.uuid4().hex
            source.status = "needs_correction" if result["errors"] else "ready"
            self.queue.complete_publication(db, job, {})
        return {}

    def _confirmation(self, db, attempt):
        source = self._source(db, attempt)
        if source.preview_token != attempt["parameters"]["preview_token"]:
            reject(409, "La vista previa cambió. Revísala antes de confirmar.")
        if source.status not in ("ready", "committing", "imported"):
            reject(409, "La importación no está lista para confirmar.")
        summary = required_summary(db, ImportSummary, source.id)
        preview = summary.preview
        target_id = preview.get("resolved_target_id")
        target = self.service.dataset(db, source.owner_id, target_id) if target_id else None
        if source.status != "imported" and target and target.revision != preview["target_revision"]:
            reject(409, "El dataset cambió. Genera y revisa una nueva vista previa.")
        if source.status != "imported":
            selected = db.query(ImportFile).filter_by(import_id=source.id, duplicate=False, existing=False)
            new_files, new_bytes = selected.with_entities(func.count(ImportFile.id),
                func.coalesce(func.sum(ImportFile.size_bytes), 0)).one()
            count, total = db.query(func.count(ImportFile.id),
                func.coalesce(func.sum(ImportFile.size_bytes), 0)).filter_by(import_id=source.id).one()
            if (count != summary.file_count or total != summary.total_size_bytes
                    or new_files != preview.get("new_count") or new_bytes < 0):
                reject(503, "Los metadatos requieren migración verificada antes de continuar.")
            issues = quota_issues(dataset_quota(db, target, new_bytes, new_files, self.service.limits))
            if issues:
                reject(409, issues[0]["code"])
            for other in db.query(DatasetImport).filter_by(owner_id=source.owner_id, status="committing"):
                if other.id != source.id and (target and other.dataset_id == target.id or
                        not target and other.request["name"] == source.request["name"] or
                        required_summary(db, ImportSummary, other.id).fingerprint == summary.fingerprint):
                    reject(409, "Hay una confirmación pendiente de recuperación para este destino. Reinténtala primero.")
            if not target:
                collision = db.query(ImportedDataset).filter_by(owner_id=source.owner_id, name=source.request["name"]).first()
                equivalent = db.query(DatasetImport).join(ImportSummary, ImportSummary.import_id == DatasetImport.id).filter(
                    DatasetImport.owner_id == source.owner_id, DatasetImport.status == "imported",
                    ImportSummary.fingerprint == summary.fingerprint).first()
                if collision or equivalent:
                    reject(409, "El destino cambió. Genera y revisa una nueva vista previa.")
        return source, target, preview

    def confirm(self, attempt, staging):
        from app.services.dataset_import_receipts import release_published_receipt
        # Commit the journal before any filesystem publication. A replacement
        # reuses this journal and verifies the immutable destination after crash.
        with self.queue.publication(attempt) as (db, job):
            source, target, preview = self._confirmation(db, attempt)
            if source.status == "imported":
                release_published_receipt(db, source)
                result = {"added_count": source.added_count}
                if source.dataset_id:
                    result["dataset_id"] = source.dataset_id
                self.queue.complete_publication(db, job, result)
                return result
            source.status = "committing"
            source.dataset_id = target.id if target else source.dataset_id or uuid.uuid4().hex
            source_id = source.id
            attempt_name = preview.get("staging_attempt")
            files = [(f.stored_name, f.sha256) for f in db.query(ImportFile).filter_by(
                import_id=source.id, duplicate=False, existing=False).order_by(ImportFile.ordinal)]
        # Legacy ready previews retain their original files; new previews always
        # refer to a server-generated attempt identity, never a client path.
        if attempt_name and (Path(attempt_name).name != attempt_name or attempt_name in (".", "..") or "/" in attempt_name):
            reject(409, "El staging requiere recuperación.")
        prepared = self.root / attempt_name / "files" if attempt_name else self.service.root / "staging" / source_id / "files"
        destination = self.service.root / "objects" / source_id
        location = destination if destination.exists() else prepared
        for name, digest in files:
            path = location / name
            if not path.is_file() or path.is_symlink() or digest_file(path) != digest:
                reject(409, "La copia local no coincide. Conserva el estado y solicita recuperación.")
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
        if files:
            _durable_directory(location)
        with self.queue.publication(attempt) as (db, job):
            source, target, _ = self._confirmation(db, attempt)
            if files:
                if not destination.exists():
                    os.rename(prepared, destination)
                _durable_directory(destination)
                _durable_directory(destination.parent)
                _durable_directory(prepared.parent)
            if target is None and files:
                target = ImportedDataset(id=source.dataset_id, owner_id=source.owner_id,
                    name=source.request["name"], description=source.request["description"], files=[], revision=0)
                db.add(target)
                db.flush()
                db.add(DatasetSummary(dataset_id=target.id, revision=0, file_count=0, class_count=0, total_size_bytes=0))
                db.flush()
            selected = db.query(ImportFile).filter_by(import_id=source.id, duplicate=False, existing=False)
            if files:
                target.revision += 1
                total = 0
                for file in selected.order_by(ImportFile.ordinal):
                    fields = {c.name: getattr(file, c.name) for c in DatasetMember.__table__.columns
                              if c.name not in ("id", "dataset_id", "dataset_revision")}
                    db.add(DatasetMember(id=identifier(), dataset_id=target.id, dataset_revision=target.revision, **fields))
                    total += file.size_bytes
                db.flush()
                counts = required_summary(db, DatasetSummary, target.id)
                counts.revision, counts.file_count = target.revision, counts.file_count + len(files)
                counts.total_size_bytes += total
                counts.class_count = db.query(func.count(func.distinct(DatasetMember.class_name))).filter_by(dataset_id=target.id).scalar()
            source.status, source.added_count = "imported", len(files)
            source.dataset_id = target.id if target else None
            release_published_receipt(db, source)
            result = {"added_count": len(files)}
            if source.dataset_id:
                result["dataset_id"] = source.dataset_id
            self.queue.complete_publication(db, job, result)
        return result

    def sync(self, attempt, staging):
        from app.services.dataset_import_storage import TransientSyncError
        if self.storage is None:
            raise RuntimeError("An explicit storage adapter is required for sync")
        with self.queue.publication(attempt) as (db, _):
            source = self._source(db, attempt)
            if source.status != "imported" or not source.dataset_id:
                reject(409, "Confirma una importación con contenido antes de sincronizar.")
            source.sync_status, source.error = "running", None
            dataset_id, owner = source.dataset_id, source.owner_id
        cursor = ""
        while True:
            with self.queue.sessions() as db:
                wanted = select(ImportFile.sha256).where(ImportFile.import_id == attempt["import_id"])
                file = db.query(DatasetMember).filter(DatasetMember.dataset_id == dataset_id,
                    DatasetMember.sha256.in_(wanted), DatasetMember.id > cursor).order_by(DatasetMember.id).first()
                if file is None:
                    break
                identity, digest, origin, name, label = file.id, file.sha256, file.source_import_id, file.stored_name, file.class_name
            path = self.service.root / "objects" / origin / name
            if path.is_symlink() or not path.is_file() or digest_file(path) != digest:
                reject(409, "Integridad local incorrecta. Solicita recuperación.")
            key = f"private-imports/{owner}/{dataset_id}/{digest}.wav"
            # No DB session or publication lock spans the network operation.
            try:
                for retry in range(3):
                    try:
                        generation = self.storage.ensure(key, path, digest,
                            {"owner_id": str(owner), "dataset_id": dataset_id, "class_name": label})
                        break
                    except TransientSyncError:
                        if retry == 2:
                            raise
                        time.sleep(0.05 * 2**retry)
            except Exception:
                with self.queue.publication(attempt) as (db, _):
                    source = self._source(db, attempt)
                    source.sync_status, source.error = "error", "sync_failed_or_integrity_conflict"
                raise RuntimeError("Synchronization failed") from None
            with self.queue.publication(attempt) as (db, _):
                self._source(db, attempt)
                file = db.get(DatasetMember, identity)
                file.sync_status, file.object_key, file.object_generation = "synced", key, generation
                db.query(ImportFile).filter_by(import_id=attempt["import_id"], sha256=digest).update({"sync_status": "synced"})
            cursor = identity
        with self.queue.publication(attempt) as (db, job):
            source = self._source(db, attempt)
            source.sync_status = "synced"
            count = db.query(func.count(func.distinct(ImportFile.sha256))).filter_by(
                import_id=source.id, sync_status="synced").scalar()
            result = {"dataset_id": dataset_id, "synced_count": count}
            self.queue.complete_publication(db, job, result)
        return result
