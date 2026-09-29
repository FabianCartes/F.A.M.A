"""
Esquemas DTOs para el subsistema de entrenamiento y ensamble dinámico de modelos.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

VALID_ARCHITECTURES = {
    "EfficientNet-B0",
    "ConvNeXt-Nano",
    "ResNet-34d",
    "PANNs-CNN14",
    "AudioCNN",
}


class AudioConfigSchema(BaseModel):
    """
    Parámetros de física de audio para preprocesamiento y extracción espectral.
    """
    target_sr: int = Field(default=22050, ge=8000, le=48000, description="Frecuencia de muestreo en Hz")
    duration_seconds: float = Field(default=5.0, ge=0.5, le=30.0, description="Duración de la ventana de audio en segundos")
    f_min: float = Field(default=0.0, ge=0.0, description="Frecuencia mínima del filtro mel en Hz")
    f_max: float = Field(default=10000.0, ge=100.0, description="Frecuencia máxima del filtro mel en Hz")
    n_mels: int = Field(default=128, ge=32, le=256, description="Número de bandas mel")
    n_fft: int = Field(default=2048, ge=256, description="Tamaño de ventana FFT")
    hop_length: int = Field(default=512, ge=64, description="Salto temporal de FFT en muestras")

    @model_validator(mode="after")
    def validate_physics(self) -> "AudioConfigSchema":
        if self.f_max > self.target_sr / 2.0:
            raise ValueError(
                f"Violación de Nyquist: f_max ({self.f_max} Hz) no puede superar target_sr / 2 ({self.target_sr / 2.0} Hz)."
            )
        if self.f_min >= self.f_max:
            raise ValueError(
                f"f_min ({self.f_min} Hz) debe ser estrictamente menor que f_max ({self.f_max} Hz)."
            )
        if self.hop_length > self.n_fft:
            raise ValueError(
                f"hop_length ({self.hop_length}) no puede ser mayor que n_fft ({self.n_fft})."
            )
        return self


class WindowingConfigSchema(BaseModel):
    """
    Configuración de ventaneo denso y agregación temporal para eventos de audio breves.
    """
    hop_seconds: float = Field(default=1.0, gt=0.0, description="Salto temporal entre ventanas consecutivas en segundos")
    aggregation_mode: Literal["max", "mean"] = Field(default="max", description="Modo de agregación temporal")
    gem_p: float = Field(default=3.0, ge=1.0, le=10.0, description="Exponente p para Generalized Mean Pooling (GeM)")
    vad_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="Umbral de detección de actividad vocal / energética")


class RegularizationConfigSchema(BaseModel):
    """
    Configuración de regularización, función de pérdida y aumentos espectrales.
    """
    loss_type: Literal["focal", "cross_entropy"] = Field(default="focal", description="Función de pérdida objetivo")
    focal_gamma: float = Field(default=2.0, ge=0.0, description="Parámetro gamma de Focal Loss")
    mixup_enabled: bool = Field(default=False, description="Habilitar regularización Mixup")
    mixup_alpha: float = Field(default=0.2, ge=0.0, description="Parámetro alfa para distribución Beta en Mixup")
    pitch_shift_enabled: bool = Field(default=False, description="Habilitar modulación de tono (Pitch Shift)")


class ModelEnsembleItem(BaseModel):
    """
    Especificación de un modelo miembro del ensamble con su respectiva ponderación y épocas dedicadas.
    """
    architecture: str
    weight: float = Field(ge=0.0, le=1.0)
    epochs: Optional[int] = Field(default=None, ge=1, le=100, description="Épocas de entrenamiento individuales para este modelo")

    @field_validator("architecture")
    @classmethod
    def validate_architecture(cls, v: str) -> str:
        if v not in VALID_ARCHITECTURES:
            raise ValueError(
                f"Arquitectura '{v}' no válida. Opciones permitidas: {sorted(list(VALID_ARCHITECTURES))}"
            )
        return v


class StartTrainingRequest(BaseModel):
    """
    Contrato de solicitud para iniciar el pipeline de entrenamiento.
    Permite composición dinámica de 1 a 3 modelos o retrocompatibilidad con arquitectura única/tríada fija,
    y desacoplamiento del dominio acústico mediante AudioConfigSchema, WindowingConfigSchema y RegularizationConfigSchema.
    """
    dataset_name: str = "AvesChilenas"
    architecture: Optional[str] = "EfficientNet-B0"
    epochs: int = 10
    learning_rate: float = 0.001
    weight_decay: float = Field(default=0.01, ge=0.0, le=1.0, description="Decaimiento de pesos (regularización L2) para AdamW")
    batch_size: int = 16
    framework: str = "pytorch"
    is_tri_model: bool = False
    models: Optional[List[ModelEnsembleItem]] = None
    audio_config: Optional[AudioConfigSchema] = None
    windowing_config: Optional[WindowingConfigSchema] = None
    regularization_config: Optional[RegularizationConfigSchema] = None
    _explicit_models: bool = False

    def __init__(self, **data):
        has_models = "models" in data and data["models"] is not None
        super().__init__(**data)
        object.__setattr__(self, "_explicit_models", has_models)

    @model_validator(mode="after")

    def validate_and_normalize_models(self) -> "StartTrainingRequest":
        if self.models is not None:
            if len(self.models) == 0:
                raise ValueError("La lista de modelos no puede estar vacía.")
            if len(self.models) > 3:
                raise ValueError("No se permite un ensamble de más de 3 modelos.")

            total_weight = sum(item.weight for item in self.models)
            if total_weight <= 0.0:
                raise ValueError("La suma de ponderaciones debe ser mayor a 0.")

            # Auto-normalización determinista de pesos
            normalized_models = []
            for item in self.models:
                normalized_models.append(
                    ModelEnsembleItem(
                        architecture=item.architecture,
                        weight=item.weight / total_weight,
                        epochs=item.epochs,
                    )
                )
            self.models = normalized_models
        else:
            # Retrocompatibilidad con peticiones históricas
            if self.is_tri_model:
                is_engine = self.dataset_name in ["engine_diagnostics", "MotoresVehiculares"]
                archs = (
                    ["ResNet-34d", "EfficientNet-B0", "PANNs-CNN14"]
                    if is_engine
                    else ["EfficientNet-B0", "ConvNeXt-Nano", "ResNet-34d"]
                )
                self.models = [
                    ModelEnsembleItem(architecture=a, weight=1.0 / len(archs))
                    for a in archs
                ]
            else:
                arch = self.architecture or "EfficientNet-B0"
                self.models = [ModelEnsembleItem(architecture=arch, weight=1.0)]

        return self
