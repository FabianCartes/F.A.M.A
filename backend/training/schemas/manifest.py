"""
backend/training/schemas/manifest.py
Contrato declarativo del manifest.json para serialización y auto-descubrimiento en ModelRegistry.
"""
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class ManifestAudioSpecs(BaseModel):
    target_sr: int = 22050
    duration_seconds: float = 5.0
    n_mels: int = 128
    n_fft: int = 2048
    hop_length: int = 512
    f_min: float = 800.0
    f_max: Optional[float] = None
    use_gpu_frontend: bool = True


class ManifestModelSpecs(BaseModel):
    architecture_family: Literal["audio_cnn", "timm_bioacoustic", "ensemble"]
    backbone: str = Field(..., description="ej. 'efficientnet_b0', 'convnext_nano', 'custom_cnn'")
    in_channels: int = 1
    pool_type: str = "gem"
    weights_file: str = "weights.pt"


class ManifestDiagnostics(BaseModel):
    spectral_flatness_noise_threshold: float = 0.15
    rms_silence_threshold: float = 0.001
    default_temperature: float = 1.0


class ModelManifest(BaseModel):
    schema_version: str = Field("1.0.0", description="Versión del contrato de manifest")
    model_id: str = Field(..., description="Slug único registrado en ModelRegistry")
    name: str = Field(..., description="Nombre amigable para /api/models")
    description: str = Field(..., description="Descripción técnica y origen del bundle")
    created_at: str
    is_default: bool = False
    classes: List[str] = Field(..., description="Taxonomía mapeada a la salida del tensor (idx -> clase)")
    audio_specs: ManifestAudioSpecs
    model_specs: ManifestModelSpecs
    diagnostics: ManifestDiagnostics = Field(default_factory=ManifestDiagnostics)
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Métricas de test: val_acc, f1_macro, etc.")
