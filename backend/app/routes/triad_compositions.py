"""Dataset-authorized read and weight revision of standard triad compositions."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.training import TriadWeightsRevisionRequest
from app.schemas.triad_composition import TriadComponent, TriadCompositionResponse
from app.services.access import ResourceAccess, resource_access
from app.services.registry import ModelRegistry, get_model_registry
from app.services.triad_compositions import (
    TriadCompositionConflict, TriadCompositionError, activate_composition, component_ids, component_weights, composition_query,
    get_composition, is_latest, revise_weights, triad_model_key,
)

router = APIRouter(prefix="/api/triad-compositions", tags=["Tríadas combinadas"])


def _describe(db: Session, composition) -> TriadCompositionResponse:
    return TriadCompositionResponse(
        id=composition.id, model_id=triad_model_key(composition.id), dataset_id=composition.dataset_id,
        partition_version=composition.partition_version, job_id=composition.job_id,
        version=composition.version, previous_id=composition.previous_id,
        latest=is_latest(db, composition), active=bool(composition.activo),
        components=[TriadComponent(id_modelo=model_id, catalogue_id=f"fama_trained_model_{model_id}", weight=weight)
                    for model_id, weight in zip(component_ids(composition), component_weights(composition))],
        author_id=composition.author_id, created_at=composition.created_at)


def _refresh_registry(registry: ModelRegistry, db: Session) -> None:
    """Re-publish so the default follows the persisted activation; same tolerance as model activation."""
    try:
        registry.register_from_db(db)
    except Exception as error:
        print(f"[TriadCompositions] Advertencia al sincronizar registry: {error}")


def _authorized(access: ResourceAccess, composition_id: int):
    # Authorization is the dataset assignment, never the author of the composition.
    composition = composition_query(access).filter_by(id=composition_id).first()
    if composition is None:
        raise HTTPException(404, "Recurso no encontrado o no asignado.")
    return composition


@router.get("/{composition_id}", response_model=TriadCompositionResponse,
            summary="Consultar una versión de composición de tríada")
def read_composition(composition_id: int, response: Response, db: Session = Depends(get_db),
                     access: ResourceAccess = Depends(resource_access)):
    response.headers["Cache-Control"] = "no-store"
    return _describe(db, _authorized(access, composition_id))


@router.post("/{composition_id}/weights", response_model=TriadCompositionResponse, status_code=201,
             summary="Revisar los pesos de la última versión de una tríada sin reentrenar")
def revise_composition_weights(composition_id: int, body: TriadWeightsRevisionRequest, request: Request,
                               response: Response, db: Session = Depends(get_db),
                               access: ResourceAccess = Depends(resource_access),
                               registry: ModelRegistry = Depends(get_model_registry)):
    response.headers["Cache-Control"] = "no-store"
    composition = _authorized(access, composition_id)
    try:
        revision = revise_weights(db, composition, body.weights, author_id=access.user.id)
    except TriadCompositionError as error:
        raise HTTPException(422, str(error)) from None
    except TriadCompositionConflict as error:
        raise HTTPException(409, str(error)) from None
    if revision.activo:
        _refresh_registry(registry, db)
    return _describe(db, revision)


@router.post("/{composition_id}/activate", response_model=TriadCompositionResponse,
             summary="Activar la última versión de una tríada como modelo por defecto (solo administrador)")
def activate_triad_composition(composition_id: int, response: Response, db: Session = Depends(get_db),
                               access: ResourceAccess = Depends(resource_access),
                               registry: ModelRegistry = Depends(get_model_registry)):
    response.headers["Cache-Control"] = "no-store"
    access.require_administrator()
    composition = get_composition(db, composition_id)
    if composition is None:
        raise HTTPException(404, "Recurso no encontrado o no asignado.")
    try:
        activate_composition(db, composition)
    except TriadCompositionConflict as error:
        raise HTTPException(409, str(error)) from None
    _refresh_registry(registry, db)
    return _describe(db, composition)
