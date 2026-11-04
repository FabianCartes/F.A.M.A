"""Explicit additive migration. Never invoked automatically by application startup."""
from sqlalchemy import inspect
from app.models.dataset_import import ImportedDataset
from app.models.dataset_import_metadata import DatasetMember
from app.models.dataset_import_job import ImportJobGate
from app.models.training_snapshot import TrainingSnapshot, SnapshotMember


def migrate_snapshots(engine, *, writers_stopped=False):
    """Operator must stop all writers before calling; no implicit DB selection."""
    if writers_stopped is not True:
        raise RuntimeError("All writers must be stopped explicitly")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("Unsupported schema dialect")
    with engine.begin() as connection:
        inspector = inspect(connection)
        targets = [TrainingSnapshot.__table__, SnapshotMember.__table__]
        prerequisites = [ImportedDataset.__table__, DatasetMember.__table__, ImportJobGate.__table__]
        for table in prerequisites + targets:
            if not inspector.has_table(table.name):
                if table in prerequisites:
                    raise RuntimeError("Required import schema absent")
                continue
            actual = {c["name"]: c for c in inspector.get_columns(table.name)}
            for column in table.columns:
                candidate = actual.get(column.name)
                if candidate is None or candidate["type"]._type_affinity is not column.type._type_affinity:
                    raise RuntimeError("Incompatible schema")
            if table in targets:
                primary = inspector.get_pk_constraint(table.name)["constrained_columns"]
                if set(primary) != {c.name for c in table.primary_key}:
                    raise RuntimeError("Incompatible schema primary key")
                if any(actual[c.name]["nullable"] != c.nullable for c in table.columns):
                    raise RuntimeError("Incompatible schema nullability")
        for table in targets:
            table.create(connection, checkfirst=True)
