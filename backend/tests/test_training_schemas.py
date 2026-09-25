import pytest
from pathlib import Path
from pydantic import ValidationError

from training.schemas.config import (
    AudioConfig,
    AugmentationConfig,
    LossConfig,
    LossType,
    OptimizerConfig,
    OptimizerType,
    DatasetConfig,
    SplitConfig,
    ArchitectureConfig,
    TrainingConfig,
)
from training.schemas.manifest import (
    ModelManifest,
    ManifestAudioSpecs,
    ManifestModelSpecs,
    ManifestDiagnostics,
)


def test_audio_config_valid_physics():
    cfg = AudioConfig(
        target_sr=32000,
        duration_seconds=3.0,
        n_mels=128,
        n_fft=1024,
        hop_length=512,
        f_min=100.0,
        f_max=16000.0,
    )
    assert cfg.target_sr == 32000
    assert cfg.duration_seconds == 3.0
    assert cfg.f_max == 16000.0


def test_audio_config_invalid_physics_raises():
    # f_max <= f_min
    with pytest.raises(ValidationError):
        AudioConfig(f_min=1000.0, f_max=800.0)

    # hop_length > n_fft
    with pytest.raises(ValidationError):
        AudioConfig(n_fft=512, hop_length=1024)


def test_split_config_proportions_validation():
    # Proporciones válidas (suman 1.0)
    split = SplitConfig(train_size=0.7, val_size=0.15, test_size=0.15)
    assert split.train_size == 0.7

    # Proporciones inválidas (suman 1.1)
    with pytest.raises(ValidationError):
        SplitConfig(train_size=0.7, val_size=0.2, test_size=0.2)


def test_training_config_full_instantiation():
    raw_dict = {
        "experiment_id": "exp-anfibios-01",
        "model_id": "anfibios-pam-32k",
        "model_name": "Anfibios PAM 32kHz",
        "description": "Clasificador de anfibios para monitoreo pasivo",
        "epochs": 20,
        "batch_size": 16,
        "architecture": {
            "type": "convnext_nano",
            "pretrained": True,
            "in_chans": 1,
            "pool_type": "gem",
        },
        "audio": {
            "target_sr": 32000,
            "duration_seconds": 3.0,
            "f_min": 50.0,
            "f_max": 16000.0,
        },
        "loss": {
            "name": "bce_with_logits",
        },
        "dataset": {
            "metadata_csv": Path("/tmp/data.csv"),
            "raw_dir": Path("/tmp/raw"),
        },
        "split": {
            "train_size": 0.8,
            "val_size": 0.1,
            "test_size": 0.1,
        },
    }

    cfg = TrainingConfig.model_validate(raw_dict)
    assert cfg.model_id == "anfibios-pam-32k"
    assert cfg.audio.target_sr == 32000
    assert cfg.loss.name == LossType.BCE
    assert cfg.architecture.type == "convnext_nano"


def test_model_manifest_validation():
    manifest = ModelManifest(
        model_id="anfibios-pam-32k",
        name="Anfibios PAM 32kHz",
        description="Modelo exportado para serving",
        created_at="2026-09-15T22:00:00Z",
        classes=["Batrachyla leptopus", "Pleurodema thaul"],
        audio_specs=ManifestAudioSpecs(
            target_sr=32000,
            duration_seconds=3.0,
            n_mels=128,
            n_fft=1024,
            hop_length=512,
            f_min=50.0,
            f_max=16000.0,
        ),
        model_specs=ManifestModelSpecs(
            architecture_family="timm_bioacoustic",
            backbone="convnext_nano",
            in_channels=1,
            pool_type="gem",
            weights_file="weights.pt",
        ),
        metrics={"f1_macro": 0.892},
    )

    assert manifest.model_id == "anfibios-pam-32k"
    assert manifest.audio_specs.target_sr == 32000
    assert len(manifest.classes) == 2
    assert manifest.model_specs.backbone == "convnext_nano"
