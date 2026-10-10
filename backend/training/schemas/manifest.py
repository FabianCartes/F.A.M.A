"""
backend/training/schemas/manifest.py
Contrato declarativo del manifest.json para serialización y auto-descubrimiento en ModelRegistry.
"""
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.evaluation import EvaluationProvenance, validate_report


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


class FinalEvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provenance: EvaluationProvenance
    report: Dict[str, Any]

    @model_validator(mode="after")
    def validate_report_provenance(self):
        validate_report(self.report, self.provenance)
        return self


class FinalEvaluations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reports: Dict[Literal["val", "test"], FinalEvaluationRecord]

    @model_validator(mode="after")
    def validate_final_pair(self):
        if set(self.reports) != {"val", "test"}:
            raise ValueError("Official final evaluation requires val and test reports")
        for split, evaluation in self.reports.items():
            if evaluation.provenance.split != split:
                raise ValueError("Report split does not match its manifest key")
            if evaluation.provenance.checkpoint_sha256 != self.weights_sha256:
                raise ValueError("Evaluation weights hash does not match bundle weights")
        return self


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
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Legacy training-loop metrics; not final reports.")
    dataset_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    final_evaluations: Optional[FinalEvaluations] = None

    def effective_inference_config(self) -> Dict[str, Dict[str, Any]]:
        """Canonical effective configuration shared by inference and report validation."""
        audio = {
            key: value for key, value in self.audio_specs.model_dump(mode="json").items()
            if key != "use_gpu_frontend"
        }
        diagnostics = self.diagnostics.model_dump(mode="json")
        return {
            "predictor_config": {
                "architecture_family": self.model_specs.architecture_family,
                "backbone": self.model_specs.backbone,
                "in_channels": self.model_specs.in_channels,
                "pool_type": self.model_specs.pool_type,
            },
            "preprocessing_config": {
                "audio_specs": audio,
                "diagnostics": diagnostics,
                "resampling": {
                    "implementation": "librosa.load-default-resampler",
                    "target_sr": audio["target_sr"],
                    "mono": True,
                    "crop": "maximum-rms-window-v1",
                    "crop_hop_seconds": min(1.0, audio["duration_seconds"] / 2.0),
                    "short_audio_padding": "right-zero",
                },
                "frontend": {
                    "implementation": "librosa.feature.melspectrogram-v1",
                    "window": "hann",
                    "win_length": None,
                    "center": True,
                    "pad_mode": "constant",
                    "power": 2.0,
                    "mel_scale_htk": False,
                    "mel_norm": "slaney",
                    "power_to_db_reference": "per-window-maximum",
                    "power_to_db_amin": 1e-10,
                    "power_to_db_top_db": 80.0,
                    "normalization": "relative-db-to-window-maximum",
                },
                "filters": {
                    "rms_silence_threshold": diagnostics["rms_silence_threshold"],
                    "spectral_flatness_noise_threshold": diagnostics["spectral_flatness_noise_threshold"],
                    "spectral_flatness": {
                        "implementation": "librosa.feature.spectral_flatness",
                        "n_fft": 2048,
                        "hop_length": 512,
                        "win_length": None,
                        "window": "hann",
                        "center": True,
                        "pad_mode": "reflect",
                        "power": 2.0,
                    },
                },
            },
            "aggregation_config": {
                "algorithm": "temperature_softmax_max_probability_over_active_1s_windows-v1",
                "window_seconds": audio["duration_seconds"],
                "window_hop_seconds": 1.0,
                "active_window_rms_threshold": diagnostics["rms_silence_threshold"],
                "temperature": diagnostics["default_temperature"],
                "probability_aggregation": "classwise-max",
                "rejected_statuses": ["silence", "noise"],
            },
        }

    @model_validator(mode="after")
    def validate_final_evaluation_binding(self):
        if self.final_evaluations is None:
            return self
        if self.dataset_name is None or not self.dataset_name.strip():
            raise ValueError("Official final evaluations require explicit dataset_name")
        expected = self.effective_inference_config()
        reference = None
        for split, entry in self.final_evaluations.reports.items():
            provenance = entry.provenance
            if provenance.dataset != self.dataset_name:
                raise ValueError("Final report dataset does not match bundle dataset")
            if provenance.classes != self.classes:
                raise ValueError("Final report class order does not match bundle classes")
            for field, config in expected.items():
                if getattr(provenance, field) != config:
                    raise ValueError(f"Final report {field} does not match effective bundle configuration")
            comparable = {
                "schema_version": provenance.schema_version,
                "evaluator_version": provenance.evaluator_version,
                "dataset": provenance.dataset,
                "classes": provenance.classes,
                "checkpoint_sha256": provenance.checkpoint_sha256,
                "predictor_config": provenance.predictor_config,
                "preprocessing_config": provenance.preprocessing_config,
                "aggregation_config": provenance.aggregation_config,
                "code_revision": provenance.code_revision,
            }
            if reference is None:
                reference = comparable
            elif comparable != reference:
                raise ValueError("Validation and test provenance must share one predictor identity")
            if provenance.split != split:
                raise ValueError("Final report split does not match its manifest key")
        return self
