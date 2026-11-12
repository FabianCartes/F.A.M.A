"""Frozen schema 0007: 0006 plus joint evaluation attempts of standard triad compositions."""
import sqlalchemy as sa
from migrations.schema_0006 import BOOTSTRAP_TABLES, metadata as previous

metadata = sa.MetaData()
for table in previous.sorted_tables:
    table.to_metadata(metadata)

sa.Table('triad_composition_evaluation', metadata,
    sa.Column('id', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('composition_id', sa.Integer(), sa.ForeignKey('triad_composition.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('composition_version', sa.Integer(), nullable=False),
    sa.Column('component_model_ids', sa.JSON(), nullable=False),
    sa.Column('checkpoint_sha256s', sa.JSON(), nullable=False),
    sa.Column('weights', sa.JSON(), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=False),
    sa.Column('evaluator_version', sa.String(length=100), nullable=False),
    sa.Column('checkpoint_sha256', sa.String(length=64), nullable=False),
    sa.Column('dataset', sa.String(length=255), nullable=False),
    sa.Column('split', sa.String(length=10), nullable=False),
    sa.Column('manifest_sha256', sa.String(length=64), nullable=False),
    sa.Column('classes', sa.JSON(), nullable=False),
    sa.Column('predictor_config', sa.JSON(), nullable=False),
    sa.Column('preprocessing_config', sa.JSON(), nullable=False),
    sa.Column('aggregation_config', sa.JSON(), nullable=False),
    sa.Column('sample_count', sa.Integer(), nullable=False),
    sa.Column('report', sa.JSON(none_as_null=True), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('error_reason', sa.String(length=2000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('code_revision', sa.String(length=255), nullable=True),
    sa.CheckConstraint("status IN ('pending','running','completed','failed')", name='triad_evaluation_status'),
    sa.CheckConstraint("split IN ('val','test')", name='triad_evaluation_split'),
    sa.CheckConstraint('sample_count > 0 AND schema_version = 2 AND composition_version >= 1',
                       name='triad_evaluation_counts'),
    sa.CheckConstraint("(status = 'completed' AND report IS NOT NULL AND error_reason IS NULL) OR "
                       "(status != 'completed' AND report IS NULL)", name='triad_evaluation_report'),
    sa.CheckConstraint("(status = 'failed' AND error_reason IS NOT NULL) OR "
                       "(status != 'failed' AND error_reason IS NULL)", name='triad_evaluation_error'),
    sa.CheckConstraint("(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
                       "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
                       "(status IN ('completed','failed') AND finished_at IS NOT NULL)", name='triad_evaluation_times'),
)
sa.Index('ix_triad_composition_evaluation_composition_id',
         metadata.tables['triad_composition_evaluation'].c['composition_id'], unique=False)

__all__ = ["BOOTSTRAP_TABLES", "metadata"]
