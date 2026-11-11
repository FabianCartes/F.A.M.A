"""Add the optional shared dataset description; additive and nullable (ADR 0079)."""
from alembic import op
import sqlalchemy as sa
revision = "0006_dataset_description"
down_revision = "0005_triad_composition"

def upgrade():
    op.add_column("conjunto_datos", sa.Column("descripcion", sa.String(length=2000), nullable=True))

def downgrade():
    raise RuntimeError("La reversión destructiva requiere recuperación explícita del operador")
