"""Additive export jobs and bounded native-download sessions."""
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Float, ForeignKey, Index, Integer, String, UniqueConstraint

from app.database import Base


class DatasetExport(Base):
    __tablename__ = "dataset_export"
    __table_args__ = (
        UniqueConstraint("owner_id", "request_key"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','deleting','expired')"),
        CheckConstraint("attempt >= 0 AND token >= 0 AND progress >= 0 AND progress <= 100"),
        CheckConstraint("(status = 'running' AND lease_until IS NOT NULL) OR (status <> 'running' AND lease_until IS NULL)"),
        Index("ix_dataset_export_claim", "status", "lease_until", "created_at"),
    )
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False)
    dataset_id = Column(String(32), ForeignKey("imported_dataset.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    request_key = Column(String(100), nullable=False)
    status = Column(String(12), nullable=False)
    attempt = Column(Integer, nullable=False, default=0)
    token = Column(Integer, nullable=False, default=0)
    progress = Column(Integer, nullable=False, default=0)
    lease_until = Column(Float)
    created_at = Column(Float, nullable=False)
    expires_at = Column(Float, nullable=False)
    artifact = Column(String(150))
    artifact_identity = Column(String(160))
    sha256 = Column(String(64))
    size_bytes = Column(BigInteger)
    error = Column(String(40))


class DownloadSession(Base):
    __tablename__ = "dataset_export_session"
    __table_args__ = (Index("ix_export_session_expiry", "export_id", "expires_at"),)
    id = Column(String(32), primary_key=True)
    export_id = Column(String(32), ForeignKey("dataset_export.id"), nullable=False)
    owner_id = Column(Integer, nullable=False)
    secret_sha256 = Column(String(64), nullable=False)
    established = Column(Boolean, nullable=False, default=False)
    expires_at = Column(Float, nullable=False)


EXPORT_MODELS = (DatasetExport, DownloadSession)
