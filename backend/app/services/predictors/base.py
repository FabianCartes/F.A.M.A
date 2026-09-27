"""
Contrato abstracto para estrategias de predicción e inferencia bioacústica.
Representa un Módulo Profundo (Deep Module Seam) que oculta el preprocesamiento,
la arquitectura del modelo, la inferencia y la decodificación detrás de una pequeña interfaz.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult


class ModelWeightsError(Exception):
    """Excepción lanzada cuando los pesos del modelo no existen, están corruptos o no pueden cargarse."""
    pass


# Umbral de planitud espectral: aves reales promedian 0.015 (máx 0.032).
# Ruido blanco/estática promedia > 0.50. Umbral de 0.15 separa nítidamente ambos.
SPECTRAL_FLATNESS_NOISE_THRESHOLD = 0.15

# Clases por defecto del dominio piloto de aves chilenas
DEFAULT_CHILEAN_BIRD_CLASSES = [
    "Canastero", "Chercán", "Chincol", "Chucao", "Churrín de la Mocha",
    "Churrín del sur", "Colilarga", "Fío-fío", "Picaflor chico", "Rayadito",
    "Tapaculo", "Tijeral", "Tordo", "Turca", "Zorzal patagónico"
]


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

    @property
    def has_weights(self) -> bool:
        """Indica si el modelo cuenta con archivos de pesos (.pt) válidos en disco."""
        return True

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
