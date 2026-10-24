"""Minimal security events: no request bodies, secrets or user text fields."""
from sqlalchemy import Column, Integer, BigInteger, String, CheckConstraint, Index
from app.database import Base


class EventoSeguridad(Base):
    __tablename__ = "evento_seguridad"
    __table_args__ = (
        CheckConstraint("outcome IN ('success', 'denied')", name="chk_evento_resultado"),
        Index("ix_evento_retencion", "occurred_at", "id"),
        {"sqlite_autoincrement": True},
    )
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    occurred_at = Column(BigInteger, nullable=False)
    action = Column(String(48), nullable=False)
    outcome = Column(String(12), nullable=False)
    # Intentionally not cascading FKs: history must survive future account archival.
    actor_id = Column(Integer, nullable=True)
    subject_user_id = Column(Integer, nullable=True)
    dataset_id = Column(Integer, nullable=True)
