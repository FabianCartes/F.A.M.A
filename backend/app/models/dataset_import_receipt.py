"""Durable receipt admission, separate from execution leases and dataset storage."""
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, ForeignKey, Integer, String

from app.database import Base


class ImportReceiptSchema(Base):
    __tablename__ = "dataset_import_receipt_schema"
    __table_args__ = (CheckConstraint("id = 1"), CheckConstraint("version = 1"))
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)


class ImportReceipt(Base):
    __tablename__ = "dataset_import_receipt"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_receipt_size"),
        CheckConstraint("reserved_bytes >= size_bytes", name="ck_receipt_reservation"),
        CheckConstraint("received_bytes >= 0 AND received_bytes <= size_bytes", name="ck_receipt_progress"),
        CheckConstraint("chunk_bytes > 0", name="ck_receipt_chunk_size"),
        CheckConstraint("status IN ('receiving', 'sealed', 'cancelled')", name="ck_receipt_status"),
    )
    import_id = Column(String(32), ForeignKey("dataset_import.id"), primary_key=True)
    name = Column(String(255), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    reserved_bytes = Column(BigInteger, nullable=False)
    reservation_active = Column(Boolean, nullable=False)
    received_bytes = Column(BigInteger, nullable=False)
    chunk_bytes = Column(Integer, nullable=False)
    status = Column(String(12), nullable=False)


RECEIPT_MODELS = (ImportReceiptSchema, ImportReceipt)
