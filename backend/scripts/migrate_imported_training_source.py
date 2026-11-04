"""Explicit additive migration and read-only imported-source schema preflight."""
from sqlalchemy import inspect
from app.models.training import Modelo
from app.models.training_snapshot import TrainingSnapshot
from app.models.imported_training_source import ImportedModelSource


def _validate(connection, *, require_target):
    inspector = inspect(connection)
    target = ImportedModelSource.__table__
    for table in (Modelo.__table__, TrainingSnapshot.__table__, target):
        if not inspector.has_table(table.name):
            if table is not target or require_target:
                raise RuntimeError("Required source schema absent")
            continue
        columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        if any(c.name not in columns or columns[c.name]["type"]._type_affinity is not c.type._type_affinity
               for c in table.columns):
            raise RuntimeError("Incompatible schema")
        if table is target:
            if (set(inspector.get_pk_constraint(table.name)["constrained_columns"]) != {"model_id"}
                    or any(columns[c.name]["nullable"] != c.nullable for c in table.columns)):
                raise RuntimeError("Incompatible source constraints")
            foreign = {(tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
                       for f in inspector.get_foreign_keys(table.name)}
            if foreign != {(("model_id",), "modelo", ("id_modelo",)),
                           (("snapshot_id",), "training_snapshot", ("id",))}:
                raise RuntimeError("Incompatible source foreign keys")


def validate_imported_sources(engine):
    """Read-only: fail before job assignment if required schema is absent/incompatible."""
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("Unsupported schema dialect")
    with engine.connect() as connection:
        _validate(connection, require_target=True)


def migrate_imported_sources(engine, *, writers_stopped=False):
    if writers_stopped is not True:
        raise RuntimeError("All writers must be stopped explicitly")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("Unsupported schema dialect")
    with engine.begin() as connection:
        _validate(connection, require_target=False)
        ImportedModelSource.__table__.create(connection, checkfirst=True)
