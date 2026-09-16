"""
backend/training/schemas/config.py
Esquemas declarativos y validación de recetas de entrenamiento vía Pydantic v2.
"""
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, Literal
from pydantic import BaseModel, Field, model_validator


class AudioConfig(BaseModel):
    """Parámetros de física de audio y extracción espectral."""
    target_sr: int = Field(22050, description="Tasa de muestreo en Hz (ej. 22050, 32000, 44100)")
    duration_seconds: float = Field(5.0, gt=0.0, description="Ventana de análisis en segundos")
    n_mels: int = Field(128, ge=32, le=256, description="Número de bandas Mel")
    n_fft: int = Field(2048, ge=256, description="Tamaño de ventana FFT")
    hop_length: int = Field(512, ge=64, description="Salto temporal entre ventanas FFT")
    f_min: float = Field(800.0, ge=0.0, description="Frecuencia mínima para filtro Mel")
    f_max: Optional[float] = Field(None, description="Frecuencia máxima (None = Nyquist: target_sr / 2)")
    use_gpu_frontend: bool = Field(True, description="Extracción de Mel en GPU vía GPUAudioFrontEnd")

    @model_validator(mode="after")
    def validate_audio_physics(self) -> "AudioConfig":
        if self.f_max is not None and self.f_max <= self.f_min:
            raise ValueError(f"f_max ({self.f_max}) debe ser mayor que f_min ({self.f_min})")
        if self.hop_length > self.n_fft:
            raise ValueError(f"hop_length ({self.hop_length}) no puede superar n_fft ({self.n_fft})")
        return self


class AugmentationConfig(BaseModel):
    """Transformaciones estocásticas para entrenamiento."""
    time_shift_prob: float = Field(0.5, ge=0.0, le=1.0)
    max_time_shift_seconds: float = Field(0.5, ge=0.0)
    gain_prob: float = Field(0.5, ge=0.0, le=1.0)
    gain_range: Tuple[float, float] = (0.8, 1.2)
    noise_prob: float = Field(0.5, ge=0.0, le=1.0)
    noise_factor_range: Tuple[float, float] = (0.002, 0.010)
    spec_augment_prob: float = Field(0.5, ge=0.0, le=1.0)
    freq_mask_param: int = Field(8, ge=0)
    time_mask_param: int = Field(16, ge=0)
    mixup_alpha: float = Field(0.2, ge=0.0)
    mixup_prob: float = Field(0.5, ge=0.0, le=1.0)
    pitch_shift_prob: float = Field(0.0, ge=0.0, le=1.0)
    pitch_shift_bins: int = Field(2, ge=0)


class LossType(str, Enum):
    FOCAL = "focal"
    CROSS_ENTROPY = "cross_entropy"
    BCE = "bce_with_logits"


class LossConfig(BaseModel):
    """Configuración de la función de coste."""
    name: LossType = Field(LossType.FOCAL)
    gamma: float = Field(2.0, ge=0.0, description="Parámetro gamma para Focal Loss")
    reduction: Literal["mean", "sum", "none"] = "mean"


class OptimizerType(str, Enum):
    ADAM = "adam"
    ADAMW = "adamw"
    SGD = "sgd"


class OptimizerConfig(BaseModel):
    """Optimizador y política de aprendizaje."""
    name: OptimizerType = Field(OptimizerType.ADAMW)
    lr: float = Field(1e-3, gt=0.0)
    weight_decay: float = Field(1e-2, ge=0.0)
    warmup_epochs: int = Field(3, ge=0)
    scheduler: Optional[str] = Field("cosine", description="Tipo de scheduler: cosine, step, plateau o None")


class DatasetConfig(BaseModel):
    """Rutas y parámetros de ingesta de datos."""
    metadata_csv: Path
    raw_dir: Path
    cache_windows: bool = True
    num_workers: int = Field(4, ge=0)
    pin_memory: bool = True


class SplitConfig(BaseModel):
    """Partición con prevención de fuga acústica (agrupada por recordist)."""
    group_col: str = "recordist"
    target_col: str = "clase"
    train_size: float = Field(0.70, gt=0.0, lt=1.0)
    val_size: float = Field(0.15, gt=0.0, lt=1.0)
    test_size: float = Field(0.15, gt=0.0, lt=1.0)
    random_state: int = 42

    @model_validator(mode="after")
    def validate_split_sums(self) -> "SplitConfig":
        total = self.train_size + self.val_size + self.test_size
        if not abs(total - 1.0) < 1e-5:
            raise ValueError(f"Las proporciones de split deben sumar 1.0 (suma actual: {total:.4f})")
        return self


class ArchitectureConfig(BaseModel):
    """Especificación del modelo neuronal y extractor de características."""
    type: str = Field(..., description="Tipo de arquitectura: 'audio_cnn', 'efficientnet_b0', 'convnext_nano', 'resnet34d'")
    pretrained: bool = True
    in_chans: int = Field(1, ge=1, le=3)
    drop_rate: float = Field(0.3, ge=0.0, le=0.9)
    pool_type: Literal["gem", "avg", "max"] = "gem"


class TrainingConfig(BaseModel):
    """Esquema raíz para recetas de entrenamiento validadas desde YAML."""
    experiment_id: str = Field(..., description="Identificador único del experimento")
    model_id: str = Field(..., pattern=r"^[a-z0-9-_]+$", description="Slug del modelo exportable para el registry")
    model_name: str = Field(..., description="Nombre humano descriptivo")
    description: str = Field(..., description="Descripción técnica de la receta")
    epochs: int = Field(15, ge=1)
    batch_size: int = Field(16, ge=1)
    seed: int = 42
    device: Optional[str] = "cuda"

    architecture: ArchitectureConfig
    audio: AudioConfig = Field(default_factory=AudioConfig)
    augmentation: AugmentationConfig = Field(default_factory=AugmentationConfig)
    loss: LossConfig = Field(default_factory=LossConfig)
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    dataset: DatasetConfig
    split: SplitConfig = Field(default_factory=SplitConfig)
