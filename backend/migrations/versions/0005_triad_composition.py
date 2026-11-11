"""Add the versioned standard triad composition; additive only (decision 11)."""
from alembic import op
from migrations.schema_0004 import metadata as previous
from migrations.schema_0005 import metadata
revision = "0005_triad_composition"
down_revision = "0004_integration"

def upgrade():
    bind = op.get_bind()
    for table in metadata.sorted_tables:
        if table.name not in previous.tables:
            table.create(bind, checkfirst=False)

def downgrade():
    raise RuntimeError("La reversión destructiva requiere recuperación explícita del operador")
