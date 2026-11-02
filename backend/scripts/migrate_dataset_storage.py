"""Public maintenance functions for a new EMPTY lab; no CLI or activation.

The caller supplies an explicit engine and stops participating writers. This
module never loads ambient configuration, reconciles existing work, or creates
physical roots. Active pool provisioning remains an operational prerequisite.
"""
from sqlalchemy import func, inspect, select

from app.models.dataset_storage import STORAGE_MODELS, StorageGrant, StoragePool, StorageSchema
from app.services.dataset_storage import _verify_schema


def _inspect(conn):
    present = [inspect(conn).has_table(model.__tablename__) for model in STORAGE_MODELS]
    if not any(present):
        return dict(version=1, state="absent", schema_verified=False, pools=0, live_grants=0)
    if not all(present):
        raise ValueError("incomplete_storage_schema")
    _verify_schema(conn)
    rows = conn.execute(select(StorageSchema.__table__)).mappings().all()
    pools = conn.scalar(select(func.count()).select_from(StoragePool.__table__))
    grants = conn.scalar(select(func.count()).select_from(StorageGrant.__table__))
    if not rows and not pools and not grants:
        return dict(version=1, state="uninitialized", schema_verified=False, pools=0, live_grants=0)
    if (len(rows) != 1 or rows[0]["id"] != 1 or rows[0]["version"] != 1
            or rows[0]["state"] not in ("prepared", "active")):
        raise ValueError("incompatible_storage_version")
    return dict(version=1, state=rows[0]["state"], schema_verified=True, pools=pools,
                live_grants=conn.scalar(select(func.count()).select_from(StorageGrant.__table__).where(
                    StorageGrant.state == "live")))


def inspect_storage(engine):
    """Read-only inventory, including absent/uninitialized metadata."""
    with engine.connect() as conn:
        return dict(_inspect(conn), action="inspect")


def migrate_storage(engine, *, writers_stopped=False):
    """Prepare additive metadata ONLY for a new empty lab, never an active store."""
    if writers_stopped is not True:
        raise ValueError("stop_writers_before_storage_migration")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise ValueError("unsupported_storage_database")
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_job import ImportJob, ImportJobGate
    from scripts.migrate_dataset_import_jobs import _verify_table

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("LOCK TABLE dataset_import_job_gate IN SHARE ROW EXCLUSIVE MODE")
        _verify_table(conn, ImportJobGate.__table__)
        gates = conn.execute(select(ImportJobGate.__table__)).mappings().all()
        if len(gates) != 1 or gates[0]["id"] != 1 or gates[0]["version"] != 1:
            raise ValueError("storage_requires_verified_job_gate")
        for model in (DatasetImport, ImportedDataset, ImportJob):
            if conn.scalar(select(func.count()).select_from(model.__table__)):
                raise ValueError("storage_requires_empty_lab")
        current = _inspect(conn)
        if current["state"] == "active" or current["pools"] or current["live_grants"]:
            raise ValueError("storage_requires_empty_lab")
        if current["state"] == "absent":
            for model in STORAGE_MODELS:
                model.__table__.create(conn)
        # Retired authority is also evidence of existing work, not a new lab.
        if conn.scalar(select(func.count()).select_from(StorageGrant.__table__)):
            raise ValueError("storage_requires_empty_lab")
        if current["state"] in ("absent", "uninitialized"):
            conn.execute(StorageSchema.__table__.insert(), dict(id=1, version=1, state="prepared"))
        return dict(_inspect(conn), action="prepare")
