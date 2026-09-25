from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Retroalimentacion(Base):
    """
    Modelo relacional para la tabla 'retroalimentacion' en PostgreSQL (Tabla 6.9 de la Tesis).
    Almacena la validación experta o corrección taxonómica del investigador sobre una predicción.
    """
    __tablename__ = "retroalimentacion"

    id_retroalimentacion = Column(Integer, primary_key=True, autoincrement=True, index=True)
    id_prediccion = Column(
        Integer,
        ForeignKey("prediccion.id_prediccion", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    id_usuario = Column(Integer, nullable=False, default=1)
    etiqueta_corregida = Column(String(100), nullable=True)
    fue_correcta = Column(Boolean, nullable=False)
    procesado = Column(Boolean, nullable=False, default=False)
    fecha_retroalimentacion = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    prediccion = relationship("Prediccion", backref="retroalimentacion")

    def __repr__(self) -> str:
        return (
            f"<Retroalimentacion(id={self.id_retroalimentacion}, "
            f"prediccion_id={self.id_prediccion}, "
            f"correcta={self.fue_correcta}, "
            f"corregida='{self.etiqueta_corregida}')>"
        )
