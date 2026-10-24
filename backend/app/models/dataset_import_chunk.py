"""Additive chunk journal; receipt schema version one remains unchanged."""
from sqlalchemy import BigInteger, CheckConstraint, Column, Float, ForeignKey, Integer, String, UniqueConstraint

from app.database import Base


class ImportChunkSchema(Base):
    __tablename__ = "dataset_import_chunk_schema"
    __table_args__ = (CheckConstraint("id = 1"), CheckConstraint("version = 1"))
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)


class ImportChunkActivity(Base):
    __tablename__ = "dataset_import_chunk_activity"
    import_id = Column(String(32), ForeignKey("dataset_import_receipt.import_id"), primary_key=True)
    updated_at = Column(Float, nullable=False)


class ImportChunk(Base):
    __tablename__ = "dataset_import_chunk"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0"), CheckConstraint("offset_bytes >= 0"),
        CheckConstraint("length_bytes > 0"), CheckConstraint("length(sha256) = 64"),
        UniqueConstraint("import_id", "offset_bytes"),
    )
    import_id = Column(String(32), ForeignKey("dataset_import_receipt.import_id"), primary_key=True)
    chunk_index = Column(Integer, primary_key=True)
    offset_bytes = Column(BigInteger, nullable=False)
    length_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)


CHUNK_MODELS = (ImportChunkSchema, ImportChunkActivity, ImportChunk)
