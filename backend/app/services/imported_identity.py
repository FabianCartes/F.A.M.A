"""Resolve real imported-resource identity without changing legacy authentication."""
from fastapi import Response
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

from app.services.auth import get_current_user
from app.services.web_sessions import web_identity


SESSION_COOKIES = ("__Host-fama_session", "fama_session_dev")


def has_web_credential(request):
    return any(name in request.cookies for name in SESSION_COOKIES)


def imported_user(request, response: Response, credentials, db):
    """Legacy callers invoke this only when a resource actually requires identity."""
    bearer = None
    if request.headers.get("authorization") or not has_web_credential(request):
        # Invalid or malformed Authorization never falls back to a valid cookie.
        bearer = get_current_user(credentials, db)
    if not has_web_credential(request):
        return bearer
    try:
        return web_identity(request, response, db, expected_user_id=bearer.id if bearer else None)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Servicio de autenticación temporalmente no disponible.") from None
