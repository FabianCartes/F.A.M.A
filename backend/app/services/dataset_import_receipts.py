"""Short transactional receipt reservations; never a cumulative dataset quota.

The stored promise includes the declared ZIP and one configured expanded-byte
allowance. Existing bytes still reduce filesystem free space: admission is
deliberately conservative rather than pretending promises are physical files.
"""
import os
import shutil

from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.models.dataset_import import DatasetImport
from app.models.dataset_import_receipt import ImportReceipt, ImportReceiptSchema
from app.services.dataset_import_jobs import _gate
from app.services.dataset_imports import reject


ACTIVE_IMPORTS = ("receiving", "validating", "needs_correction", "ready", "committing")
CHUNK_BYTES = 16 * 1024**2


def _ready(db):
    try:
        marker = db.get(ImportReceiptSchema, 1)
    except SQLAlchemyError:
        reject(503, "La recepción requiere migración explícita antes de continuar.")
    if marker is None or marker.version != 1:
        reject(503, "La recepción requiere migración explícita antes de continuar.")


def _view(row):
    return {"import_id": row.import_id, "name": row.name, "size_bytes": row.size_bytes,
            "reserved_bytes": row.reserved_bytes if row.reservation_active else 0,
            "received_bytes": row.received_bytes, "chunk_bytes": row.chunk_bytes, "status": row.status}


def _budgets(limits):
    maximum = limits.received_bytes + limits.expanded_bytes
    try:
        owner = int(os.environ.get("FAMA_IMPORT_RESERVED_BYTES_PER_OWNER", maximum))
        total = int(os.environ.get("FAMA_IMPORT_RESERVED_BYTES_GLOBAL", maximum * limits.concurrent_imports))
        if not 0 < owner <= 2**63 - 1 or not 0 < total <= 2**63 - 1:
            raise ValueError
    except ValueError:
        reject(503, "La configuración del presupuesto temporal no es válida.")
    return owner, total


def get_receipt(service, db, owner, import_id):
    service.job(db, owner, import_id)
    _ready(db)
    row = db.get(ImportReceipt, import_id)
    if row is None:
        reject(404, "Recepción no encontrada.")
    return _view(row)


def reserve_receipt(service, db, owner, import_id, *, name, size_bytes):
    with service.mutation(db, import_id):
        source = service.job(db, owner, import_id)
        _ready(db)
        _gate(db)
        prior = db.get(ImportReceipt, import_id)
        if prior is not None:
            if prior.name != name or prior.size_bytes != size_bytes or source.status == "cancelled":
                reject(409, "La recepción ya existe con otros parámetros o fue cancelada.")
            return _view(prior)
        if source.status != "receiving" or source.archive_sha256:
            reject(409, "La importación no admite una recepción nueva.")
        if size_bytes > service.limits.received_bytes:
            reject(413, "El ZIP supera el límite recibido. Reduce el archivo.")
        owner_budget, global_budget = _budgets(service.limits)
        # Published datasets have no further ZIP/extraction promise. Releasing
        # that promise does not claim retained staging or WAVs were deleted.
        db.execute(update(ImportReceipt).where(ImportReceipt.import_id.in_(
            select(DatasetImport.id).where(DatasetImport.status == "imported")),
            ImportReceipt.reservation_active.is_(True)).values(reservation_active=False))
        active = db.query(ImportReceipt).join(DatasetImport, DatasetImport.id == ImportReceipt.import_id).filter(
            ImportReceipt.reservation_active.is_(True))
        if active.filter(DatasetImport.owner_id == owner).first() is not None:
            reject(429, "Finaliza o cancela tu importación en curso antes de iniciar otra recepción.")
        owner_used = active.filter(DatasetImport.owner_id == owner).with_entities(
            func.coalesce(func.sum(ImportReceipt.reserved_bytes), 0)).scalar()
        total_used = active.with_entities(func.coalesce(func.sum(ImportReceipt.reserved_bytes), 0)).scalar()
        promise = size_bytes + service.limits.expanded_bytes
        if owner_used + promise > owner_budget or total_used + promise > global_budget:
            reject(429, "Presupuesto temporal agotado. Finaliza o cancela recepciones antes de reintentar.")
        if total_used + promise + service.limits.free_bytes > shutil.disk_usage(service.root).free:
            reject(507, "Espacio disponible insuficiente para reservar la recepción y su expansión.")
        try:
            chunk_bytes = int(os.environ.get("FAMA_IMPORT_CHUNK_BYTES", CHUNK_BYTES))
            if not 1 <= chunk_bytes <= 2**31 - 1:
                raise ValueError
        except ValueError:
            reject(503, "La configuración de fragmentos no es válida.")
        row = ImportReceipt(import_id=import_id, name=name, size_bytes=size_bytes,
            reserved_bytes=promise, reservation_active=True, received_bytes=0,
            chunk_bytes=chunk_bytes, status="receiving")
        db.add(row)
        db.commit()
        return _view(row)


def has_receipt(db, import_id):
    # Compatibility only until the coordinated whole-body/protocol cutover.
    # A fresh/legacy schema is not silently migrated by an HTTP request.
    return inspect(db.connection()).has_table(ImportReceipt.__tablename__) and db.get(ImportReceipt, import_id) is not None


def release_receipt(db, import_id):
    """After safe cancellation/deletion, release the outstanding write promise."""
    if has_receipt(db, import_id):
        _gate(db)
        row = db.get(ImportReceipt, import_id)
        row.reservation_active = False
        source = db.get(DatasetImport, import_id)
        if source.status == "cancelled":
            row.status = "cancelled"
        db.commit()


def release_published_receipt(db, source):
    """Release a fulfilled promise inside the caller's publication transaction.

    The queue gate is already held. Never reacquire it or commit independently:
    membership, journal completion and this release must succeed together.
    Legacy imports may have no receipt table/row; no migration is performed.
    This does not assert that retained archive or attempt files were removed.
    """
    if source.status != "imported":
        raise ValueError("Only published imports fulfill their reservation")
    if has_receipt(db, source.id):
        db.get(ImportReceipt, source.id).reservation_active = False
