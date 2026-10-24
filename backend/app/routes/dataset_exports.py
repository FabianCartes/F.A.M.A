"""Bearer control plane and cookie-authorized native byte ranges, never a Blob."""
import fcntl
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.routes.dataset_imports import OperationImport, get_import_service, get_import_user
from app.services.dataset_exports import ExportQueue, artifact_identity, public_export
from app.services.dataset_import_worker import _private_root
from app.services.dataset_imports import reject

router = APIRouter()


def get_export_queue(db: Session = Depends(get_db), service=Depends(get_import_service)):
    return ExportQueue(sessionmaker(bind=db.get_bind()), service)


def export_root():
    value = os.environ.get("FAMA_EXPORT_ROOT")
    if not value:
        reject(503, "Configura el almacenamiento privado de exportaciones.")
    try:
        return _private_root(Path(value))
    except (ValueError, OSError):
        reject(503, "El almacenamiento privado de exportaciones no está disponible.")


def download_origin():
    value = os.environ.get("FAMA_EXPORT_DOWNLOAD_ORIGIN", "")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        reject(503, "Configura un origen HTTPS de descarga directo, fuera de la reescritura de Next.")
    return value


@router.post("/datasets/{dataset_id}/revisions/{revision}/exports", status_code=202)
def admit_export(dataset_id: str, revision: int, payload: OperationImport,
                 user=Depends(get_import_user), queue=Depends(get_export_queue)):
    return public_export(queue.admit(user.id, dataset_id, revision, payload.request_key))


@router.get("/exports/{export_id}")
def export_status(export_id: str, user=Depends(get_import_user), queue=Depends(get_export_queue)):
    return public_export(queue.get(user.id, export_id))


@router.get("/datasets/{dataset_id}/exports")
def export_history(dataset_id: str, user=Depends(get_import_user), queue=Depends(get_export_queue)):
    return queue.list(user.id, dataset_id)


@router.post("/exports/{export_id}/sessions")
def issue_session(export_id: str, user=Depends(get_import_user), queue=Depends(get_export_queue)):
    origin = download_origin()  # Fail before creating a session if routing is unavailable.
    export_root()
    session = queue.issue_session(user.id, export_id)
    return JSONResponse(dict(url=f"{origin}/api/ingestion/imports/exports/{export_id}/download?ticket={session['ticket']}",
                             expires_at=session["expires_at"]),
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


class _DownloadResponse(StreamingResponse):
    """Release locks even if ASGI send fails before iteration or disconnects."""
    def __init__(self, body, close, **kwargs):
        self.close = close
        super().__init__(body, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.close()


@router.api_route("/exports/{export_id}/download", methods=["GET", "HEAD"])
def download_export(export_id: str, request: Request, queue=Depends(get_export_queue)):
    cookie_name = "fama_export_" + export_id
    cookie = request.cookies.get(cookie_name)
    ticket = request.query_params.get("ticket")
    established = None
    if ticket is not None:
        try:
            established = queue.authorize_download(export_id, ticket, bootstrap=True)
        except HTTPException as error:
            if error.status_code != 401 or not cookie:
                raise
            # Repeated native navigation may retain its consumed ticket. It is
            # still an explicit credential: validate it rather than ignoring an
            # arbitrary invalid value just because another credential exists.
            queue.authorize_download(export_id, ticket)
    if established is not None:
        _, remaining = established
        response = RedirectResponse(f"/api/ingestion/imports/exports/{export_id}/download", status_code=303,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        response.set_cookie(cookie_name, ticket, max_age=max(1, int(remaining)), secure=True,
            httponly=True, samesite="lax", path=f"/api/ingestion/imports/exports/{export_id}/download")
        return response
    row, _ = queue.authorize_download(export_id, cookie)
    root = export_root()
    artifact = row["artifact"]
    if not artifact or not re.fullmatch(re.escape(export_id) + r"-[1-9][0-9]*-[1-9][0-9]*/export\.zip", artifact):
        reject(409, "Identidad de exportación no válida.")
    directory = root / artifact.split("/")[0]
    directory_fd = file_fd = None
    def close():
        nonlocal directory_fd, file_fd
        if file_fd is not None:
            os.close(file_fd)
            file_fd = None
        if directory_fd is not None:
            os.close(directory_fd)
            directory_fd = None
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fcntl.flock(directory_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        # Cleanup owns an exclusive directory lock before its deleting fence.
        queue.authorize_download(export_id, cookie)
        file_fd = os.open(directory / "export.zip", os.O_RDONLY | os.O_NOFOLLOW)
        size = os.fstat(file_fd).st_size
        if size != row["size_bytes"] or artifact_identity(os.fstat(file_fd)) != row["artifact_identity"]:
            reject(409, "El archivo de exportación cambió.")
        etag = '"' + row["sha256"] + '"'
        headers = {"Content-Disposition": f'attachment; filename="dataset-{row["dataset_id"]}-r{row["revision"]}.zip"',
                   "Content-Length": str(size), "ETag": etag, "Accept-Ranges": "bytes",
                   "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
                   "X-Content-Type-Options": "nosniff"}
        start, end, status = 0, size - 1, 200
        byte_range = request.headers.get("range")
        if byte_range and request.headers.get("if-range", etag) == etag:
            match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", byte_range)
            valid = match and any(match.groups()) and len(byte_range) <= 100
            if valid:
                left, right = match.groups()
                if left:
                    start, end = int(left), min(int(right), size - 1) if right else size - 1
                else:
                    start, end = max(0, size - int(right)), size - 1
                    valid = int(right) > 0
                valid = valid and 0 <= start <= end < size
            if not valid:
                close()
                return Response(status_code=416, headers=dict(headers, **{"Content-Range": f"bytes */{size}", "Content-Length": "0"}))
            status = 206
            headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
        if request.method == "HEAD":
            close()
            return Response(status_code=status, headers=headers, media_type="application/zip")
        os.lseek(file_fd, start, os.SEEK_SET)
        def chunks():
            remaining = end - start + 1
            while remaining:
                data = os.read(file_fd, min(1024 * 1024, remaining))
                if not data:
                    raise OSError("Export truncated during download")
                remaining -= len(data)
                yield data
        return _DownloadResponse(chunks(), close, status_code=status, headers=headers, media_type="application/zip")
    except (OSError, ValueError):
        close()
        reject(410, "El archivo de exportación no está disponible.")
    except BaseException:
        close()
        raise
