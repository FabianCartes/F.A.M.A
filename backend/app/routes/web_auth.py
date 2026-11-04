"""Existing opaque browser session, isolated from the public Bearer contract.

Adapted from aa53e09a9b935f752b01fe464cbc1a5bd10556c0; no installer,
account administration or global resource policy is imported here.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import access_limits
from app.services.security_audit import record_event
from app.services.web_sessions import (
    authenticate_web_user, current_web_user, start_session, trusted_web_request, end_session, ensure_web_schema,
)


class WebAuthRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                response = await handler(request)
            except HTTPException as error:
                response = JSONResponse({"detail": error.detail}, status_code=error.status_code,
                                        headers=error.headers)
            except RequestValidationError:
                response = JSONResponse({"detail": "Solicitud de autenticación inválida."}, status_code=422)
            except SQLAlchemyError:
                response = JSONResponse({"detail": "Servicio de autenticación temporalmente no disponible."},
                                        status_code=503)
            response.headers["Cache-Control"] = "no-store"
            return response
        return handle


router = APIRouter(prefix="/web", tags=["Sesión web"], route_class=WebAuthRoute)


class WebLoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email", mode="before")
    @classmethod
    def canonical_identifier(cls, value):
        if isinstance(value, str):
            value = value.strip().lower()
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise ValueError("Identificador inválido") from None
        return value


def public_user(user):
    # Import lazily to keep the existing Bearer schema as the single contract.
    from app.routes.auth import UserResponse
    return UserResponse.model_validate(user)


@router.post("/login", summary="Iniciar sesión web revocable (no entrega JWT)")
def login(req: WebLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    config = trusted_web_request(request)
    ensure_web_schema(db)
    access_limits.admit(db, [("login_account", req.email),
                             ("login_peer", access_limits.observed_peer(request))])
    user = authenticate_web_user(db, req.email, req.password)
    if not user:
        record_event(db, "session.login", "denied")
        db.commit()
        raise HTTPException(401, "Credenciales inválidas o cuenta de usuario desactivada.")
    start_session(db, user, request, response, config)
    return {"user": public_user(user)}


@router.get("/me", summary="Consultar sesión web activa")
def me(user=Depends(current_web_user)):
    return public_user(user)


@router.post("/logout", status_code=204, summary="Revocar la sesión web del navegador")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(request, response, db)
