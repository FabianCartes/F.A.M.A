from datetime import datetime, timezone
from sqlalchemy import Column, Integer, BigInteger, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class ConjuntoDatos(Base):
    """
    Modelo relacional para la tabla 'conjunto_datos' en PostgreSQL.
    Corresponde a la Tabla 6.4 de la tesis (Especificación del Modelo de Datos).
    Registra cada dataset de audio bioacústico sincronizado o subido al sistema.
    """
    __tablename__ = "conjunto_datos"

    id_conjunto_datos = Column(Integer, primary_key=True, autoincrement=True, index=True)
    nombre = Column(String(100), nullable=False, unique=True, index=True)
    ruta_gcp = Column(String(500), nullable=False)
    estado = Column(String(50), nullable=False, default="sincronizado")
    id_usuario_carga = Column(Integer, nullable=True)
    fecha_carga = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    tamano_total_bytes = Column(BigInteger, default=0, nullable=False)
    cantidad_audios = Column(Integer, default=0, nullable=False)
    finalidad = Column(Text, default="Entrenamiento bioacústico", nullable=False)
    base_licitud = Column(String(50), default="Investigación académica", nullable=False)

    # Relación 1:N con la tabla 'audio' con borrado en cascada
    audios = relationship("Audio", back_populates="conjunto_datos", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return (
            f"<ConjuntoDatos(id={self.id_conjunto_datos}, nombre='{self.nombre}', "
            f"estado='{self.estado}', audios={self.cantidad_audios})>"
        )


class Audio(Base):
    """
    Modelo relacional para la tabla 'audio' en PostgreSQL.
    Corresponde a la Tabla 6.5 de la tesis.
    Almacena los metadatos individuales de cada archivo de audio ingerido.
    """
    __tablename__ = "audio"

    id_audio = Column(Integer, primary_key=True, autoincrement=True, index=True)
    id_conjunto_datos = Column(
        Integer,
        ForeignKey("conjunto_datos.id_conjunto_datos", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre_archivo = Column(String(255), nullable=False)
    ruta_gcp = Column(String(500), nullable=False)
    clase = Column(String(100), nullable=False, index=True)
    frecuencia_muestreo = Column(Integer, nullable=True, default=22050)
    duracion_segundos = Column(Float, nullable=True)
    tamano_bytes = Column(BigInteger, default=0, nullable=False)
    hash_archivo = Column(String(64), nullable=True)
    fecha_subida = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relación N:1 con 'conjunto_datos'
    conjunto_datos = relationship("ConjuntoDatos", back_populates="audios")

    def __repr__(self) -> str:
        return (
            f"<Audio(id={self.id_audio}, archivo='{self.nombre_archivo}', "
            f"clase='{self.clase}', bytes={self.tamano_bytes})>"
        )
