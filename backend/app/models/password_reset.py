"""One current recovery capability per account; raw tokens are never persisted."""
from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey
from app.database import Base


class RecuperacionCuenta(Base):
    __tablename__ = "recuperacion_cuenta"
    id_usuario = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="CASCADE"), primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expira_en = Column(BigInteger, nullable=False, index=True)
