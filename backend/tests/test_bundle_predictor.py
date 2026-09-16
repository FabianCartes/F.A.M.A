import tempfile
from pathlib import Path
import json
import torch
import torch.nn as nn
import pytest

from training.schemas.config import (
    TrainingConfig,
    AudioConfig,
    ArchitectureConfig,
    LossConfig,
    DatasetConfig,
    SplitConfig,
)
from training.exporters.bundle_exporter import BundleExporter
from app.services.predictors.bundle_predictor import BundleAudioPredictor
from app.services.registry import ModelRegistry, discover_and_register_bundles


class SimpleCNN(nn.Module):
    def __init__(self, num_classes=2):
        super().__init__()
        self.conv = nn.Conv2d(1, 4, 3)
        self.pool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(4, num_classes)

    def forward(self, x):
        return self.fc(self.pool(self.conv(x)).flatten(1))


@pytest.fixture
def created_bundle_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        cfg = TrainingConfig(
            experiment_id="exp-auto-01",
            model_id="bundle-anfibios-test",
            model_name="Anfibios Bundle Test",
            description="Modelo exportado para prueba de serving",
            epochs=1,
            batch_size=2,
            architecture=ArchitectureConfig(type="audio_cnn", pretrained=False),
            audio=AudioConfig(target_sr=32000, duration_seconds=3.0, n_mels=64),
            loss=LossConfig(name="cross_entropy"),
            dataset=DatasetConfig(metadata_csv=Path("/tmp/m.csv"), raw_dir=Path("/tmp/r")),
            split=SplitConfig(),
        )
        model = SimpleCNN(num_classes=2)
        classes = ["Rana chilena", "Sapito de cuatro ojos"]
        metrics = {"f1_macro": 0.885}

        bundle_path = BundleExporter.export(
            output_dir=root,
            model=model,
            config=cfg,
            classes=classes,
            metrics=metrics,
        )
        yield root, bundle_path


def test_bundle_audio_predictor_reads_manifest(created_bundle_dir):
    _, bundle_path = created_bundle_dir
    predictor = BundleAudioPredictor(bundle_dir=bundle_path)

    assert predictor.model_id == "bundle-anfibios-test"
    meta = predictor.metadata
    assert meta.id == "bundle-anfibios-test"
    assert meta.target_sr == 32000
    assert meta.duration_seconds == 3.0
    assert meta.classes == ["Rana chilena", "Sapito de cuatro ojos"]
    assert meta.metrics["f1_macro"] == 0.885


def test_discover_and_register_bundles(created_bundle_dir):
    root, _ = created_bundle_dir
    registry = ModelRegistry()

    assert not registry.has_model("bundle-anfibios-test")

    # Ejecutar autodescubrimiento
    discover_and_register_bundles(registry=registry, checkpoints_root=root)

    assert registry.has_model("bundle-anfibios-test")
    predictor = registry.get("bundle-anfibios-test")
    assert predictor.model_id == "bundle-anfibios-test"


def test_discover_bundles_handles_corrupted_manifest_gracefully():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        corrupt_dir = root / "corrupt_bundle"
        corrupt_dir.mkdir()
        # Escribir manifest roto
        (corrupt_dir / "manifest.json").write_text("{ broken json: true", encoding="utf-8")

        registry = ModelRegistry()
        # No debe lanzar excepción no controlada
        discover_and_register_bundles(registry=registry, checkpoints_root=root)
        assert len(registry.list_models()) == 0
