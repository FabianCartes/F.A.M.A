"""Additive metadata backfill targets; importing these does not switch runtime readers."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Float, ForeignKey,
    Index, Integer, JSON, String, UniqueConstraint,
)

from app.database import Base


class FileMetadata:
    id = Column(String(32), primary_key=True)
    source_import_id = Column(String(32), ForeignKey("dataset_import.id"), nullable=False)
    class_name = Column(String(240), nullable=False)
    original_path = Column(String(1024), nullable=False)
    selected_root = Column(String(1024), nullable=False)
    relative_path = Column(String(1024), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    stored_name = Column(String(240), nullable=False)
    sample_rate = Column(Integer)
    duration_seconds = Column(Float)
    sync_status = Column(String(30), nullable=False, default="pending")
    object_key = Column(String(1024))
    object_generation = Column(String(100))
    # Per-record audit copy, not an operational membership/progress document.
    legacy_metadata = Column(JSON, nullable=False)


class ImportFile(FileMetadata, Base):
    __tablename__ = "dataset_import_file"
    __table_args__ = (
        UniqueConstraint("import_id", "ordinal"),
        CheckConstraint("size_bytes >= 0"),
        Index("ix_import_file_hash", "import_id", "sha256"),
        Index("ix_import_file_class", "import_id", "class_name", "id"),
        Index("ix_import_file_sync", "import_id", "sync_status", "id"),
    )
    import_id = Column(String(32), ForeignKey("dataset_import.id"), nullable=False)
    ordinal = Column(Integer, nullable=False)
    duplicate = Column(Boolean, nullable=False)
    existing = Column(Boolean, nullable=False)


class DatasetMember(FileMetadata, Base):
    __tablename__ = "imported_dataset_member"
    __table_args__ = (
        UniqueConstraint("dataset_id", "sha256"),
        UniqueConstraint("dataset_id", "relative_path"),
        CheckConstraint("size_bytes >= 0"),
        Index("ix_dataset_member_class", "dataset_id", "class_name", "id"),
        Index("ix_dataset_member_sync", "dataset_id", "sync_status", "id"),
    )
    dataset_id = Column(String(32), ForeignKey("imported_dataset.id"), nullable=False)
    # Revision of the migrated snapshot, not an invented first-added revision.
    dataset_revision = Column(Integer, nullable=False)


class ImportIssue(Base):
    __tablename__ = "dataset_import_issue"
    __table_args__ = (
        UniqueConstraint("import_id", "severity", "ordinal"),
        Index("ix_import_issue_page", "import_id", "severity", "ordinal"),
    )
    id = Column(String(32), primary_key=True)
    import_id = Column(String(32), ForeignKey("dataset_import.id"), nullable=False)
    severity = Column(String(10), nullable=False)
    ordinal = Column(Integer, nullable=False)
    path = Column(String(1024), nullable=False)
    code = Column(String(100), nullable=False)
    action = Column(String(2000))
    legacy_metadata = Column(JSON, nullable=False)


class ImportClass(Base):
    __tablename__ = "dataset_import_class"
    __table_args__ = (UniqueConstraint("import_id", "class_name"),
                      UniqueConstraint("import_id", "ordinal"))
    id = Column(String(32), primary_key=True)
    import_id = Column(String(32), ForeignKey("dataset_import.id"), nullable=False)
    ordinal = Column(Integer, nullable=False)
    class_name = Column(String(240), nullable=False)


class ImportSummary(Base):
    __tablename__ = "dataset_import_summary"
    import_id = Column(String(32), ForeignKey("dataset_import.id"), primary_key=True)
    preview = Column(JSON, nullable=False)
    fingerprint = Column(String(100), index=True)
    file_count = Column(Integer, nullable=False)
    class_count = Column(Integer, nullable=False)
    error_count = Column(Integer, nullable=False)
    warning_count = Column(Integer, nullable=False)
    total_size_bytes = Column(BigInteger, nullable=False)


class DatasetSummary(Base):
    __tablename__ = "imported_dataset_summary"
    dataset_id = Column(String(32), ForeignKey("imported_dataset.id"), primary_key=True)
    revision = Column(Integer, nullable=False)
    file_count = Column(Integer, nullable=False)
    class_count = Column(Integer, nullable=False)
    total_size_bytes = Column(BigInteger, nullable=False)


class MetadataBackfill(Base):
    __tablename__ = "dataset_import_metadata_backfill"
    version = Column(Integer, primary_key=True)
    source_sha256 = Column(String(64), nullable=False)
    report = Column(JSON, nullable=False)


BACKFILL_MODELS = (ImportFile, DatasetMember, ImportIssue, ImportClass,
                   ImportSummary, DatasetSummary, MetadataBackfill)
