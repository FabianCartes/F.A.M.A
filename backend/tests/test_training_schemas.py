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


def test_dataset_config_path_resolution_docker_root(monkeypatch, tmp_path):
    """
    Verifica que en entornos de contenedor donde get_project_root() es /app
    (sin carpeta /app/backend), rutas relativas con prefijo 'backend/data/raw'
    o 'data/raw' resuelvan canónicamente a get_raw_data_dir() en vez de /app/backend/data/raw.
    """
    from training.paths import get_raw_data_dir

    fake_app = tmp_path / "app"
    fake_raw = fake_app / "data" / "raw"
    fake_raw.mkdir(parents=True)

    monkeypatch.setattr("training.paths.get_project_root", lambda: fake_app)
    monkeypatch.setattr(
        "training.paths.get_raw_data_dir",
        lambda dataset_name=None: (fake_raw / dataset_name) if dataset_name else fake_raw,
    )

    ds = DatasetConfig(
        metadata_csv=Path("backend/data/raw/engine_diagnostics/train_metadata.csv"),
        raw_dir=Path("backend/data/raw/engine_diagnostics"),
    )

    assert ds.raw_dir == fake_raw / "engine_diagnostics"
    assert ds.metadata_csv == fake_raw / "engine_diagnostics" / "train_metadata.csv"

    # También con prefijo data/raw
    ds2 = DatasetConfig(
        metadata_csv=Path("data/raw/engine_diagnostics/train_metadata.csv"),
        raw_dir=Path("data/raw/engine_diagnostics"),
    )
    assert ds2.raw_dir == fake_raw / "engine_diagnostics"
    assert ds2.metadata_csv == fake_raw / "engine_diagnostics" / "train_metadata.csv"


# ============================================================================
# TESTS: Selector Dinámico de Ensamble (DTOs y Validación de Schemas)
# ============================================================================
from app.schemas.training import (
    ModelEnsembleItem,
    StartTrainingRequest,
    VALID_ARCHITECTURES,
    AudioConfigSchema,
    WindowingConfigSchema,
    RegularizationConfigSchema,
)


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


# ============================================================================
# TESTS: Parametrización Universal Multi-Dominio (Slice 1)
# ============================================================================

def test_audio_config_schema_valid():
    cfg = AudioConfigSchema(
        target_sr=16000,
        duration_seconds=2.0,
        f_min=50.0,
        f_max=4000.0,
        n_mels=128,
        n_fft=1024,
        hop_length=256,
    )
    assert cfg.target_sr == 16000
    assert cfg.duration_seconds == 2.0
    assert cfg.f_min == 50.0
    assert cfg.f_max == 4000.0
    assert cfg.n_mels == 128
    assert cfg.n_fft == 1024
    assert cfg.hop_length == 256


def test_audio_config_schema_nyquist_violation_raises():
    # f_max > target_sr / 2 (ej: 9000 > 16000 / 2 = 8000)
    with pytest.raises(ValidationError) as exc:
        AudioConfigSchema(
            target_sr=16000,
            duration_seconds=2.0,
            f_min=50.0,
            f_max=9000.0,
        )
    assert "Nyquist" in str(exc.value)


def test_audio_config_schema_fmin_ge_fmax_raises():
    with pytest.raises(ValidationError):
        AudioConfigSchema(
            target_sr=22050,
            duration_seconds=3.0,
            f_min=5000.0,
            f_max=4000.0,
        )

    with pytest.raises(ValidationError):
        AudioConfigSchema(
            target_sr=22050,
            duration_seconds=3.0,
            f_min=4000.0,
            f_max=4000.0,
        )


def test_audio_config_schema_hop_greater_than_nfft_raises():
    with pytest.raises(ValidationError):
        AudioConfigSchema(
            target_sr=22050,
            duration_seconds=3.0,
            n_fft=512,
            hop_length=1024,
            f_min=100.0,
            f_max=8000.0,
        )


def test_audio_config_schema_bounds_validation():
    # target_sr bounds: ge=8000, le=48000
    with pytest.raises(ValidationError):
        AudioConfigSchema(target_sr=4000)
    with pytest.raises(ValidationError):
        AudioConfigSchema(target_sr=96000)

    # duration_seconds bounds: ge=0.5, le=30.0
    with pytest.raises(ValidationError):
        AudioConfigSchema(duration_seconds=0.2)
    with pytest.raises(ValidationError):
        AudioConfigSchema(duration_seconds=35.0)

    # n_mels bounds: ge=32, le=256
    with pytest.raises(ValidationError):
        AudioConfigSchema(n_mels=16)
    with pytest.raises(ValidationError):
        AudioConfigSchema(n_mels=512)

    # n_fft ge=256
    with pytest.raises(ValidationError):
        AudioConfigSchema(n_fft=128)

    # hop_length ge=64
    with pytest.raises(ValidationError):
        AudioConfigSchema(hop_length=32)

    # f_min ge=0.0
    with pytest.raises(ValidationError):
        AudioConfigSchema(f_min=-10.0)

    # f_max ge=100.0
    with pytest.raises(ValidationError):
        AudioConfigSchema(f_max=50.0)


