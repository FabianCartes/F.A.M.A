from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime
from app.database import Base


class Prediccion(Base):
    """
    Modelo relacional para la tabla 'prediccion' en PostgreSQL.
    Almacena el registro histórico de cada inferencia bioacústica ejecutada.
    """
    __tablename__ = "prediccion"

    id_prediccion = Column(Integer, primary_key=True, autoincrement=True, index=True)
    ruta_audio_prueba = Column(String(255), nullable=False)
    etiqueta_predicha = Column(String(100), nullable=False)
    confianza = Column(Float, nullable=False)
    fecha_prediccion = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Prediccion(id={self.id_prediccion}, "
            f"etiqueta='{self.etiqueta_predicha}', "
            f"confianza={self.confianza})>"
        )
