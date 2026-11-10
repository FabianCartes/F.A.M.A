"""Tablas de negocio anteriores al control de acceso web."""
from alembic import op
from migrations.schema_0002 import metadata, CORE_TABLES

revision = "0001_core"
down_revision = None


def upgrade():
    metadata.create_all(op.get_bind(), tables=[metadata.tables[name] for name in CORE_TABLES], checkfirst=False)


def downgrade():
    raise RuntimeError("La reversión destructiva requiere un procedimiento de recuperación del operador")
