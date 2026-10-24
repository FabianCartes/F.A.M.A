"""Authenticated, dataset-authorized checkpoint copy operations."""
from fastapi import APIRouter, Depends, HTTPException

from app.models.training import Modelo
from app.routes.auth import WebAuthRoute
from app.services.access import resource_access, ResourceAccess
from app.services.checkpoints import CheckpointCopies, CheckpointConflict

router = APIRouter(prefix='/api/training/models/{model_id}/checkpoint',
                   tags=['Respaldo de modelos'], route_class=WebAuthRoute)


def copies(model_id: int, access: ResourceAccess = Depends(resource_access)):
    model = access.query(Modelo).filter_by(id_modelo=model_id).one_or_none()
    if model is None:
        raise HTTPException(404, 'Modelo no encontrado o no asignado.')
    from app.main import training_service
    try:
        return CheckpointCopies(model, training_service.checkpoints_dir)
    except CheckpointConflict as error:
        raise HTTPException(409, str(error)) from None
    except Exception:
        raise HTTPException(503, 'No se pudo preparar el acceso a las copias del modelo.') from None


def run(operation):
    try:
        return operation()
    except CheckpointConflict as error:
        raise HTTPException(409, str(error)) from None
    except Exception:
        raise HTTPException(503, 'No se pudo comprobar o transferir el checkpoint. Revisa GCS, la conexión y el espacio local; puedes reintentar.') from None


@router.get('')
def checkpoint_status(store: CheckpointCopies = Depends(copies)):
    return run(store.status)


@router.post('/backup')
def backup_checkpoint(store: CheckpointCopies = Depends(copies)):
    return run(store.backup)


@router.post('/restore')
def restore_checkpoint(store: CheckpointCopies = Depends(copies)):
    return run(store.restore)
