"""One append-only ZIP, with DB acknowledgement strictly after data durability.

The import lock spans I/O; the queue gate never does. Unacknowledged tail bytes
are discarded on the next append, not advertised as resumable progress.
"""
import asyncio
import hashlib
import os
import time

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.models.dataset_import_chunk import ImportChunk, ImportChunkActivity, ImportChunkSchema
from app.models.dataset_import_receipt import ImportReceipt
from app.services.dataset_import_receipts import _ready, _view
from app.services.dataset_imports import reject, _durable_directory


def ready(db):
    _ready(db)
    try:
        marker = db.get(ImportChunkSchema, 1)
    except SQLAlchemyError:
        reject(503, "Los fragmentos requieren migración explícita antes de continuar.")
    if marker is None or marker.version != 1:
        reject(503, "Los fragmentos requieren migración explícita antes de continuar.")


def receipt(service, db, owner, identity):
    source = service.job(db, owner, identity)
    ready(db)
    row = db.get(ImportReceipt, identity)
    if row is None:
        reject(404, "Recepción no encontrada.")
    return source, row


def activity(db, identity):
    row = db.get(ImportChunkActivity, identity)
    if row is None:
        db.add(ImportChunkActivity(import_id=identity, updated_at=time.time()))
    else:
        row.updated_at = time.time()


def protects_cleanup(service, db, source, cutoff):
    """Called only with the shared import lock and queue gate already held."""
    if not inspect(db.connection()).has_table(ImportChunkSchema.__tablename__):
        return False
    marker = db.get(ImportChunkSchema, 1)
    if marker is None:
        return False
    row = db.get(ImportReceipt, source.id)
    if row is None or row.status == "cancelled" or source.status == "cancelled":
        return False
    recent = db.get(ImportChunkActivity, source.id)
    return bool((recent and recent.updated_at >= cutoff) or
                (row.status == "receiving" and (service.stage(source) / "archive.zip").exists()))


def hash_page(service, db, owner, identity, **paging):
    from app.services.dataset_import_records import page
    _, row = receipt(service, db, owner, identity)
    # Bind each traversal to its complete accepted prefix. A concurrent append
    # requires restarting pagination rather than silently mixing snapshots.
    return page(db.query(ImportChunk).filter(ImportChunk.import_id == identity,
                    ImportChunk.offset_bytes + ImportChunk.length_bytes <= row.received_bytes), ImportChunk.chunk_index,
                scope=f"{identity}:chunks", snapshot=row.received_bytes, key="chunks",
                serialize=lambda chunk: dict(index=chunk.chunk_index, offset_bytes=chunk.offset_bytes,
                    length_bytes=chunk.length_bytes, sha256=chunk.sha256), **paging)


async def accept_chunk(service, db, owner, identity, index, offset, sha256, request):
    with service.mutation(db, identity):
        source, row = receipt(service, db, owner, identity)
        service.require_idle(db, identity)
        if row.status != "receiving" or source.status != "receiving" or not row.reservation_active:
            reject(409, "La recepción no admite modificaciones.")
        if index < 0 or offset < 0 or index * row.chunk_bytes != offset or offset > row.received_bytes:
            reject(409, "El fragmento deja un hueco o solapa otra posición.")
        length = min(row.chunk_bytes, row.size_bytes - offset)
        if length <= 0:
            reject(413, "El fragmento supera el tamaño declarado.")
        prior = db.get(ImportChunk, (identity, index))
        if offset < row.received_bytes and prior is None:
            reject(409, "El prefijo durable no es coherente.")
        if prior and (prior.offset_bytes != offset or prior.length_bytes != length or prior.sha256 != sha256):
            reject(409, "La posición ya contiene otro fragmento.")
        prefix = row.received_bytes
        staging = service.stage(source)
        db.rollback()  # No transaction, including a read snapshot, spans I/O.
        if staging.is_symlink():
            reject(503, "Almacenamiento no válido.")
        staging.mkdir(mode=0o700, exist_ok=True)
        archive = staging / "archive.zip"
        if archive.exists() and not prior:
            reject(409, "La recepción requiere completar su finalización.")
        path = archive if archive.exists() else staging / "receiving.part"
        flags = os.O_RDONLY if prior else os.O_RDWR | os.O_CREAT
        fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_size < prefix:
                reject(409, "El prefijo durable no está disponible. Solicita recuperación.")
            if not prior:
                os.ftruncate(fd, prefix)
                os.lseek(fd, prefix, os.SEEK_SET)
            size, digest = 0, hashlib.sha256()
            try:
                async with asyncio.timeout(service.limits.validation_seconds):
                    async for block in request.stream():
                        size += len(block)
                        if size > length:
                            reject(413, "El fragmento supera la longitud esperada.")
                        digest.update(block)
                        if not prior:
                            service.space()
                            view = memoryview(block)
                            while view:
                                written = os.write(fd, view)
                                if written <= 0:
                                    raise OSError("Short chunk write")
                                view = view[written:]
                if size != length or digest.hexdigest() != sha256:
                    reject(409, "La longitud o SHA-256 del fragmento no coincide.")
                if prior:
                    os.lseek(fd, offset, os.SEEK_SET)
                    remaining, stored = length, hashlib.sha256()
                    while remaining:
                        block = os.read(fd, min(1024**2, remaining))
                        if not block:
                            reject(409, "El prefijo durable no está disponible. Solicita recuperación.")
                        stored.update(block)
                        remaining -= len(block)
                    if stored.hexdigest() != sha256:
                        reject(409, "La integridad del prefijo durable no coincide.")
                    return _view(db.get(ImportReceipt, identity))
                os.fsync(fd)
                _durable_directory(staging)
                _durable_directory(staging.parent)
            except BaseException:
                if not prior:
                    os.ftruncate(fd, prefix)
                    os.fsync(fd)
                raise
        except TimeoutError:
            reject(408, "Tiempo de recepción agotado. Reintenta la solicitud.")
        finally:
            os.close(fd)
        service.require_idle(db, identity)
        row = db.get(ImportReceipt, identity)
        db.add(ImportChunk(import_id=identity, chunk_index=index, offset_bytes=offset,
                           length_bytes=length, sha256=sha256))
        row.received_bytes = prefix + length
        activity(db, identity)
        db.commit()
        return _view(row)


