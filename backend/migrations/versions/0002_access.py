"""Sesiones, asignaciones, recuperación, cuotas y auditoría."""
from alembic import op
from migrations.schema_0002 import metadata, ACCESS_TABLES

revision = "0002_access"
down_revision = "0001_core"


def upgrade():
    metadata.create_all(op.get_bind(), tables=[metadata.tables[name] for name in ACCESS_TABLES], checkfirst=False)


def downgrade():
    raise RuntimeError("La reversión destructiva requiere un procedimiento de recuperación del operador")
