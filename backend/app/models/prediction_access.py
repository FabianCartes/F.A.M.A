"""Verified provenance for new predictions; historical strings are not grants."""
from sqlalchemy import Column, Integer, ForeignKey
from app.database import Base


class AccesoPrediccion(Base):
    __tablename__ = "acceso_prediccion"
    id_prediccion = Column(Integer, ForeignKey("prediccion.id_prediccion", ondelete="CASCADE"), primary_key=True)
    id_conjunto_datos = Column(Integer, ForeignKey("conjunto_datos.id_conjunto_datos", ondelete="CASCADE"),
                              nullable=False, index=True)
    id_usuario = Column(Integer, ForeignKey("usuario.id_usuario"), nullable=False)
