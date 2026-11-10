"""POSIX ZIP workers are optional; unsupported hosts retain the rest of F.A.M.A."""
import os
from fastapi import APIRouter, HTTPException

def zip_router(*, supported=None):
    if supported is None:
        supported = os.name == "posix"
    if supported:
        from app.routes.dataset_imports import router
        return router
    router = APIRouter(prefix="/api/ingestion/imports")
    message = "La importación y exportación ZIP requiere el servicio Linux/Docker con sus workers configurados. La carga de audios y GCS sigue disponible."
    @router.get("/access")
    def access():
        return {"available": False, "development_mode": False, "authenticated": False,
                "reason": message}
    @router.api_route("", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    @router.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
    def unavailable(path: str = ""):
        raise HTTPException(503, message, headers={"Cache-Control": "no-store"})
    return router
