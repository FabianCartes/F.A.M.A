"""Explicit grants, independent of historical uploader IDs or display names."""
from sqlalchemy import Column, Integer, ForeignKey
from app.database import Base


class AsignacionDataset(Base):
    __tablename__ = "asignacion_dataset"
    id_usuario = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="CASCADE"), primary_key=True)
    id_conjunto_datos = Column(Integer, ForeignKey("conjunto_datos.id_conjunto_datos", ondelete="CASCADE"),
                              primary_key=True, index=True)