def finalize(service, db, owner, identity):
    with service.mutation(db, identity):
        source, row = receipt(service, db, owner, identity)
        service.require_idle(db, identity)
        if row.status == "cancelled" or source.status == "cancelled" or not row.reservation_active:
            reject(409, "La recepción no admite finalización.")
        if row.received_bytes != row.size_bytes:
            reject(409, "La recepción está incompleta.")
        staging, expected, chunk_bytes = service.stage(source), row.size_bytes, row.chunk_bytes
        sealed, archive_hash = row.status == "sealed", source.archive_sha256
        db.rollback()
        if staging.is_symlink():
            reject(503, "Almacenamiento no válido.")
        archive, partial = staging / "archive.zip", staging / "receiving.part"
        # A complete DB prefix plus archive.zip is the rename-before-commit
        # recovery intent. Never assemble a second ZIP or trust the rename alone.
        path = archive if archive.exists() else partial
        if not path.exists() or (sealed and path != archive):
            reject(409, "El archivo recibido no está disponible. Solicita recuperación.")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        digest, offset, index = hashlib.sha256(), 0, 0
        deadline = time.monotonic() + service.limits.validation_seconds
        try:
            if os.fstat(fd).st_size != expected:
                reject(409, "El tamaño del archivo recibido no coincide.")
            while offset < expected:
                records = [(c.chunk_index, c.offset_bytes, c.length_bytes, c.sha256) for c in
                    db.query(ImportChunk).filter(ImportChunk.import_id == identity,
                        ImportChunk.chunk_index >= index).order_by(ImportChunk.chunk_index).limit(200)]
                db.rollback()  # Release the read snapshot before hashing bytes.
                if not records:
                    reject(409, "El prefijo durable no es coherente.")
                for number, position, length, sha in records:
                    if (number != index or position != offset or
                            length != min(chunk_bytes, expected - offset) or length <= 0):
                        reject(409, "El prefijo durable no es coherente.")
                    remaining, chunk_hash = length, hashlib.sha256()
                    while remaining:
                        if time.monotonic() >= deadline:
                            reject(408, "Tiempo de verificación agotado. Reintenta la solicitud.")
                        block = os.read(fd, min(1024**2, remaining))
                        if not block:
                            reject(409, "El tamaño del archivo recibido no coincide.")
                        chunk_hash.update(block)
                        digest.update(block)
                        remaining -= len(block)
                    if chunk_hash.hexdigest() != sha:
                        reject(409, "La integridad del archivo recibido no coincide.")
                    offset += length
                    index += 1
            if archive_hash and digest.hexdigest() != archive_hash:
                reject(409, "La integridad del archivo recibido no coincide.")
            os.fsync(fd)
        finally:
            os.close(fd)
        if path == partial:
            os.replace(partial, archive)
        _durable_directory(staging)
        _durable_directory(staging.parent)
        service.require_idle(db, identity)
        row = db.get(ImportReceipt, identity)
        if not sealed:
            source = service.job(db, owner, identity)
            source.archive_sha256, source.status = digest.hexdigest(), "validating"
            row.status = "sealed"
            activity(db, identity)
            db.commit()
        return _view(row)
