from datetime import datetime, timezone
from sqlalchemy import Column, Integer, BigInteger, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Modelo(Base):
    """
    Modelo relacional para la tabla 'modelo' en PostgreSQL.
    Corresponde a la Tabla 6.6 de la tesis (Especificación del Modelo de Datos).
    Almacena los metadatos de arquitecturas, hiperparámetros y pesos binarios (.pt).
    """
    __tablename__ = "modelo"

    id_modelo = Column(Integer, primary_key=True, autoincrement=True, index=True)
    id_usuario = Column(Integer, nullable=True)
    id_conjunto_datos = Column(
        Integer,
        ForeignKey("conjunto_datos.id_conjunto_datos", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    clase_objetivo = Column(String(100), nullable=False, default="15 Aves Chilenas")
    actualizacion_de = Column(
        Integer,
        ForeignKey("modelo.id_modelo", ondelete="SET NULL"),
        nullable=True,
    )
    arquitectura = Column(String(255), nullable=False)
    epocas = Column(Integer, nullable=False)
    tasa_aprendizaje = Column(Float, nullable=False)
    tamano_lote = Column(Integer, nullable=False)
    precision = Column(Float, nullable=True)
    perdida = Column(Float, nullable=True)
    ruta_binario_gcp = Column(String(500), nullable=False)
    tamano_bytes = Column(BigInteger, default=0, nullable=False)
    hash_binario = Column(String(64), nullable=True)
    activo = Column(Boolean, default=False, nullable=False)
    estado = Column(String(50), default="entrenado", nullable=False)
    fecha_entrenamiento = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relaciones
    conjunto_datos = relationship("ConjuntoDatos")
    metricas = relationship(
        "MetricaEntrenamiento",
        back_populates="modelo",
        cascade="all, delete-orphan",
        order_by="MetricaEntrenamiento.epoca",
    )

    def __repr__(self) -> str:
        return (
            f"<Modelo(id={self.id_modelo}, arquitectura='{self.arquitectura}', "
            f"precision={self.precision}, activo={self.activo})>"
        )


class MetricaEntrenamiento(Base):
    """
    Modelo relacional para la tabla 'metrica_entrenamiento' en PostgreSQL.
    Corresponde a la Tabla 6.7 de la tesis.
    Almacena el registro histórico época a época de pérdida y precisión (IS_02).
    """
    __tablename__ = "metrica_entrenamiento"

    id_metrica = Column(Integer, primary_key=True, autoincrement=True, index=True)
    id_modelo = Column(
        Integer,
        ForeignKey("modelo.id_modelo", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    epoca = Column(Integer, nullable=False)
    precision = Column(Float, nullable=False)
    perdida = Column(Float, nullable=False)
    puntuacion_validacion = Column(Float, nullable=True)
    tiempo_epoca = Column(Float, nullable=True)

    # Relación N:1 con 'modelo'
    modelo = relationship("Modelo", back_populates="metricas")

    def __repr__(self) -> str:
        return (
            f"<MetricaEntrenamiento(id={self.id_metrica}, modelo={self.id_modelo}, "
            f"epoca={self.epoca}, acc={self.precision}, loss={self.perdida})>"
        )
