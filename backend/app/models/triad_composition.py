"""Versioned composition of a standard triad: three trained models and their weights.

A weight revision is a new row (``version`` + 1, ``previous_id``); rows are never
edited in place, so prediction history and feedback keep the version they used.
"""
from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String,
                        UniqueConstraint, false)

from app.database import Base


class TriadComposition(Base):
    __tablename__ = "triad_composition"
    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_triad_composition_job_version"),
        CheckConstraint("version >= 1", name="triad_composition_version"),
        CheckConstraint("first_weight >= 0 AND second_weight >= 0 AND third_weight >= 0",
                        name="triad_composition_weights"),
        CheckConstraint("first_model_id <> second_model_id AND first_model_id <> third_model_id"
                        " AND second_model_id <> third_model_id", name="triad_composition_models"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(Integer, ForeignKey("conjunto_datos.id_conjunto_datos", ondelete="RESTRICT"),
                        nullable=False, index=True)
    partition_version = Column(String(64), nullable=True)
    job_id = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False)
    previous_id = Column(Integer, ForeignKey("triad_composition.id", ondelete="RESTRICT"), nullable=True)
    first_model_id = Column(Integer, ForeignKey("modelo.id_modelo", ondelete="RESTRICT"), nullable=False)
    second_model_id = Column(Integer, ForeignKey("modelo.id_modelo", ondelete="RESTRICT"), nullable=False)
    third_model_id = Column(Integer, ForeignKey("modelo.id_modelo", ondelete="RESTRICT"), nullable=False)
    first_weight = Column(Float, nullable=False)
    second_weight = Column(Float, nullable=False)
    third_weight = Column(Float, nullable=False)
    author_id = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="RESTRICT"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    # Default-model flag; at most one of ``modelo.activo`` / ``triad_composition.activo`` is true.
    activo = Column(Boolean, nullable=False, default=False, server_default=false())


class TriadCompositionEvaluation(Base):
    """One joint evaluation attempt of one exact composition version on one split.

    The identity freezes the ordered components, checkpoint hashes and weights; a weight
    revision is another composition and never inherits these rows. ``checkpoint_sha256``
    is the digest of the whole ensemble, not of any single component.
    """
    __tablename__ = "triad_composition_evaluation"
    __table_args__ = (
        CheckConstraint("status IN ('pending','running','completed','failed')", name="triad_evaluation_status"),
        CheckConstraint("split IN ('val','test')", name="triad_evaluation_split"),
        CheckConstraint("sample_count > 0 AND schema_version = 2 AND composition_version >= 1",
                        name="triad_evaluation_counts"),
        CheckConstraint("(status = 'completed' AND report IS NOT NULL AND error_reason IS NULL) OR "
                        "(status != 'completed' AND report IS NULL)", name="triad_evaluation_report"),
        CheckConstraint("(status = 'failed' AND error_reason IS NOT NULL) OR "
                        "(status != 'failed' AND error_reason IS NULL)", name="triad_evaluation_error"),
        CheckConstraint("(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
                        "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
                        "(status IN ('completed','failed') AND finished_at IS NOT NULL)",
                        name="triad_evaluation_times"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    composition_id = Column(Integer, ForeignKey("triad_composition.id", ondelete="RESTRICT"),
                            nullable=False, index=True)
    composition_version = Column(Integer, nullable=False)
    component_model_ids = Column(JSON, nullable=False)
    checkpoint_sha256s = Column(JSON, nullable=False)
    weights = Column(JSON, nullable=False)
    schema_version = Column(Integer, nullable=False)
    evaluator_version = Column(String(100), nullable=False)
    checkpoint_sha256 = Column(String(64), nullable=False)
    dataset = Column(String(255), nullable=False)
    split = Column(String(10), nullable=False)
    manifest_sha256 = Column(String(64), nullable=False)
    classes = Column(JSON, nullable=False)
    predictor_config = Column(JSON, nullable=False)
    preprocessing_config = Column(JSON, nullable=False)
    aggregation_config = Column(JSON, nullable=False)
    sample_count = Column(Integer, nullable=False)
    report = Column(JSON(none_as_null=True), nullable=True)
    status = Column(String(10), nullable=False)
    error_reason = Column(String(2000), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    code_revision = Column(String(255), nullable=True)
