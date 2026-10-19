"""Database-backed execution admission; notifications are never queue authority."""
from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import math
import os
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import Float, cast, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.models.dataset_import import DatasetImport, ImportedDataset
from app.models.dataset_import_job import ImportJob, ImportJobGate
from app.models.dataset_import_metadata import ImportSummary


ACTIVE = ("queued", "running")


class LeaseLost(RuntimeError):
    """The attempt is no longer authorized to write."""


def lease_duration(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 3600:
        raise ValueError("Lease duration must be finite and in (0, 3600]")
    return value


@dataclass(frozen=True)
class JobLimits:
    global_active: int = 4
    owner_active: int = 1

    def __post_init__(self):
        if any(type(value) is not int or not 1 <= value <= 2**31 - 1
               for value in (self.global_active, self.owner_active)):
            raise ValueError("Job limits must be positive bounded integers")

    @classmethod
    def from_environment(cls):
        return cls(int(os.environ.get("FAMA_IMPORT_CONCURRENT_IMPORTS", "4")),
                   int(os.environ.get("FAMA_IMPORT_JOBS_PER_OWNER", "1")))


def _reject(code, message):
    raise HTTPException(code, detail=message)


def _snapshot(row):
    return dict(id=row.id, import_id=row.import_id, kind=row.kind, status=row.status,
                stage=row.stage, progress=row.progress, result=dict(row.result),
                error=dict(row.error) if row.error else None, attempt=row.attempt,
                token=row.token, created_at=row.created_at, updated_at=row.updated_at,
                lease_until=row.lease_until, heartbeat_at=row.heartbeat_at,
                parameters=dict(row.parameters), request_key=row.request_key,
                 status_url=f"/api/ingestion/imports/{row.import_id}/jobs/{row.id}")


def public_job(snapshot):
    """Bounded owner-facing state, excluding execution credentials/parameters."""
    return {key: snapshot[key] for key in (
        "id", "import_id", "kind", "status", "stage", "progress", "result", "error", "status_url")}


def _gate(db):
    # UPDATE is the atomic reservation primitive. Counts and insertion happen
    # only while its database write lock is held, never count-then-insert alone.
    if db.get_bind().dialect.name not in ("sqlite", "postgresql"):
        _reject(503, "Motor de cola no disponible.")
    try:
        changed = db.execute(update(ImportJobGate).where(
            ImportJobGate.id == 1, ImportJobGate.version == 1).values(
                generation=ImportJobGate.generation + 1)).rowcount
    except SQLAlchemyError:
        _reject(503, "La cola no está disponible; conserva la solicitud y reintenta después.")
    if changed != 1:
        _reject(503, "La cola requiere migración explícita antes de admitir trabajos.")


def _owned(db, owner, job_id):
    row = db.scalar(select(ImportJob).where(ImportJob.id == job_id, ImportJob.owner_id == owner))
    if row is None:
        _reject(404, "Trabajo no encontrado.")
    return row


class ImportJobQueue:
    """Short transactions only; no filesystem, decoder, network or request session."""

    def __init__(self, sessions, *, limits=None, clock=None, allowed_kinds=None):
        if allowed_kinds is not None:
            if (isinstance(allowed_kinds, str) or not allowed_kinds
                    or not set(allowed_kinds) <= {"preview", "confirm", "sync"}):
                raise ValueError("Claim kinds must be a nonempty collection of known job kinds")
            allowed_kinds = frozenset(allowed_kinds)
        self.sessions = sessions
        self.limits = limits or JobLimits.from_environment()
        self.clock = clock
        self.allowed_kinds = allowed_kinds

    def _now(self, db):
        if self.clock is not None:
            return self.clock()
        # One authority for all processes using the same database. PostgreSQL
        # clock_timestamp (not transaction-start now()) follows gate acquisition.
        expression = ((func.julianday("now") - 2440587.5) * 86400.0
                      if db.get_bind().dialect.name == "sqlite"
                      else func.extract("epoch", func.clock_timestamp()))
        return float(db.scalar(select(expression)))

    def claim(self, *, lease_seconds):
        duration = lease_duration(lease_seconds)
        with self.sessions() as db, db.begin():
            _gate(db)
            now = self._now(db)
            query = select(ImportJob).where(or_(
                ImportJob.status == "queued",
                (ImportJob.status == "running") & (ImportJob.lease_until <= now)
            ))
            if self.allowed_kinds is not None:
                query = query.where(ImportJob.kind.in_(self.allowed_kinds))
            row = db.scalar(query.order_by(ImportJob.created_at, ImportJob.id).limit(1))
            if row is None:
                return None
            row.attempt += 1
            row.token += 1
            row.status, row.stage, row.progress = "running", "running", 0
            row.result, row.error = {}, None
            row.lease_until, row.heartbeat_at, row.updated_at = now + duration, now, now
            db.flush()
            return _snapshot(row)

    def _current(self, db, attempt):
        _gate(db)
        now = self._now(db)
        row = db.scalar(select(ImportJob).where(
            ImportJob.id == attempt["id"], ImportJob.attempt == attempt["attempt"],
            ImportJob.token == attempt["token"], ImportJob.status == "running",
            ImportJob.lease_until > now))
        if row is None:
            raise LeaseLost("Attempt lease lost")
        return row, now

    @contextmanager
    def publication(self, attempt):
        """Serialize a short publication against reclaim, cancellation and admission.

        No hashing, decoding or network is permitted in this transaction. The
        gate remains held through filesystem metadata operations and commit.
        A lease expiring inside the critical section rejects the DB publication;
        its previously committed journal remains available for recovery.
        """
        with self.sessions() as db, db.begin():
            row, _ = self._current(db, attempt)
            yield db, row
            if row.status == "running" and row.lease_until <= self._now(db):
                raise LeaseLost("Attempt expired during publication")

    def complete_publication(self, db, row, result):
        now = self._now(db)
        if row.status != "running" or row.lease_until <= now:
            raise LeaseLost("Attempt expired during publication")
        row.status = row.stage = "succeeded"
        row.result, row.error, row.progress = dict(result), None, 100
        row.lease_until, row.updated_at = None, now

    def heartbeat(self, attempt, *, lease_seconds):
        duration = lease_duration(lease_seconds)
        with self.sessions() as db, db.begin():
            row, now = self._current(db, attempt)
            row.lease_until = max(row.lease_until, now + duration)
            row.heartbeat_at, row.updated_at = now, now

    def progress(self, attempt, *, stage, progress):
        if stage not in ("running", "validating", "verifying", "syncing", "prepared"):
            raise ValueError("Invalid execution stage")
        if type(progress) is not int or not 0 <= progress <= 99:
            raise ValueError("Invalid execution progress")
        with self.sessions() as db, db.begin():
            row, now = self._current(db, attempt)
            if progress < row.progress:
                raise ValueError("Progress must not decrease")
            row.stage, row.progress, row.updated_at = stage, progress, now

    def finish(self, attempt, *, result=None, error=None):
        if error not in (None, "execution_failed", "execution_timeout", "staging_failed"):
            raise ValueError("Invalid execution error")
        result = {} if result is None else result
        if not isinstance(result, dict) or set(result) - {"dataset_id", "dataset_revision", "added_count", "synced_count"}:
            raise ValueError("Invalid execution result")
        for key, value in result.items():
            if key == "dataset_id":
                if not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
                    raise ValueError("Invalid dataset identity")
            elif type(value) is not int or not 0 <= value <= 2**31 - 1:
                raise ValueError("Invalid result count")
        with self.sessions() as db, db.begin():
            row, now = self._current(db, attempt)
            row.status = row.stage = "failed" if error else "succeeded"
            row.result = {} if error else dict(result)
            row.error = {"code": error} if error else None
            row.progress = row.progress if error else 100
            row.lease_until, row.updated_at = None, now

    def admit(self, owner, import_id, kind, request_key, parameters):
        if kind not in ("preview", "confirm", "sync"):
            _reject(422, "Tipo de trabajo no válido.")
        if (not isinstance(request_key, str) or not 1 <= len(request_key) <= 100
                or not request_key.isascii() or not all(c.isalnum() or c in "-_.:" for c in request_key)):
            _reject(422, "Identidad de operación no válida.")
        if not isinstance(parameters, dict):
            _reject(422, "Parámetros de trabajo no válidos.")
        expected_keys = {"preview": {"root"}, "confirm": {"preview_token"}, "sync": set()}[kind]
        if set(parameters) != expected_keys:
            _reject(422, "Parámetros de trabajo no válidos.")
        if kind == "preview" and (not isinstance(parameters["root"], str) or len(parameters["root"]) > 240):
            _reject(422, "Raíz de revisión no válida.")
        if kind == "confirm" and (not isinstance(parameters["preview_token"], str)
                or len(parameters["preview_token"]) != 64
                or any(c not in "0123456789abcdef" for c in parameters["preview_token"])):
            _reject(422, "Token de revisión no válido.")
        try:
            encoded = json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError):
            _reject(422, "Parámetros de trabajo no válidos.")
        if len(encoded.encode("utf-8")) > 4096:
            _reject(422, "Parámetros de trabajo demasiado extensos.")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self.sessions() as db, db.begin():
            _gate(db)
            source = db.scalar(select(DatasetImport).where(
                DatasetImport.id == import_id, DatasetImport.owner_id == owner))
            if source is None:
                _reject(404, "Importación no encontrada.")
            from app.services.dataset_import_cleanup import require_available
            require_available(db, import_id)
            prior = db.scalar(select(ImportJob).where(
                ImportJob.owner_id == owner, ImportJob.import_id == import_id,
                ImportJob.kind == kind, ImportJob.request_key == request_key))
            if prior:
                if prior.parameters_sha256 != digest or prior.parameters != parameters:
                    _reject(409, "La operación ya existe con otros parámetros.")
                return _snapshot(prior)
            summary = db.get(ImportSummary, source.id)
            if summary is None:
                _reject(503, "Los metadatos requieren migración verificada antes de continuar.")
            if source.error == "expired":
                _reject(410, "La importación venció. Crea una nueva solicitud.")
            if kind == "preview" and (source.status not in ("validating", "needs_correction", "ready")
                                      or not source.archive_sha256):
                _reject(409, "La importación no admite una nueva vista previa.")
            if kind == "confirm" and (source.status not in ("ready", "committing", "imported")
                                      or source.preview_token != parameters["preview_token"]):
                _reject(409, "La vista previa cambió o no está lista para confirmar.")
            if kind == "confirm" and source.status != "imported":
                target_id = summary.preview.get("resolved_target_id")
                target = db.get(ImportedDataset, target_id) if target_id else None
                if target_id and (not target or target.owner_id != owner or target.revision != summary.preview.get("target_revision")):
                    _reject(409, "El dataset cambió. Genera y revisa una nueva vista previa.")
                if not target_id:
                    equivalent = db.scalar(select(DatasetImport.id).join(ImportSummary,
                        ImportSummary.import_id == DatasetImport.id).where(DatasetImport.owner_id == owner,
                        DatasetImport.status == "imported", ImportSummary.fingerprint == summary.fingerprint).limit(1))
                    collision = db.scalar(select(ImportedDataset.id).where(ImportedDataset.owner_id == owner,
                        ImportedDataset.name == source.request["name"]).limit(1))
                    if equivalent or collision:
                        _reject(409, "El destino cambió. Genera y revisa una nueva vista previa.")
                for other in db.scalars(select(DatasetImport).where(DatasetImport.owner_id == owner,
                        DatasetImport.status == "committing", DatasetImport.id != source.id)):
                    if (target_id and other.dataset_id == target_id or
                            not target_id and other.request["name"] == source.request["name"] or
                            db.get(ImportSummary, other.id).fingerprint == summary.fingerprint):
                        _reject(409, "Hay una confirmación pendiente de recuperación para este destino. Reinténtala primero.")
            if kind == "sync" and (source.status != "imported" or not source.dataset_id):
                _reject(409, "Confirma una importación con contenido antes de sincronizar.")
            global_count, owner_count = self._counts(db, owner)
            if global_count >= self.limits.global_active or owner_count >= self.limits.owner_active:
                _reject(429, "Se alcanzó el límite de trabajos activos.")
            if db.scalar(select(ImportJob.id).where(
                    ImportJob.import_id == import_id, ImportJob.status.in_(ACTIVE)).limit(1)):
                _reject(409, "La importación ya tiene un trabajo activo.")
            now = self._now(db)
            row = ImportJob(id=uuid.uuid4().hex, owner_id=owner, import_id=import_id,
                            kind=kind, request_key=request_key, parameters=json.loads(encoded),
                            parameters_sha256=digest, expected_preview_token=parameters.get("preview_token"),
                            expected_revision=summary.preview.get("target_revision") if kind == "confirm" else None,
                            status="queued",
                            stage="queued", progress=0, result={}, error=None, attempt=0,
                            token=0, created_at=now, updated_at=now)
            db.add(row)
            db.flush()
            summary.preview = dict(summary.preview, execution_id=row.id, _activity_at=time.time())
            return _snapshot(row)

    @staticmethod
    def _counts(db, owner):
        return (db.scalar(select(func.count()).select_from(ImportJob).where(ImportJob.status.in_(ACTIVE))),
                db.scalar(select(func.count()).select_from(ImportJob).where(
                    ImportJob.status.in_(ACTIVE), ImportJob.owner_id == owner)))

    def active_counts(self, owner):
        with self.sessions() as db:
            global_count, owner_count = self._counts(db, owner)
            return {"global": global_count, "owner": owner_count}

    def get(self, owner, job_id):
        # Polling never touches useful activity, heartbeat or the admission gate.
        with self.sessions() as db:
            return _snapshot(_owned(db, owner, job_id))

    def cancel(self, owner, job_id):
        with self.sessions() as db, db.begin():
            _gate(db)
            row = _owned(db, owner, job_id)
            if row.status == "cancelled":
                return _snapshot(row)
            if row.status != "queued":
                _reject(409, "Solo se puede cancelar un trabajo pendiente de ejecución.")
            row.status, row.stage = "cancelled", "cancelled"
            row.updated_at = self._now(db)
            db.flush()
            # Capacity is represented by active rows, so this terminal state
            # releases it in exactly the same transaction, even after restart.
            return _snapshot(row)
