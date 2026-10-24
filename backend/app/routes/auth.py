from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db
from app.models.user import Usuario
from app.services.web_sessions import (
    current_web_user, trusted_web_request, start_session, end_session, web_administrator, authenticate_web_user,
)
from app.services import accounts
from app.services import access_limits
from app.services.security_audit import record_event

class WebAuthRoute(APIRoute):
    """Keep credentials and user profiles out of caches, including error paths."""
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


router = APIRouter(prefix="/api/auth", tags=["Autenticación y Sesión"], route_class=WebAuthRoute)


# ============================================================================
# ESQUEMAS PYDANTIC (CONTRATOS DE ENTRADA Y SALIDA)
# ============================================================================
class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=150, description="Correo electrónico del usuario")
    password: str = Field(..., description="Contraseña en texto plano")

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


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nombre_completo: str
    rol: str
    activo: bool
    creado_en: Optional[datetime] = None
    ultimo_acceso: Optional[datetime] = None


class LoginResponse(BaseModel):
    user: UserResponse


class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=150, pattern=r"^[^\s@]+@[^\s@]+$",
                       description="Correo electrónico institucional o de investigación")
    password: str = Field(..., min_length=12, max_length=1024, description="Contraseña del usuario (mínimo 12 caracteres)")
    nombre_completo: str = Field(..., min_length=2, max_length=150, description="Nombre y apellido del usuario")
    rol: Optional[str] = Field("investigador", description="Rol del usuario: 'administrador' o 'investigador'")

    @field_validator("email", "nombre_completo", mode="before")
    @classmethod
    def strip_identity(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def nonblank_password(cls, value):
        if not value.strip():
            raise ValueError("Contraseña vacía")
        return value


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(..., min_length=1, max_length=1024)
    new_password: str = Field(..., min_length=12, max_length=1024)

    @field_validator("new_password")
    @classmethod
    def nonblank_password(cls, value):
        if not value.strip():
            raise ValueError("Contraseña vacía")
        return value


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(..., min_length=43, max_length=43)
    new_password: str = Field(..., min_length=12, max_length=1024)

    @field_validator("new_password")
    @classmethod
    def nonblank_password(cls, value):
        if not value.strip():
            raise ValueError("Contraseña vacía")
        return value


# ============================================================================
# ENDPOINTS DE AUTENTICACIÓN (CU_SES_01 / CU_ADM_01)
# ============================================================================
@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Iniciar sesión web (CU_SES_01)",
)
def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Valida credenciales contra la base de datos PostgreSQL.
    Si son correctas y el usuario está activo, actualiza el timestamp de último acceso
    y establece una sesión opaca revocable mediante cookie HttpOnly.
    """
    config = trusted_web_request(request)
    access_limits.admit(db, [("login_account", req.email.strip().lower()),
                             ("login_peer", access_limits.observed_peer(request))])
    user = authenticate_web_user(db=db, email=req.email, password=req.password)
    if not user:
        record_event(db, "session.login", "denied")
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas o cuenta de usuario desactivada.",
        )

    start_session(db, user, request, response, config)

    return LoginResponse(
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Consultar perfil del usuario autenticado (CU_SES_02)",
)
def get_current_user_profile(current_user: Usuario = Depends(current_web_user)):
    """
    Retorna la información del usuario autenticado mediante sesión web.
    Permite validar la sesión activa en el frontend Next.js.
    """
    return UserResponse.model_validate(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Cerrar sesión web")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(request, response, db)


@router.post("/change-password", status_code=204)
def change_own_password(req: ChangePasswordRequest, request: Request, response: Response,
                        db: Session = Depends(get_db), user: Usuario = Depends(current_web_user)):
    config = trusted_web_request(request)
    accounts.change_password(db, request, user.id, req.current_password, req.new_password)
    response.delete_cookie(config.cookie, path="/", secure=config.secure, httponly=True, samesite="strict")


@router.post("/reset-password", status_code=204)
def reset_account_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    trusted_web_request(request)
    access_limits.admit(db, [("recovery_peer", access_limits.observed_peer(request))])
    accounts.reset_password(db, req.token, req.new_password)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un nuevo usuario (CU_ADM_01)",
)
def register_user(req: RegisterRequest, request: Request, db: Session = Depends(get_db),
                  administrator: Usuario = Depends(web_administrator)):
    """
    Crea una nueva cuenta de usuario en el sistema.
    Valida unicidad de correo y asignación de rol válido ('administrador' o 'investigador').
    """
    rol_clean = (req.rol or "investigador").strip().lower()
    if rol_clean not in ("administrador", "investigador"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rol no permitido: '{req.rol}'. Solo se permite 'administrador' o 'investigador'.",
        )

    try:
        user = accounts.create_account(
            db=db,
            request=request,
            actor_id=administrator.id,
            email=req.email,
            password=req.password,
            nombre_completo=req.nombre_completo,
            rol=rol_clean,
        )
        return UserResponse.model_validate(user)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
