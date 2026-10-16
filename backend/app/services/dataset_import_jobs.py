"""Database-backed execution admission; notifications are never queue authority."""
from dataclasses import dataclass
import hashlib
import json
import os
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.models.dataset_import import DatasetImport
from app.models.dataset_import_job import ImportJob, ImportJobGate
from app.models.dataset_import_metadata import ImportSummary


ACTIVE = ("queued", "running")


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
                status_url=f"/api/ingestion/imports/{row.import_id}/jobs/{row.id}")


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

    def __init__(self, sessions, *, limits=None, clock=time.time):
        self.sessions = sessions
        self.limits = limits or JobLimits.from_environment()
        self.clock = clock

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
            if kind == "preview" and (source.status not in ("validating", "needs_correction", "ready")
                                      or not source.archive_sha256):
                _reject(409, "La importación no admite una nueva vista previa.")
            if kind == "confirm" and (source.status not in ("ready", "committing", "imported")
                                      or source.preview_token != parameters["preview_token"]):
                _reject(409, "La vista previa cambió o no está lista para confirmar.")
            if kind == "sync" and (source.status != "imported" or not source.dataset_id):
                _reject(409, "Confirma una importación con contenido antes de sincronizar.")
            global_count, owner_count = self._counts(db, owner)
            if global_count >= self.limits.global_active or owner_count >= self.limits.owner_active:
                _reject(429, "Se alcanzó el límite de trabajos activos.")
            if db.scalar(select(ImportJob.id).where(
                    ImportJob.import_id == import_id, ImportJob.status.in_(ACTIVE)).limit(1)):
                _reject(409, "La importación ya tiene un trabajo activo.")
            now = self.clock()
            row = ImportJob(id=uuid.uuid4().hex, owner_id=owner, import_id=import_id,
                            kind=kind, request_key=request_key, parameters=json.loads(encoded),
                            parameters_sha256=digest, expected_preview_token=parameters.get("preview_token"),
                            expected_revision=summary.preview.get("target_revision") if kind == "confirm" else None,
                            status="queued",
                            stage="queued", progress=0, result={}, error=None, attempt=0,
                            token=0, created_at=now, updated_at=now)
            db.add(row)
            db.flush()
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
            row.updated_at = self.clock()
            db.flush()
            # Capacity is represented by active rows, so this terminal state
            # releases it in exactly the same transaction, even after restart.
            return _snapshot(row)
