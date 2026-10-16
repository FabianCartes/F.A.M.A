"""Private managed catalog; deliberately not part of training's dataset registry."""
from sqlalchemy import Column, Float, Integer, JSON, String, UniqueConstraint
from app.database import Base


class ImportedDataset(Base):
    __tablename__ = "imported_dataset"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False, index=True)
    name = Column(String(150), nullable=False)
    description = Column(String(2000), nullable=False, default="")
    revision = Column(Integer, nullable=False, default=0)
    files = Column(JSON, nullable=False, default=list)


class DatasetImport(Base):
    __tablename__ = "dataset_import"
    __table_args__ = (UniqueConstraint("owner_id", "request_key"),)
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False, index=True)
    request_key = Column(String(100), nullable=False)
    request = Column(JSON, nullable=False)
    status = Column(String(30), nullable=False, default="receiving")
    sync_status = Column(String(30), nullable=False, default="pending")
    created_at = Column(Float, nullable=False)
    archive_sha256 = Column(String(64))
    preview_token = Column(String(64))
    preview = Column(JSON, nullable=False, default=dict)
    dataset_id = Column(String(32))
    added_count = Column(Integer, nullable=False, default=0)
    error = Column(String(100))
