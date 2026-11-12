"""Add joint evaluation attempts of standard triad compositions; additive only (ADR 0081)."""
from alembic import op
from migrations.schema_0006 import metadata as previous
from migrations.schema_0007 import metadata
revision = "0007_triad_evaluation"
down_revision = "0006_dataset_description"

def upgrade():
    bind = op.get_bind()
    for table in metadata.sorted_tables:
        if table.name not in previous.tables:
            table.create(bind, checkfirst=False)

def downgrade():
    raise RuntimeError("La reversión destructiva requiere recuperación explícita del operador")
