"""Administrative account interface. No physical user deletion."""
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import Usuario
from app.routes.auth import WebAuthRoute, UserResponse
from app.services.web_sessions import web_administrator
from app.services.accounts import update_account, issue_password_reset
from app.services import access_limits

router = APIRouter(prefix="/api/users", tags=["Gestión de cuentas"], route_class=WebAuthRoute,
                   dependencies=[Depends(web_administrator)])


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
    limit: int
    offset: int


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre_completo: str | None = Field(None, min_length=2, max_length=150)
    rol: Literal["administrador", "investigador"] | None = None
    activo: bool | None = Field(None, strict=True)

    @field_validator("nombre_completo", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def nonempty_changes(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Cambios explícitos no nulos requeridos")
        return self


@router.get("", response_model=UserListResponse)
def list_users(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=2 ** 31 - 1),
               db: Session = Depends(get_db)):
    return {"users": db.query(Usuario).order_by(Usuario.id).offset(offset).limit(limit).all(),
            "total": db.query(Usuario).count(), "limit": limit, "offset": offset}


@router.patch("/{user_id}", response_model=UserResponse)
def patch_user(user_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)], changes: UpdateUserRequest,
               request: Request, db: Session = Depends(get_db), actor: Usuario = Depends(web_administrator)):
    return update_account(db, request, actor.id, user_id, changes.model_dump(exclude_unset=True))


class PasswordResetResponse(BaseModel):
    reset_url: str
    expires_in: int


@router.post("/{user_id}/password-reset", response_model=PasswordResetResponse)
def create_password_reset(user_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)], request: Request,
                          db: Session = Depends(get_db), actor: Usuario = Depends(web_administrator)):
    access_limits.admit(db, [("recovery_target", str(user_id)), ("recovery_issuer", str(actor.id))])
    return issue_password_reset(db, request, actor.id, user_id)
