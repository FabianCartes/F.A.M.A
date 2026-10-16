"""Execution identity is separate from the retained import and preview metadata."""
from sqlalchemy import (
    CheckConstraint, Column, Float, ForeignKey, Index, Integer, JSON,
    String, UniqueConstraint, text,
)

from app.database import Base


class ImportJobGate(Base):
    """One database row serializes short admission/claim/release transactions."""

    __tablename__ = "dataset_import_job_gate"
    __table_args__ = (CheckConstraint("id = 1"), CheckConstraint("version = 1"))
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)
    generation = Column(Integer, nullable=False)


class ImportJob(Base):
    __tablename__ = "dataset_import_job"
    __table_args__ = (
        UniqueConstraint("owner_id", "import_id", "kind", "request_key", name="uq_import_job_operation"),
        CheckConstraint("kind IN ('preview', 'confirm', 'sync')", name="ck_import_job_kind"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="ck_import_job_status"),
        CheckConstraint("attempt >= 0 AND token >= 0", name="ck_import_job_attempt"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_import_job_progress"),
        CheckConstraint("(status = 'running' AND lease_until IS NOT NULL AND heartbeat_at IS NOT NULL) OR (status <> 'running' AND lease_until IS NULL)", name="ck_import_job_lease"),
        Index("ix_import_job_claim", "status", "lease_until", "created_at", "id"),
        Index("ix_import_job_owner", "owner_id", "status"),
        Index("uq_import_job_active_import", "import_id", unique=True,
              sqlite_where=text("status IN ('queued', 'running')"),
              postgresql_where=text("status IN ('queued', 'running')")),
    )
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False)
    import_id = Column(String(32), ForeignKey("dataset_import.id"), nullable=False)
    kind = Column(String(10), nullable=False)
    request_key = Column(String(100), nullable=False)
    parameters = Column(JSON, nullable=False)
    parameters_sha256 = Column(String(64), nullable=False)
    expected_preview_token = Column(String(64))
    expected_revision = Column(Integer)
    status = Column(String(12), nullable=False)
    stage = Column(String(40), nullable=False)
    progress = Column(Integer, nullable=False)
    result = Column(JSON, nullable=False)
    error = Column(JSON)
    attempt = Column(Integer, nullable=False)
    token = Column(Integer, nullable=False)
    lease_until = Column(Float)
    heartbeat_at = Column(Float)
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)


JOB_MODELS = (ImportJobGate, ImportJob)
