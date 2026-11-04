"""Additive immutable provenance for imported checkpoints; never backfills legacy."""
from sqlalchemy import Column, Integer, String, JSON, ForeignKey
from app.database import Base


class ImportedModelSource(Base):
    __tablename__ = "imported_model_source"
    __table_args__ = {"info": {"explicit_migration": True}}
    model_id = Column(Integer, ForeignKey("modelo.id_modelo"), primary_key=True)
    owner_id = Column(Integer, nullable=False)
    dataset_id = Column(String(32), nullable=False)
    snapshot_id = Column(String(32), ForeignKey("training_snapshot.id"), nullable=False)
    identity = Column(JSON, nullable=False)
