"""Owner-scoped imports with an explicit loopback-only development exception."""
import asyncio
import hashlib
import io
import os
import wave
import zipfile
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.services.auth import get_current_user, security_bearer
from app.services.dataset_imports import DatasetImports, reject, _durable_directory

router = APIRouter(prefix="/api/ingestion/imports", tags=["dataset-imports"])


@dataclass(frozen=True)
class ImportPrincipal:
    id: int


def development_imports_enabled(request: Request) -> bool:
    if os.environ.get("FAMA_IMPORT_DEV_MODE") != "1":
        return False
    if os.environ.get("FAMA_ENV") != "development":
        reject(503, "El modo local de importación requiere FAMA_ENV=development.")
    try:
        peer = ip_address(request.client.host) if request.client is not None else None
        frontend = os.environ.get("FAMA_IMPORT_DEV_FRONTEND_IP")
        # An exact transport peer, never a subnet or a forwarded HTTP header.
        local_peer = peer is not None and (peer.is_loopback or (
            frontend is not None and peer == ip_address(frontend)))
    except ValueError:
        local_peer = False
    if not local_peer:
        reject(403, "El modo de desarrollo de importación solo admite loopback o el frontend local autorizado.")
    return True


def get_import_user(request: Request,
                    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
                    db: Session = Depends(get_db)):
    development = development_imports_enabled(request)
    if development and not request.headers.get("authorization"):
        # Reserved non-account identity; never borrow a real user's datasets.
        return ImportPrincipal(id=-1)
    # TODO: The dedicated session view will supply Bearer credentials. Role-based
    # import policy stays deferred; normal authentication is not disabled globally.
    user = get_current_user(credentials, db)
    if user.id <= 0:
        reject(401, "La identidad local de desarrollo no es una cuenta de usuario.")
    return user


@router.get("/access")
def access(request: Request):
    """Reveal only local-mode availability, never owner or dataset information."""
    return {"development_mode": development_imports_enabled(request)}


def get_import_service():
    root = os.environ.get("FAMA_IMPORT_ROOT", str(Path(__file__).resolve().parents[2] / "data" / "dataset-imports"))
    return DatasetImports(root)


def get_import_storage():
    from app.services.dataset_import_storage import GCSImportStorage
    return GCSImportStorage()


def get_import_queue(db: Session = Depends(get_db)):
    from app.services.dataset_import_jobs import ImportJobQueue
    return ImportJobQueue(sessionmaker(bind=db.get_bind()))


class CreateImport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=2000)
    target_id: str | None = Field(default=None, pattern="^[0-9a-f]{32}$")


class CreateReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(strict=True, gt=0, le=2**63 - 1)


class OperationImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class PreviewImport(OperationImport):
    root: str = Field(default="", max_length=240)


class ConfirmImport(OperationImport):
    preview_token: str = Field(min_length=64, max_length=64)


@router.get("/limits")
def limits(user=Depends(get_import_user), service=Depends(get_import_service)):
    return service.limits.public()


