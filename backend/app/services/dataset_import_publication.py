"""Publish a confirmed local import into the shared catalog, idempotently.

Runs after the local confirmation commits and outside any database lock. It
reuses ``IngestionService.upload_files_to_gcs`` in bounded batches: objects are
created with ``if_generation_match=0`` and identical existing objects are
skipped, so a retry after a partial failure uploads only what is missing.
"""
import os
import shutil
from itertools import groupby
from pathlib import Path, PurePosixPath

from app.models.dataset import ConjuntoDatos
from app.models.dataset_access import AsignacionDataset
from app.models.dataset_import import DatasetImport, ImportedDataset
from app.models.dataset_import_metadata import ImportFile
from app.services.dataset_imports import digest_file


class PublicationFailed(RuntimeError):
    """The import stays confirmed locally; retrying the confirm job republishes."""


def publish_import(ingestion, sessions, import_root, import_id):
    with sessions() as db:
        source = db.get(DatasetImport, import_id)
        if not source.dataset_id:
            return
        owner = source.owner_id
        name = db.get(ImportedDataset, source.dataset_id).name
        files = [(row.class_name, PurePosixPath(row.relative_path).name, row.stored_name, row.sha256, row.size_bytes)
                 for row in db.query(ImportFile).filter_by(import_id=import_id, duplicate=False, existing=False)
                 .order_by(ImportFile.class_name, ImportFile.ordinal)]
    _claim(ingestion, sessions, name, owner)
    objects = Path(import_root) / "objects" / import_id
    _, batch_limit = ingestion.get_upload_limits()
    for class_name, group in groupby(files, key=lambda item: item[0]):
        batch, size = [], 0
        for item in group:
            if batch and size + item[4] > batch_limit:
                _upload(ingestion, sessions, objects, name, class_name, owner, batch)
                batch, size = [], 0
            batch.append(item)
            size += item[4]
        if batch:
            _upload(ingestion, sessions, objects, name, class_name, owner, batch)
    for class_name, filename, stored_name, sha256, _ in files:
        _copy_local(objects / stored_name, ingestion.local_base_dir / name / class_name / filename, sha256)


def _claim(ingestion, sessions, name, owner):
    """Own the shared name before any upload; the unique name makes the claim atomic.

    A later concurrent creator finds this row instead of creating its own, so
    uploads never land in another user's dataset and no grant is self-issued.
    """
    from sqlalchemy.exc import IntegrityError
    with sessions() as db:
        shared = db.query(ConjuntoDatos).filter_by(nombre=name).first()
        if shared is None:
            shared = ConjuntoDatos(nombre=name, ruta_gcp=f"gs://{ingestion.bucket_name}/datasets/{name}/",
                                   estado="subiendo", id_usuario_carga=owner, tamano_total_bytes=0, cantidad_audios=0)
            db.add(shared)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                shared = db.query(ConjuntoDatos).filter_by(nombre=name).first()
        assigned = db.get(AsignacionDataset, (owner, shared.id_conjunto_datos)) is not None
        if shared.id_usuario_carga != owner and not assigned:
            raise PublicationFailed("name_taken")
        if not assigned:
            db.add(AsignacionDataset(id_usuario=owner, id_conjunto_datos=shared.id_conjunto_datos))
        db.commit()


def _upload(ingestion, sessions, objects, name, class_name, owner, batch):
    payload = [(filename, (objects / stored_name).read_bytes()) for _, filename, stored_name, _, _ in batch]
    with sessions() as db:
        result = ingestion.upload_files_to_gcs(payload, name, class_name, db=db, actor_id=owner)
    if result["failed"] or not result["db_persisted"]:
        raise PublicationFailed("upload_failed")


def _copy_local(source, target, sha256):
    if target.exists():
        if digest_file(target) != sha256:
            raise PublicationFailed("local_conflict")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.partial")
    shutil.copyfile(source, partial)
    os.replace(partial, target)
