"""Persistent admission windows containing only pseudonymous bucket keys."""
from sqlalchemy import Column, String, Integer, BigInteger, CheckConstraint
from app.database import Base


class CuotaAcceso(Base):
    __tablename__ = "cuota_acceso"
    __table_args__ = (CheckConstraint("intentos > 0", name="chk_cuota_intentos_positivos"),)
    clave_hash = Column(String(64), primary_key=True)
    intentos = Column(Integer, nullable=False)
    expira_en = Column(BigInteger, nullable=False, index=True)
