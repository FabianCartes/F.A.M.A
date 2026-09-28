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


def test_dataset_config_path_resolution():
    from training.paths import get_project_root, get_raw_data_dir

    ds = DatasetConfig(
        metadata_csv=Path("backend/data/raw/engine_diagnostics/train_metadata.csv"),
        raw_dir=Path("backend/data/raw/engine_diagnostics"),
    )

    assert ds.metadata_csv.is_absolute()
    assert ds.raw_dir.is_absolute()
    assert ds.raw_dir == get_raw_data_dir("engine_diagnostics")
    assert ds.metadata_csv == get_raw_data_dir("engine_diagnostics") / "train_metadata.csv"


# ============================================================================
# TESTS: Selector Dinámico de Ensamble (DTOs y Validación de Schemas)
# ============================================================================
from app.schemas.training import ModelEnsembleItem, StartTrainingRequest, VALID_ARCHITECTURES


def test_model_ensemble_item_valid():
    item = ModelEnsembleItem(architecture="EfficientNet-B0", weight=0.6)
    assert item.architecture == "EfficientNet-B0"
    assert item.weight == 0.6


def test_model_ensemble_item_invalid_architecture():
    with pytest.raises(ValidationError):
        ModelEnsembleItem(architecture="NonExistentNet", weight=0.5)


def test_model_ensemble_item_invalid_weight():
    with pytest.raises(ValidationError):
        ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=-0.1)

    with pytest.raises(ValidationError):
        ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=1.5)


def test_start_training_request_dynamic_models_valid():
    # 1 modelo
    req1 = StartTrainingRequest(
        models=[ModelEnsembleItem(architecture="EfficientNet-B0", weight=1.0)]
    )
    assert len(req1.models) == 1
    assert req1.models[0].architecture == "EfficientNet-B0"
    assert req1.models[0].weight == 1.0

    # 2 modelos (Dúo)
    req2 = StartTrainingRequest(
        models=[
            ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=0.6),
            ModelEnsembleItem(architecture="EfficientNet-B0", weight=0.4),
        ]
    )
    assert len(req2.models) == 2
    assert req2.models[0].weight == 0.6
    assert req2.models[1].weight == 0.4

    # 3 modelos (Tríada personalizada)
    req3 = StartTrainingRequest(
        models=[
            ModelEnsembleItem(architecture="PANNs-CNN14", weight=0.5),
            ModelEnsembleItem(architecture="ResNet-34d", weight=0.3),
            ModelEnsembleItem(architecture="AudioCNN", weight=0.2),
        ]
    )
    assert len(req3.models) == 3


def test_start_training_request_models_length_limits():
    # Lista vacía debe fallar
    with pytest.raises(ValidationError):
        StartTrainingRequest(models=[])

    # Más de 3 modelos debe fallar
    with pytest.raises(ValidationError):
        StartTrainingRequest(
            models=[
                ModelEnsembleItem(architecture="EfficientNet-B0", weight=0.25),
                ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=0.25),
                ModelEnsembleItem(architecture="ResNet-34d", weight=0.25),
                ModelEnsembleItem(architecture="AudioCNN", weight=0.25),
            ]
        )


def test_start_training_request_weight_normalization():
    # Ponderaciones que no suman 1.0 se normalizan determinísticamente
    req = StartTrainingRequest(
        models=[
            ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=0.3),
            ModelEnsembleItem(architecture="EfficientNet-B0", weight=0.3),
        ]
    )
    assert len(req.models) == 2
    total = sum(m.weight for m in req.models)
    assert total == pytest.approx(1.0, abs=1e-3)
    assert req.models[0].weight == pytest.approx(0.5, abs=1e-3)
    assert req.models[1].weight == pytest.approx(0.5, abs=1e-3)

    # Si todas las ponderaciones son 0, debe fallar
    with pytest.raises(ValidationError):
        StartTrainingRequest(
            models=[
                ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=0.0),
                ModelEnsembleItem(architecture="EfficientNet-B0", weight=0.0),
            ]
        )


def test_start_training_request_backward_compatibility():
    # Caso 1: Modelo individual clásico sin especificar `models`
    req_single = StartTrainingRequest(
        architecture="ResNet-34d",
        is_tri_model=False,
    )
    assert req_single.models is not None
    assert len(req_single.models) == 1
    assert req_single.models[0].architecture == "ResNet-34d"
    assert req_single.models[0].weight == 1.0

    # Caso 2: Tríada clásica para AvesChilenas
    req_triad_aves = StartTrainingRequest(
        dataset_name="AvesChilenas",
        is_tri_model=True,
    )
    assert req_triad_aves.models is not None
    assert len(req_triad_aves.models) == 3
    assert [m.architecture for m in req_triad_aves.models] == [
        "EfficientNet-B0",
        "ConvNeXt-Nano",
        "ResNet-34d",
    ]
    assert sum(m.weight for m in req_triad_aves.models) == pytest.approx(1.0, abs=1e-3)

    # Caso 3: Tríada clásica para MotoresVehiculares / engine_diagnostics
    req_triad_eng = StartTrainingRequest(
        dataset_name="engine_diagnostics",
        is_tri_model=True,
    )
    assert req_triad_eng.models is not None
    assert len(req_triad_eng.models) == 3
    assert [m.architecture for m in req_triad_eng.models] == [
        "ResNet-34d",
        "EfficientNet-B0",
        "PANNs-CNN14",
    ]
    assert sum(m.weight for m in req_triad_eng.models) == pytest.approx(1.0, abs=1e-3)


