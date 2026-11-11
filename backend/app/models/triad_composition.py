"""Versioned composition of a standard triad: three trained models and their weights.

A weight revision is a new row (``version`` + 1, ``previous_id``); rows are never
edited in place, so prediction history and feedback keep the version they used.
"""
from sqlalchemy import (CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String,
                        UniqueConstraint)

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