def test_windowing_config_schema_valid_and_bounds():
    win = WindowingConfigSchema(
        hop_seconds=0.5,
        aggregation_mode="max",
        gem_p=3.0,
        vad_threshold=0.05,
    )
    assert win.hop_seconds == 0.5
    assert win.aggregation_mode == "max"
    assert win.gem_p == 3.0
    assert win.vad_threshold == 0.05

    # hop_seconds <= 0.0 raises
    with pytest.raises(ValidationError):
        WindowingConfigSchema(hop_seconds=0.0)
    with pytest.raises(ValidationError):
        WindowingConfigSchema(hop_seconds=-0.5)

    # aggregation_mode invalid
    with pytest.raises(ValidationError):
        WindowingConfigSchema(aggregation_mode="median")

    # gem_p bounds: ge=1.0, le=10.0
    with pytest.raises(ValidationError):
        WindowingConfigSchema(gem_p=0.5)
    with pytest.raises(ValidationError):
        WindowingConfigSchema(gem_p=12.0)

    # vad_threshold bounds: ge=0.0, le=1.0
    with pytest.raises(ValidationError):
        WindowingConfigSchema(vad_threshold=-0.1)
    with pytest.raises(ValidationError):
        WindowingConfigSchema(vad_threshold=1.5)


def test_regularization_config_schema_valid_and_bounds():
    reg = RegularizationConfigSchema(
        loss_type="focal",
        focal_gamma=2.5,
        mixup_enabled=True,
        mixup_alpha=0.4,
        pitch_shift_enabled=False,
    )
    assert reg.loss_type == "focal"
    assert reg.focal_gamma == 2.5
    assert reg.mixup_enabled is True
    assert reg.mixup_alpha == 0.4
    assert reg.pitch_shift_enabled is False

    # loss_type invalid
    with pytest.raises(ValidationError):
        RegularizationConfigSchema(loss_type="dice")

    # focal_gamma < 0.0
    with pytest.raises(ValidationError):
        RegularizationConfigSchema(focal_gamma=-1.0)

    # mixup_alpha < 0.0
    with pytest.raises(ValidationError):
        RegularizationConfigSchema(mixup_alpha=-0.2)


def test_start_training_request_with_multi_domain_configs():
    audio = AudioConfigSchema(
        target_sr=16000,
        duration_seconds=2.0,
        f_min=50.0,
        f_max=4000.0,
        n_mels=128,
        n_fft=1024,
        hop_length=256,
    )
    windowing = WindowingConfigSchema(
        hop_seconds=0.5,
        aggregation_mode="max",
        gem_p=3.0,
        vad_threshold=0.0,
    )
    regularization = RegularizationConfigSchema(
        loss_type="focal",
        focal_gamma=2.0,
        mixup_enabled=False,
        pitch_shift_enabled=False,
    )

    req = StartTrainingRequest(
        dataset_name="medical_cough",
        audio_config=audio,
        windowing_config=windowing,
        regularization_config=regularization,
    )

    assert req.audio_config is not None
    assert req.audio_config.target_sr == 16000
    assert req.audio_config.f_max == 4000.0
    assert req.windowing_config is not None
    assert req.windowing_config.hop_seconds == 0.5
    assert req.regularization_config is not None
    assert req.regularization_config.loss_type == "focal"

    # Retrocompatibilidad: si no se proveen, son None
    req_default = StartTrainingRequest(dataset_name="AvesChilenas")
    assert req_default.audio_config is None
    assert req_default.windowing_config is None
    assert req_default.regularization_config is None


def test_start_training_request_weight_decay():
    # 1. Default value is 0.01 (AdamW canonical default)
    req = StartTrainingRequest(dataset_name="AvesChilenas")
    assert hasattr(req, "weight_decay")
    assert req.weight_decay == 0.01

    # 2. Custom valid weight_decay
    req_custom = StartTrainingRequest(dataset_name="AvesChilenas", weight_decay=0.05)
    assert req_custom.weight_decay == 0.05

    # 3. Invalid negative weight_decay raises ValidationError
    with pytest.raises(ValidationError):
        StartTrainingRequest(dataset_name="AvesChilenas", weight_decay=-0.01)

    # 4. Invalid excessive weight_decay (> 1.0) raises ValidationError
    with pytest.raises(ValidationError):
        StartTrainingRequest(dataset_name="AvesChilenas", weight_decay=1.5)


def test_model_ensemble_item_epochs_validation():
    # 1. Por defecto, epochs es None (retrocompatibilidad)
    item_default = ModelEnsembleItem(architecture="EfficientNet-B0", weight=0.5)
    assert hasattr(item_default, "epochs")
    assert item_default.epochs is None

    # 2. epochs explícito válido
    item_custom = ModelEnsembleItem(architecture="ResNet-34d", weight=0.5, epochs=35)
    assert item_custom.epochs == 35

    # 3. epochs <= 0 debe fallar
    with pytest.raises(ValidationError):
        ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=0.5, epochs=0)

    # 4. epochs hasta 1000 es valido, > 1000 debe fallar
    item_max = ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=0.5, epochs=1000)
    assert item_max.epochs == 1000

    with pytest.raises(ValidationError):
        ModelEnsembleItem(architecture="ConvNeXt-Nano", weight=0.5, epochs=1001)


def test_start_training_request_preserves_model_epochs():
    req = StartTrainingRequest(
        models=[
            {"architecture": "ResNet-34d", "weight": 0.6, "epochs": 35},
            {"architecture": "EfficientNet-B0", "weight": 0.4, "epochs": 10},
        ]
    )
    assert req.models[0].epochs == 35
    assert req.models[1].epochs == 10





