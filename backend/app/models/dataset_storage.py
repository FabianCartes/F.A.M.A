"""Additive physical write promises; importing does not prepare any schema."""
from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Integer, String

from app.database import Base


class StorageSchema(Base):
    __tablename__ = "dataset_storage_schema"
    __table_args__ = (
        CheckConstraint("id = 1"), CheckConstraint("version = 1"),
        CheckConstraint("state IN ('prepared', 'active')"),
    )
    id = Column(Integer, primary_key=True, autoincrement=False)
    version = Column(Integer, nullable=False)
    state = Column(String(12), nullable=False)


class StoragePool(Base):
    __tablename__ = "dataset_storage_pool"
    __table_args__ = (CheckConstraint("free_floor_bytes >= 0"),)
    id = Column(String(64), primary_key=True)
    configuration_sha256 = Column(String(64), nullable=False)
    free_floor_bytes = Column(BigInteger, nullable=False)


class StorageGrant(Base):
    __tablename__ = "dataset_storage_grant"
    __table_args__ = (
        CheckConstraint("envelope_bytes > 0"),
        CheckConstraint("attempt >= 0 AND token >= 0"),
        CheckConstraint("state IN ('live', 'retired')"),
    )
    id = Column(String(64), primary_key=True)
    pool_id = Column(String(64), ForeignKey("dataset_storage_pool.id"), nullable=False)
    resource_id = Column(String(128), nullable=False)
    phase = Column(String(24), nullable=False)
    attempt = Column(BigInteger, nullable=False)
    token = Column(BigInteger, nullable=False)
    policy_sha256 = Column(String(64), nullable=False)
    envelope_bytes = Column(BigInteger, nullable=False)
    state = Column(String(12), nullable=False)


STORAGE_MODELS = (StorageSchema, StoragePool, StorageGrant)
