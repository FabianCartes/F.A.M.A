"""Bounded administrative observation and maintenance, without productive lifespan."""
from fastapi import APIRouter, Depends, Query, Body, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import WebAuthRoute
from app.services.web_sessions import web_administrator
from app.services.security_audit import recent_events
from app.services.security_maintenance import cleanup
from app.models.user import Usuario

router = APIRouter(prefix="/api/security", tags=["Seguridad"], route_class=WebAuthRoute,
                   dependencies=[Depends(web_administrator)])


class SecurityEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    occurred_at: int
    action: str
    outcome: str
    actor_id: int | None
    subject_user_id: int | None
    dataset_id: int | None


class AuditPage(BaseModel):
    events: list[SecurityEvent]
    next_before_id: int | None


@router.get("/audit", response_model=AuditPage)
def list_audit(limit: int = Query(50, ge=1, le=100),
               before_id: int | None = Query(None, ge=1, le=2 ** 63 - 1), db: Session = Depends(get_db)):
    return recent_events(db, limit, before_id)


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_size: int = Field(500, ge=1, le=1000, strict=True)


class CleanupResponse(BaseModel):
    batch_size: int
    deleted: dict[str, int]
    has_more: bool


@router.post("/cleanup", response_model=CleanupResponse)
def cleanup_security(request: Request, options: CleanupRequest | None = Body(None),
                      db: Session = Depends(get_db), actor: Usuario = Depends(web_administrator)):
    return cleanup(db, request, actor.id, options.batch_size if options is not None else 500)
