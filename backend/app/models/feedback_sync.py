"""Intención durable de sincronización, independiente de la curación legacy."""
from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String

from app.database import Base


class FeedbackSync(Base):
    __tablename__ = "feedback_sync"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'synced')", name="feedback_sync_status"),
        CheckConstraint("attempts >= 0", name="feedback_sync_attempts"),
    )

    id_retroalimentacion = Column(Integer, ForeignKey(
        "retroalimentacion.id_retroalimentacion", ondelete="RESTRICT"), primary_key=True)
    dataset_name = Column(String(100), nullable=False)
    storage_class = Column(String(100), nullable=False)
    class_label = Column(String(100), nullable=False)
    object_key = Column(String(255), nullable=False, unique=True)
    local_relative_path = Column(String(255), nullable=False, unique=True)
    sha256 = Column(String(64), nullable=False)
    status = Column(String(10), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    error_code = Column(String(32), nullable=True)
