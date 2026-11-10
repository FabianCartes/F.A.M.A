"""Authorship of incorporations and metadata-only access requests."""
import sqlalchemy as sa
from alembic import op
from migrations.schema_0003 import metadata

revision = '0003_autonomy'
down_revision = '0002_access'


def upgrade():
    op.add_column('feedback_sync', sa.Column('incorporated_by', sa.Integer(), nullable=True))
    op.add_column('feedback_sync', sa.Column('incorporated_at', sa.DateTime(timezone=True), nullable=True))
    metadata.tables['solicitud_dataset'].create(op.get_bind(), checkfirst=False)


def downgrade():
    raise RuntimeError('La reversión destructiva requiere un procedimiento de recuperación del operador')
