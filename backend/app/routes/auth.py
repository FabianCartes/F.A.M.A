from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import Usuario
from app.services.auth import (
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
)

router = APIRouter(prefix="/api/auth", tags=["Autenticación y Sesión"])


# ============================================================================
# ESQUEMAS PYDANTIC (CONTRATOS DE ENTRADA Y SALIDA)
# ============================================================================
class LoginRequest(BaseModel):
    email: str = Field(..., description="Correo electrónico del usuario")
    password: str = Field(..., description="Contraseña en texto plano")


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
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class RegisterRequest(BaseModel):
    email: str = Field(..., description="Correo electrónico institucional o de investigación")
    password: str = Field(..., min_length=6, description="Contraseña del usuario (mínimo 6 caracteres)")
    nombre_completo: str = Field(..., min_length=2, description="Nombre y apellido del usuario")
    rol: Optional[str] = Field("investigador", description="Rol del usuario: 'administrador' o 'investigador'")


# ============================================================================
# ENDPOINTS DE AUTENTICACIÓN (CU_SES_01 / CU_ADM_01)
# ============================================================================
@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Iniciar sesión y obtener token JWT (CU_SES_01)",
)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """
    Valida credenciales contra la base de datos PostgreSQL.
    Si son correctas y el usuario está activo, actualiza el timestamp de último acceso
    y genera un token Bearer JWT con vigencia de 8 horas.
    """
    user = authenticate_user(db=db, email=req.email, password=req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas o cuenta de usuario desactivada.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={
            "sub": str(user.id),
            "email": user.email,
            "rol": user.rol,
        }
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Consultar perfil del usuario autenticado (CU_SES_02)",
)
def get_current_user_profile(current_user: Usuario = Depends(get_current_user)):
    """
    Retorna la información del usuario autenticado a partir de su Bearer token.
    Permite validar la sesión activa en el frontend Next.js.
    """
    return UserResponse.model_validate(current_user)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un nuevo usuario (CU_ADM_01)",
)
def register_user(req: RegisterRequest, db: Session = Depends(get_db)):
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
        user = create_user(
            db=db,
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