@router.get("/example.zip")
def example(user=Depends(get_import_user)):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, label in enumerate(("chucao", "colilarga"), start=1):
            wav = io.BytesIO()
            with wave.open(wav, "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(index.to_bytes(2, "little") * 800)
            archive.writestr(f"aves/{label}/audio_01.wav", wav.getvalue())
    return Response(output.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="dataset-example.zip"'})


def pagination(limit: int | None = Query(default=None, ge=1, le=200),
               cursor: str | None = Query(default=None, max_length=4096)):
    return {"limit": limit, "cursor": cursor}


@router.get("/datasets")
def datasets(db: Session = Depends(get_db), user=Depends(get_import_user), service=Depends(get_import_service),
             paging=Depends(pagination)):
    return service.list_datasets(db, user.id, **paging)


@router.get("/datasets/{dataset_id}/files")
def files(dataset_id: str, db: Session = Depends(get_db), user=Depends(get_import_user), service=Depends(get_import_service),
          paging=Depends(pagination)):
    return service.dataset_page(db, user.id, dataset_id, **paging)


@router.get("/datasets/{dataset_id}/files/{sha256}")
def download(dataset_id: str, sha256: str, db: Session = Depends(get_db), user=Depends(get_import_user), service=Depends(get_import_service)):
    return FileResponse(service.download(db, user.id, dataset_id, sha256), media_type="audio/wav", filename=f"{sha256}.wav")


@router.post("")
def create(payload: CreateImport, db: Session = Depends(get_db), user=Depends(get_import_user), service=Depends(get_import_service)):
    return service.create(db, user.id, payload.model_dump())


@router.get("")
def jobs(db: Session = Depends(get_db), user=Depends(get_import_user), service=Depends(get_import_service),
         paging=Depends(pagination)):
    return service.list_jobs(db, user.id, **paging)


@router.get("/{job_id}/files")
def review_files(job_id: str, db: Session = Depends(get_db), user=Depends(get_import_user),
                 service=Depends(get_import_service), paging=Depends(pagination)):
    return service.review_page(db, user.id, job_id, "files", **paging)


@router.get("/{job_id}/classes")
def review_classes(job_id: str, db: Session = Depends(get_db), user=Depends(get_import_user),
                   service=Depends(get_import_service), paging=Depends(pagination)):
    return service.review_page(db, user.id, job_id, "classes", **paging)


@router.get("/{job_id}/issues")
def review_issues(job_id: str, db: Session = Depends(get_db), user=Depends(get_import_user),
                  service=Depends(get_import_service), paging=Depends(pagination)):
    return service.review_page(db, user.id, job_id, "issues", **paging)


@router.get("/{job_id}")
def status(job_id: str, db: Session = Depends(get_db), user=Depends(get_import_user), service=Depends(get_import_service)):
    return service.view(service.job(db, user.id, job_id))


@router.post("/{job_id}/receipt")
def create_receipt(job_id: str, payload: CreateReceipt, db: Session = Depends(get_db),
                   user=Depends(get_import_user), service=Depends(get_import_service)):
    from app.services.dataset_import_receipts import reserve_receipt
    return reserve_receipt(service, db, user.id, job_id, **payload.model_dump())


@router.get("/{job_id}/receipt")
def receipt_status(job_id: str, db: Session = Depends(get_db),
                   user=Depends(get_import_user), service=Depends(get_import_service)):
    from app.services.dataset_import_receipts import get_receipt
    return get_receipt(service, db, user.id, job_id)


@router.put("/{job_id}/archive")
async def upload(job_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_import_user), service=Depends(get_import_service)):
    # Raw streamed ZIP avoids multipart parser spooling before server admission.
    if request.headers.get("content-type", "").split(";")[0] != "application/zip":
        reject(415, "Selecciona un ZIP y envíalo como application/zip.")
    with service.mutation(db, job_id):
        row = service.job(db, user.id, job_id)
        from app.services.dataset_import_receipts import has_receipt
        if has_receipt(db, job_id):
            reject(409, "Esta importación usa recepción fragmentada; consulta su estado para continuar.")
        service.require_idle(db, job_id)
        db.commit()  # No queue gate or DB write transaction spans receipt.
        if row.status not in ("receiving", "validating", "needs_correction", "ready"):
            reject(409, "La importación no admite otro archivo.")
        staging = service.stage(row)
        staging.mkdir(mode=0o700, exist_ok=True)
        temporary = staging / "receiving.part"
        size, digest = 0, hashlib.sha256()
        try:
            with temporary.open("wb") as output:
                async with asyncio.timeout(service.limits.validation_seconds):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > service.limits.received_bytes:
                            reject(413, "El ZIP supera el límite recibido. Reduce el archivo.")
                        service.space()
                        output.write(chunk)
                        digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            if row.archive_sha256:
                if digest.hexdigest() != row.archive_sha256:
                    reject(409, "Esta solicitud ya recibió otro archivo. Crea una nueva importación.")
            # Even an identical replay must restore the retained original bytes
            # and their directory entry before reporting successful receipt.
            os.replace(temporary, staging / "archive.zip")
            _durable_directory(staging)
            _durable_directory(staging.parent)
            if row.archive_sha256:
                return service.view(row)
            row.archive_sha256 = digest.hexdigest()
            row.status = "validating"
            db.commit()
            return service.view(row)
        except TimeoutError:
            reject(408, "Tiempo de recepción agotado. Reintenta la solicitud.")
        finally:
            temporary.unlink(missing_ok=True)


@router.post("/{job_id}/preview")
def preview(job_id: str, payload: PreviewImport, user=Depends(get_import_user), queue=Depends(get_import_queue)):
    return accepted(queue.admit(user.id, job_id, "preview", payload.request_key, {"root": payload.root}))


@router.post("/{job_id}/confirm")
def confirm(job_id: str, payload: ConfirmImport, user=Depends(get_import_user), queue=Depends(get_import_queue)):
    return accepted(queue.admit(user.id, job_id, "confirm", payload.request_key, {"preview_token": payload.preview_token}))


@router.post("/{job_id}/cancel")
def cancel(job_id: str, db: Session = Depends(get_db), user=Depends(get_import_user), service=Depends(get_import_service)):
    return service.cancel(db, user.id, job_id)


@router.post("/{job_id}/sync")
def sync(job_id: str, payload: OperationImport, user=Depends(get_import_user), queue=Depends(get_import_queue)):
    return accepted(queue.admit(user.id, job_id, "sync", payload.request_key, {}))


def accepted(snapshot):
    from app.services.dataset_import_jobs import public_job
    return JSONResponse(public_job(snapshot), status_code=202, headers={"Location": snapshot["status_url"]})


def owned_execution(queue, owner, import_id, execution_id):
    snapshot = queue.get(owner, execution_id)
    if snapshot["import_id"] != import_id:
        reject(404, "Trabajo no encontrado.")
    return snapshot


@router.get("/{job_id}/jobs/{execution_id}")
def execution_status(job_id: str, execution_id: str, user=Depends(get_import_user), queue=Depends(get_import_queue)):
    from app.services.dataset_import_jobs import public_job
    return public_job(owned_execution(queue, user.id, job_id, execution_id))


@router.post("/{job_id}/jobs/{execution_id}/cancel")
def execution_cancel(job_id: str, execution_id: str, user=Depends(get_import_user), queue=Depends(get_import_queue)):
    from app.services.dataset_import_jobs import public_job
    owned_execution(queue, user.id, job_id, execution_id)
    return public_job(queue.cancel(user.id, execution_id))


@router.post("/{job_id}/jobs/{execution_id}/retry")
def execution_retry(job_id: str, execution_id: str, payload: OperationImport,
                    user=Depends(get_import_user), queue=Depends(get_import_queue)):
    snapshot = owned_execution(queue, user.id, job_id, execution_id)
    if snapshot["status"] not in ("failed", "cancelled"):
        reject(409, "Solo se puede reintentar un trabajo fallido o cancelado.")
    if payload.request_key == snapshot["request_key"]:
        reject(409, "Usa una identidad nueva para reintentar.")
    return accepted(queue.admit(user.id, job_id, snapshot["kind"], payload.request_key, snapshot["parameters"]))
