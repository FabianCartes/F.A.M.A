"""Explicit additive web-session schema; never executed by application startup.

The operator must stop writers and authorize a real migration separately.
Only the synthetic in-memory invocation is part of development verification.
"""
from sqlalchemy import inspect

from app.models.user import Usuario
from app.models.web_session import SesionWeb
from app.models.access_quota import CuotaAcceso
from app.models.security_audit import EventoSeguridad

TABLES = (SesionWeb.__table__, CuotaAcceso.__table__, EventoSeguridad.__table__)


def _validate(connection, *, require_all):
    inspector = inspect(connection)
    if not inspector.has_table(Usuario.__tablename__):
        raise RuntimeError("Required user schema absent")
    for table in TABLES:
        if not inspector.has_table(table.name):
            if require_all:
                raise RuntimeError("Required web-session schema absent")
            continue
        columns = {column["name"]: column for column in inspector.get_columns(table.name)}
        if (set(columns) != set(table.columns.keys()) or any(
                columns[c.name]["type"]._type_affinity is not c.type._type_affinity
                or columns[c.name]["nullable"] != c.nullable
                or getattr(columns[c.name]["type"], "length", None) != getattr(c.type, "length", None)
                for c in table.columns)):
            raise RuntimeError("Incompatible web-session schema")
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != [c.name for c in table.primary_key]:
            raise RuntimeError("Incompatible web-session primary key")
        actual_fks = {(tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]),
                       f.get("options", {}).get("ondelete")) for f in inspector.get_foreign_keys(table.name)}
        expected_fks = {(tuple(e.parent.name for e in fk.elements), fk.referred_table.name,
                         tuple(e.column.name for e in fk.elements), fk.ondelete)
                        for fk in table.foreign_key_constraints}
        if actual_fks != expected_fks:
            raise RuntimeError("Incompatible web-session foreign keys")
        actual_indexes = {(tuple(i["column_names"]), bool(i["unique"])) for i in inspector.get_indexes(table.name)}
        expected_indexes = {(tuple(c.name for c in i.columns), bool(i.unique)) for i in table.indexes}
        if not expected_indexes <= actual_indexes:
            raise RuntimeError("Incompatible web-session indexes")
        actual_checks = {" ".join(c["sqltext"].split()) for c in inspector.get_check_constraints(table.name)}
        expected_checks = {" ".join(str(c.sqltext).split()) for c in table.constraints if hasattr(c, "sqltext")}
        if not expected_checks <= actual_checks:
            raise RuntimeError("Incompatible web-session checks")


def validate_web_sessions(engine):
    """Read-only preflight before authentication changes session/quota state."""
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("Unsupported schema dialect")
    with engine.connect() as connection:
        _validate(connection, require_all=True)


def migrate_web_sessions(engine, *, writers_stopped=False):
    """Create only absent session/quota/audit tables after validating existing ones."""
    if writers_stopped is not True:
        raise RuntimeError("All writers must be stopped explicitly")
    if engine.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("Unsupported schema dialect")
    with engine.begin() as connection:
        _validate(connection, require_all=False)
        for table in TABLES:
            table.create(connection, checkfirst=True)
        _validate(connection, require_all=True)
