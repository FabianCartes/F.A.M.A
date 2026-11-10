"""Evaluation SQL contract, independent of connection setup and operator tooling."""
from sqlalchemy import Table, Column, Integer, String, JSON, DateTime, ForeignKey, CheckConstraint

def evaluation_table(metadata):
    """Shared definition without importing the production database module."""
    return Table(
        'model_evaluation', metadata,
        Column('id_evaluation', Integer, primary_key=True, autoincrement=True),
        Column('id_modelo', Integer, ForeignKey('modelo.id_modelo', ondelete='RESTRICT'), nullable=False),
        Column('schema_version', Integer, nullable=False),
        Column('evaluator_version', String(100), nullable=False),
        Column('checkpoint_sha256', String(64), nullable=False),
        Column('dataset', String(255), nullable=False),
        Column('split', String(10), nullable=False),
        Column('manifest_sha256', String(64), nullable=False),
        Column('classes', JSON, nullable=False),
        Column('predictor_config', JSON, nullable=False),
        Column('preprocessing_config', JSON, nullable=False),
        Column('aggregation_config', JSON, nullable=False),
        Column('sample_count', Integer, nullable=False),
        Column('report', JSON(none_as_null=True), nullable=True),
        Column('status', String(10), nullable=False),
        Column('error_reason', String(2000), nullable=True),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('started_at', DateTime(timezone=True), nullable=True),
        Column('finished_at', DateTime(timezone=True), nullable=True),
        Column('code_revision', String(255), nullable=True),
        CheckConstraint("status IN ('pending','running','completed','failed')", name='evaluation_status'),
        CheckConstraint("split IN ('val','test')", name='evaluation_split'),
        CheckConstraint('sample_count > 0 AND schema_version IN (1, 2)', name='evaluation_counts'),
        CheckConstraint("(status = 'completed' AND report IS NOT NULL AND error_reason IS NULL) OR "
                        "(status != 'completed' AND report IS NULL)", name='evaluation_report'),
        CheckConstraint("(status = 'failed' AND error_reason IS NOT NULL) OR "
                        "(status != 'failed' AND error_reason IS NULL)", name='evaluation_error'),
        CheckConstraint("(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
                        "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
                        "(status IN ('completed','failed') AND finished_at IS NOT NULL)", name='evaluation_times'),
    )
