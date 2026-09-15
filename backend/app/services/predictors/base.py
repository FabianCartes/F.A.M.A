"""
Contrato abstracto para estrategias de predicción e inferencia bioacústica.
Representa un Módulo Profundo (Deep Module Seam) que oculta el preprocesamiento,
la arquitectura del modelo, la inferencia y la decodificación detrás de una pequeña interfaz.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult


class AudioPredictor(ABC):
    """
    Interfaz base que cualquier estrategia de modelo de audio debe implementar.
    """

    @property
    @abstractmethod
    def metadata(self) -> ModelMetadata:
        """Retorna los metadatos declarativos del modelo."""
        pass

    @property
    def model_id(self) -> str:
        """Identificador único del modelo."""
        return self.metadata.id

    @abstractmethod
    def predict(self, audio_file_path: Path) -> PredictionResult:
        """
        Ejecuta el análisis de la señal y la inferencia acústica.

        Parámetros:
            audio_file_path: Ruta al archivo de audio temporal o persistido.

        Retorna:
            PredictionResult con la clase predicha, confianza y diagnósticos opcionales.
        """
        pass
