"""Administrative grant management, no implicit resource ownership."""
from typing import Annotated
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response, Request, Query, Path
from pydantic import BaseModel
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dataset import ConjuntoDatos
from app.models.dataset_access import AsignacionDataset
from app.models.user import Usuario
from app.routes.auth import WebAuthRoute
from app.services.web_sessions import web_administrator
from app.services.web_sessions import current_web_user
from app.services import dataset_catalogue
from app.services.accounts import account_mutation
from app.services.security_audit import record_event

router = APIRouter(prefix="/api/access", tags=["Asignaciones"], route_class=WebAuthRoute,
                   dependencies=[Depends(web_administrator)])
catalogue_router = APIRouter(prefix="/api/datasets", tags=["Catálogo"], route_class=WebAuthRoute,
                             dependencies=[Depends(current_web_user)])


@catalogue_router.get("/catalogue")
def discover_datasets(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=2 ** 31 - 1),
                      db: Session = Depends(get_db), actor: Usuario = Depends(current_web_user)):
    return dataset_catalogue.catalogue(db, actor, limit, offset)


@catalogue_router.post("/{dataset_id}/requests")
def request_dataset(dataset_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)], request: Request,
                    db: Session = Depends(get_db), actor: Usuario = Depends(current_web_user)):
    actor = account_mutation(db, request, actor.id)
    return dataset_catalogue.request_access(db, actor, dataset_id)


@router.get("/requests")
def pending_requests(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=2 ** 31 - 1),
                     state: Literal["pending", "approved", "rejected", "all"] = "pending",
                     db: Session = Depends(get_db)):
    return dataset_catalogue.requests_inbox(db, limit, offset, state)


class RequestDecision(BaseModel):
    decision: Literal["approve", "reject"]


@router.post("/requests/{user_id}/{dataset_id}/decision")
def decide_dataset_request(user_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)],
                           dataset_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)],
                           body: RequestDecision, request: Request, db: Session = Depends(get_db),
                           actor: Usuario = Depends(web_administrator)):
    actor = account_mutation(db, request, actor.id, administrator=True)
    return dataset_catalogue.decide_request(db, actor, user_id, dataset_id, body.decision)


def resources(db, user_id, dataset_id):
    if db.get(Usuario, user_id) is None or db.get(ConjuntoDatos, dataset_id) is None:
        raise HTTPException(404, "Usuario o dataset no encontrado.")


class AssignedDataset(BaseModel):
    dataset_id: int
    name: str
    assigned: bool


class AssignmentCatalogue(BaseModel):
    user_id: int
    datasets: list[AssignedDataset]
    total: int
    limit: int
    offset: int


@router.get("/users/{user_id}/datasets", response_model=AssignmentCatalogue)
def list_assignments(user_id: Annotated[int, Path(ge=1, le=2 ** 31 - 1)],
                     limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0, le=2 ** 31 - 1), db: Session = Depends(get_db)):
    """Registered identities and grants only; never enumerate cloud or local files."""
    if db.get(Usuario, user_id) is None:
        raise HTTPException(404, "Usuario no encontrado.")
    rows = (db.query(ConjuntoDatos.id_conjunto_datos, ConjuntoDatos.nombre, AsignacionDataset.id_usuario)
            .outerjoin(AsignacionDataset, and_(
                AsignacionDataset.id_conjunto_datos == ConjuntoDatos.id_conjunto_datos,
                AsignacionDataset.id_usuario == user_id))
            .order_by(ConjuntoDatos.id_conjunto_datos).offset(offset).limit(limit).all())
    return {"user_id": user_id,
            "datasets": [{"dataset_id": identifier, "name": name, "assigned": assigned_user is not None}
                         for identifier, name, assigned_user in rows],
            "total": db.query(ConjuntoDatos).count(), "limit": limit, "offset": offset}


@router.get("/users/{user_id}/datasets/{dataset_id}")
def get_assignment(user_id: int, dataset_id: int, db: Session = Depends(get_db)):
    resources(db, user_id, dataset_id)
    return {"user_id": user_id, "dataset_id": dataset_id,
            "assigned": db.get(AsignacionDataset, (user_id, dataset_id)) is not None}


@router.put("/users/{user_id}/datasets/{dataset_id}")
def grant_assignment(user_id: int, dataset_id: int, request: Request, db: Session = Depends(get_db),
                     actor: Usuario = Depends(web_administrator)):
    account_mutation(db, request, actor.id, administrator=True)
    resources(db, user_id, dataset_id)
    if db.get(AsignacionDataset, (user_id, dataset_id)) is None:
        db.add(AsignacionDataset(id_usuario=user_id, id_conjunto_datos=dataset_id))
        record_event(db, "assignment.granted", "success", actor_id=actor.id,
                     subject_user_id=user_id, dataset_id=dataset_id)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if db.get(AsignacionDataset, (user_id, dataset_id)) is None:
                raise
    return {"user_id": user_id, "dataset_id": dataset_id, "assigned": True}


@router.delete("/users/{user_id}/datasets/{dataset_id}", status_code=204)
def revoke_assignment(user_id: int, dataset_id: int, request: Request, db: Session = Depends(get_db),
                      actor: Usuario = Depends(web_administrator)):
    account_mutation(db, request, actor.id, administrator=True)
    resources(db, user_id, dataset_id)
    deleted = db.query(AsignacionDataset).filter_by(id_usuario=user_id, id_conjunto_datos=dataset_id).delete()
    if deleted:
        record_event(db, "assignment.revoked", "success", actor_id=actor.id,
                     subject_user_id=user_id, dataset_id=dataset_id)
    db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
