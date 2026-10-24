"""Dataset-scoped preview, publication and retrieval of partition versions."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dataset import ConjuntoDatos
from app.routes.auth import WebAuthRoute
from app.services.access import ResourceAccess, resource_access
from app.services.partitions import DatasetPartitions, PartitionError

router = APIRouter(prefix="/api/training/datasets/{dataset_name}/partitions", tags=["Particiones"], route_class=WebAuthRoute)


class PartitionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_percent: int = Field(default=20, ge=10, le=40, strict=True)
    seed: int = Field(default=42, ge=0, le=2**31 - 1, strict=True)


class SavePartition(PartitionPolicy):
    preview_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_warnings: bool = False


def partitions(dataset_name: str, db: Session = Depends(get_db), access: ResourceAccess = Depends(resource_access)):
    access.require_dataset(dataset_name)
    dataset = db.query(ConjuntoDatos).filter_by(nombre=dataset_name).one_or_none()
    if dataset is None or dataset.nombre != dataset_name:
        raise HTTPException(404, "Dataset no encontrado o no asignado.")
    # Dataset identities must never become arbitrary filesystem paths.
    from app.services.ingestion import ingestion_service, IngestionValidationError
    try:
        ingestion_service.validate_dataset_names([dataset_name])
    except IngestionValidationError:
        raise HTTPException(422, "Nombre de dataset inválido.") from None
    return DatasetPartitions(dataset, db)


def run(operation):
    try:
        return operation()
    except PartitionError as error:
        raise HTTPException(409, str(error)) from None
    except OSError:
        raise HTTPException(503, "No se pudo leer o guardar la versión de particiones en este equipo.") from None


@router.get("")
def list_partitions(store: DatasetPartitions = Depends(partitions)):
    return {"versions": run(store.versions)}


@router.post("/preview")
def preview_partitions(policy: PartitionPolicy, store: DatasetPartitions = Depends(partitions)):
    return run(lambda: store.preview(policy.validation_percent, policy.seed))


@router.post("")
def save_partitions(policy: SavePartition, store: DatasetPartitions = Depends(partitions), access: ResourceAccess = Depends(resource_access)):
    return run(lambda: store.save(policy.validation_percent, policy.seed, policy.preview_version,
                                 policy.acknowledge_warnings, access.user.id))


@router.get("/{version}")
def read_partition(version: str, store: DatasetPartitions = Depends(partitions)):
    return run(lambda: store.read(version))
