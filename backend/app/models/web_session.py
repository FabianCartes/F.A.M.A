"""Opaque web sessions: persist digests, never browser credentials."""
from sqlalchemy import Column, ForeignKey, Integer, String, BigInteger

from app.database import Base


class SesionWeb(Base):
    __tablename__ = "sesion_web"

    token_hash = Column(String(64), primary_key=True)
    id_usuario = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="CASCADE"), nullable=False, index=True)
    expira_en = Column(BigInteger, nullable=False, index=True)
    inactiva_en = Column(BigInteger, nullable=False, index=True)
