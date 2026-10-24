"""Frozen reconstruction membership and separately mutable synchronization evidence."""
from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Integer, String, UniqueConstraint

from app.database import Base


class DatasetRevision(Base):
    __tablename__ = "imported_dataset_revision"
    __table_args__ = (
        UniqueConstraint("dataset_id", "revision"),
        CheckConstraint("status IN ('pending', 'complete')"),
        CheckConstraint("file_count >= 0 AND total_size_bytes >= 0"),
        CheckConstraint("verified_count >= 0 AND verified_count <= file_count"),
        CheckConstraint("verified_bytes >= 0 AND verified_bytes <= total_size_bytes"),
    )
    id = Column(String(32), primary_key=True)
    dataset_id = Column(String(32), ForeignKey("imported_dataset.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    owner_id = Column(Integer, nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(String(2000), nullable=False)
    file_count = Column(Integer, nullable=False)
    total_size_bytes = Column(BigInteger, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    verified_count = Column(Integer, nullable=False, default=0)
    verified_bytes = Column(BigInteger, nullable=False, default=0)
    manifest_key = Column(String(1024))
    manifest_generation = Column(String(100))
    manifest_sha256 = Column(String(64))
    manifest_size_bytes = Column(BigInteger)


class RevisionObject(Base):
    __tablename__ = "imported_dataset_revision_object"
    __table_args__ = (
        UniqueConstraint("revision_id", "sha256"),
        UniqueConstraint("revision_id", "relative_path"),
        CheckConstraint("size_bytes >= 0"),
    )
    revision_id = Column(String(32), ForeignKey("imported_dataset_revision.id"), primary_key=True)
    member_id = Column(String(32), primary_key=True)
    source_import_id = Column(String(32), nullable=False)
    stored_name = Column(String(240), nullable=False)
    class_name = Column(String(240), nullable=False)
    original_path = Column(String(1024), nullable=False)
    relative_path = Column(String(1024), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    object_key = Column(String(1024), nullable=False)
    object_generation = Column(String(100))
    verified_sha256 = Column(String(64))
    verified_size_bytes = Column(BigInteger)


REVISION_MODELS = (DatasetRevision, RevisionObject)
