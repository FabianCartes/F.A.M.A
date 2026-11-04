"""Additive local training snapshots, independent of remote revision status."""
from sqlalchemy import Column, String, Integer, BigInteger, JSON, ForeignKey
from app.database import Base


class TrainingSnapshot(Base):
    __tablename__ = "training_snapshot"
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False, index=True)
    dataset_id = Column(String(32), nullable=False)
    dataset_revision = Column(Integer, nullable=False)
    name = Column(String(240), nullable=False)
    description = Column(String, nullable=False)
    state = Column(String(20), nullable=False)
    file_count = Column(Integer, nullable=False)
    total_size_bytes = Column(BigInteger, nullable=False)
    manifest_sha256 = Column(String(64))
    classes = Column(JSON, nullable=False)


class SnapshotMember(Base):
    __tablename__ = "training_snapshot_member"
    snapshot_id = Column(String(32), ForeignKey("training_snapshot.id"), primary_key=True)
    member_id = Column(String(32), primary_key=True)
    source_import_id = Column(String(32), nullable=False)
    stored_name = Column(String(240), nullable=False)
    class_name = Column(String(240), nullable=False)
    original_path = Column(String(1024), nullable=False)
    relative_path = Column(String(1024), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
