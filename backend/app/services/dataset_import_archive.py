"""Archive admission policy; historical lookups deliberately remain unrestricted."""
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError


def require_schema(db):
    from scripts.migrate_dataset_import_archive import validate_archive
    try:
        validate_archive(db.connection())
    except (RuntimeError, SQLAlchemyError):
        raise HTTPException(503, 'El archivo de datasets requiere migración verificada.') from None


def require_active(db, dataset):
    require_schema(db)
    if dataset.archived:
        raise HTTPException(409, 'El dataset está archivado y no admite nuevas operaciones.')


def require_import_active(db, source):
    """Caller owns the queue gate; only NEW admissions call this helper."""
    from app.models.dataset_import import ImportedDataset
    require_schema(db)
    target = source.dataset_id or source.request.get('target_id')
    query = db.query(ImportedDataset).filter_by(owner_id=source.owner_id)
    dataset = (query.filter_by(id=target).first() if target else
               query.filter_by(name=source.request['name']).first())
    if dataset is not None:
        require_active(db, dataset)


def archive(service, db, owner, identity, revision):
    from app.services.dataset_import_jobs import _gate
    try:
        _gate(db)
        require_schema(db)
        dataset = service.dataset(db, owner, identity)
        if dataset.revision != revision:
            raise HTTPException(409, 'El dataset cambió. Actualiza el catálogo antes de archivar.')
        dataset.archived = True
        db.commit()
    except BaseException:
        db.rollback()
        raise
