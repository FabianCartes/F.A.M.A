"""Frozen schema 0005: 0004 plus the versioned standard triad composition."""
import sqlalchemy as sa
from migrations.schema_0004 import BOOTSTRAP_TABLES, metadata as previous

metadata = sa.MetaData()
for table in previous.sorted_tables:
    table.to_metadata(metadata)

sa.Table('triad_composition', metadata,
    sa.Column('id', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('dataset_id', sa.Integer(), sa.ForeignKey('conjunto_datos.id_conjunto_datos', ondelete='RESTRICT'), nullable=False),
    sa.Column('partition_version', sa.String(length=64), nullable=True),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('previous_id', sa.Integer(), sa.ForeignKey('triad_composition.id', ondelete='RESTRICT'), nullable=True),
    sa.Column('first_model_id', sa.Integer(), sa.ForeignKey('modelo.id_modelo', ondelete='RESTRICT'), nullable=False),
    sa.Column('second_model_id', sa.Integer(), sa.ForeignKey('modelo.id_modelo', ondelete='RESTRICT'), nullable=False),
    sa.Column('third_model_id', sa.Integer(), sa.ForeignKey('modelo.id_modelo', ondelete='RESTRICT'), nullable=False),
    sa.Column('first_weight', sa.Float(), nullable=False),
    sa.Column('second_weight', sa.Float(), nullable=False),
    sa.Column('third_weight', sa.Float(), nullable=False),
    sa.Column('author_id', sa.Integer(), sa.ForeignKey('usuario.id_usuario', ondelete='RESTRICT'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('job_id', 'version', name='uq_triad_composition_job_version'),
    sa.CheckConstraint('version >= 1', name='triad_composition_version'),
    sa.CheckConstraint('first_weight >= 0 AND second_weight >= 0 AND third_weight >= 0', name='triad_composition_weights'),
    sa.CheckConstraint('first_model_id <> second_model_id AND first_model_id <> third_model_id'
                       ' AND second_model_id <> third_model_id', name='triad_composition_models'),
)
sa.Index('ix_triad_composition_dataset_id', metadata.tables['triad_composition'].c['dataset_id'], unique=False)

__all__ = ["BOOTSTRAP_TABLES", "metadata"]
