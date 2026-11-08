"""Synchronous owner-scoped HTTP bridge to completed T1/T2 resources.

No queue or retry: an interrupted client must explicitly reselect a resource.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool
from sqlalchemy import inspect

from app.database import get_db
from app.services.imported_identity import imported_user

class BoundedPreparationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            if request.method == 'POST':
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise HTTPException(413, detail={'code': 'request_budget',
                            'message': 'JSON excede 8 MiB. Reduzca el mapa o la procedencia antes de solicitar preparación.'})
                    chunks.append(chunk)
                # FastAPI parses the same bounded bytes; it must not consume the stream again.
                request._body = b''.join(chunks)
            return await handler(request)
        return bounded


router = APIRouter(prefix="/api/training/imported", tags=["imported training"], route_class=BoundedPreparationRoute)
security = HTTPBearer(auto_error=False)


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=64)
    reuse_current: StrictBool = False


class PreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: list[dict[str, Any]] = Field(max_length=20000)
    provenance: dict[str, Any]
    seed: StrictInt = Field(ge=0, le=2**32 - 1)
    profile: dict[str, Any]


def get_user(request: Request, response: Response,
             credentials: HTTPAuthorizationCredentials | None = Depends(security),
             db=Depends(get_db)):
    return imported_user(request, response, credentials, db)


def get_preparations():
    from app.database import SessionLocal
    from app.services.imported_training_source import configured_sources
    try:
        return configured_sources(SessionLocal).preparations
    except Exception:
        raise HTTPException(503, detail={"code": "source_configuration_required",
            "message": "Fuente no configurada. Solicite configurar almacenamiento local al operador."}) from None


def preflight(preparations):
    """Read-only schema check; never invoke a migrator or create missing tables."""
    from app.models.training_snapshot import TrainingSnapshot, SnapshotMember
    from app.models.dataset_import import ImportedDataset
    from app.models.dataset_import_metadata import DatasetMember
    from app.models.dataset_import_job import ImportJobGate
    from scripts.migrate_imported_training_source import validate_imported_sources
    try:
        with preparations.snapshots.sessions() as db:
            engine = db.get_bind()
            validate_imported_sources(engine)
            inspector = inspect(engine)
            for table in (TrainingSnapshot.__table__, SnapshotMember.__table__,
                          ImportedDataset.__table__, DatasetMember.__table__, ImportJobGate.__table__):
                columns = {c['name']: c for c in inspector.get_columns(table.name)}
                if any(c.name not in columns or columns[c.name]['type']._type_affinity is not c.type._type_affinity
                       or columns[c.name]['nullable'] != c.nullable for c in table.columns):
                    raise RuntimeError('Incompatible schema')
                if set(inspector.get_pk_constraint(table.name)['constrained_columns']) != {c.name for c in table.primary_key}:
                    raise RuntimeError('Incompatible schema')
                expected_foreign = {(tuple(c.name for c in fk.columns), tuple(e.target_fullname for e in fk.elements)) for fk in table.foreign_key_constraints}
                actual_foreign = {(tuple(f['constrained_columns']), tuple(f['referred_table'] + '.' + c for c in f['referred_columns'])) for f in inspector.get_foreign_keys(table.name)}
                if actual_foreign != expected_foreign:
                    raise RuntimeError('Incompatible foreign keys')
                expected_unique = {tuple(c.name for c in constraint.columns) for constraint in table.constraints if constraint.__class__.__name__ == 'UniqueConstraint'}
                actual_unique = {tuple(c['column_names']) for c in inspector.get_unique_constraints(table.name)}
                if not expected_unique.issubset(actual_unique):
                    raise RuntimeError('Incompatible uniqueness')
    except Exception:
        raise HTTPException(503, detail={"code": "source_migration_required",
            "message": "Esquema no disponible. Solicite al operador el preflight y la migración explícita; no reintente automáticamente."}) from None


def unavailable():
    return HTTPException(404, detail={"code": "source_unavailable", "message": "Fuente importada no disponible. Vuelva a seleccionar una fuente propia verificada."})


def descriptor(snapshot):
    return {**{k: v for k, v in snapshot.items() if k != 'owner_id'}, 'state': 'ready'}


def public_preparation(manifest):
    # Do not expose filesystem references or owner internals from the persisted manifest.
    return {**{key: manifest[key] for key in ('version_id', 'snapshot_id', 'profile',
        'class_to_index', 'warnings', 'seed')}, 'state': 'ready'}


@router.post('/snapshots', status_code=201)
def create_snapshot(body: SnapshotRequest, user=Depends(get_user), preparations=Depends(get_preparations)):
    preflight(preparations)
    try:
        if body.reuse_current:
            current = preparations.snapshots.current(user.id, body.dataset_id)
            if current is not None:
                preparations.snapshots.admit_preparation(user.id, current['id'])
                return descriptor(current)
        return descriptor(preparations.snapshots.create(user.id, body.dataset_id))
    except HTTPException as error:
        if error.status_code == 503:
            raise
        raise unavailable() from None
    except Exception:
        raise unavailable() from None


@router.get('/snapshots/{snapshot_id}')
def get_snapshot(snapshot_id: str, user=Depends(get_user), preparations=Depends(get_preparations)):
    preflight(preparations)
    try:
        snapshot = preparations.snapshots.get(user.id, snapshot_id)
        for _member, _chunk in preparations.snapshots.iter_verified(user.id, snapshot_id):
            pass
        return descriptor(snapshot)
    except Exception:
        raise unavailable() from None


@router.get('/snapshots/{snapshot_id}/members')
def get_members(snapshot_id: str, user=Depends(get_user), preparations=Depends(get_preparations)):
    preflight(preparations)
    try:
        snapshot = preparations.snapshots.get(user.id, snapshot_id)
        if snapshot['file_count'] > 20000:
            raise ValueError('Member budget')
        members = {}
        for member, _ in preparations.snapshots.iter_verified(user.id, snapshot_id):
            members[member['member_id']] = {k: member[k] for k in
                ('member_id', 'class_name', 'original_path', 'size_bytes', 'sha256')}
        if len(members) != snapshot['file_count']:
            raise ValueError('Membership mismatch')
        return {'snapshot_id': snapshot_id, 'members': list(members.values())}
    except Exception:
        raise unavailable() from None


@router.post('/snapshots/{snapshot_id}/preparations', status_code=201)
def create_preparation(snapshot_id: str, body: PreparationRequest,
                       user=Depends(get_user), preparations=Depends(get_preparations)):
    from training.imported_dataset_preparation import PreparationError
    preflight(preparations)
    try:
        preparations.snapshots.get(user.id, snapshot_id)
    except Exception:
        raise unavailable() from None
    try:
        preparations.snapshots.admit_preparation(user.id, snapshot_id)
        manifest = preparations.create(user.id, snapshot_id, **body.model_dump())
        return public_preparation(manifest)
    except HTTPException as error:
        if error.status_code == 503:
            raise
        raise unavailable() from None
    except PreparationError as error:
        if error.code in ('source_unavailable', 'invalid_identity'):
            raise unavailable() from None
        raise HTTPException(422, detail={'code': error.code, 'message': str(error), 'state': 'failed'}) from None
    except Exception:
        raise unavailable() from None


@router.get('/snapshots/{snapshot_id}/preparations/{version}')
def get_preparation(snapshot_id: str, version: str,
                    user=Depends(get_user), preparations=Depends(get_preparations)):
    preflight(preparations)
    try:
        manifest = preparations.get(user.id, snapshot_id, version)
        # T2 get verifies indices; a ready HTTP resource also requires intact T1 audio.
        for _member, _chunk in preparations.snapshots.iter_verified(user.id, snapshot_id):
            pass
        return public_preparation(manifest)
    except Exception:
        raise unavailable() from None
