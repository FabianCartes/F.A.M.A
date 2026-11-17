"""Authenticated, dataset-authorized checkpoint copy operations."""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.models.training import Modelo
from app.routes.auth import WebAuthRoute
from app.services.access import resource_access, ResourceAccess
from app.services.checkpoints import CheckpointCopies, CheckpointConflict, sync_states

router = APIRouter(prefix='/api/training/models',
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


logger = logging.getLogger(__name__)


def run(operation):
    try:
        return operation()
    except CheckpointConflict as error:
        raise HTTPException(409, str(error)) from None
    except Exception:
        # The response stays generic; the cause is kept in the server log for diagnosis.
        model = getattr(getattr(operation, '__self__', None), 'model', None)
        logger.warning('Checkpoint %s failed for model %s', getattr(operation, '__name__', 'operation'),
                       getattr(model, 'id_modelo', '?'), exc_info=True)
        raise HTTPException(503, 'No se pudo comprobar o transferir el checkpoint. Revisa GCS, la conexión y el espacio local; puedes reintentar.') from None


@router.get('/{model_id}/checkpoint')
def checkpoint_status(store: CheckpointCopies = Depends(copies)):
    return run(store.status)


@router.post('/{model_id}/checkpoint/backup')
def backup_checkpoint(store: CheckpointCopies = Depends(copies)):
    return run(store.backup)


@router.post('/{model_id}/checkpoint/restore')
def restore_checkpoint(store: CheckpointCopies = Depends(copies)):
    return run(store.restore)


@router.post('/{model_id}/checkpoint/sync')
def sync_checkpoint(store: CheckpointCopies = Depends(copies)):
    return run(store.sync)


@router.get('/checkpoints/sync-status')
def checkpoint_sync_status(access: ResourceAccess = Depends(resource_access)):
    from app.main import training_service
    models = access.query(Modelo).order_by(Modelo.id_modelo).all()
    try:
        return {'models': sync_states(models, training_service.checkpoints_dir)}
    except Exception:
        raise HTTPException(503, 'No se pudo consultar el estado de sincronización en GCS.') from None
