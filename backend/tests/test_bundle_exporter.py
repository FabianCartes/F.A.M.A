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
from training.schemas.manifest import ModelManifest
from training.exporters.bundle_exporter import BundleExporter


class DummyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(10, 2)

    def forward(self, x):
        return self.fc(x)


@pytest.fixture
def dummy_training_config():
    return TrainingConfig(
        experiment_id="exp-test-01",
        model_id="test-exported-bundle",
        model_name="Test Exported Bundle",
        description="Bundle creado para testing unitario",
        epochs=1,
        batch_size=4,
        architecture=ArchitectureConfig(type="audio_cnn", pretrained=False),
        audio=AudioConfig(target_sr=32000, duration_seconds=3.0, n_mels=64),
        loss=LossConfig(name="cross_entropy"),
        dataset=DatasetConfig(metadata_csv=Path("/tmp/m.csv"), raw_dir=Path("/tmp/r")),
        split=SplitConfig(),
    )


def test_bundle_exporter_creates_complete_package(dummy_training_config):
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir)
        model = DummyModel()
        classes = ["Especie 1", "Especie 2"]
        metrics = {"f1_macro": 0.912, "accuracy": 0.934}

        bundle_path = BundleExporter.export(
            output_dir=output_dir,
            model=model,
            config=dummy_training_config,
            classes=classes,
            metrics=metrics,
        )

        assert bundle_path.exists()
        assert bundle_path.is_dir()
        assert bundle_path.name == "test-exported-bundle"

        # Verificar archivos esenciales
        manifest_file = bundle_path / "manifest.json"
        weights_file = bundle_path / "weights.pt"
        recipe_file = bundle_path / "training_recipe.yaml"

        assert manifest_file.exists()
        assert weights_file.exists()
        assert recipe_file.exists()

        # Validar contenido de manifest.json contra Pydantic
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        manifest = ModelManifest.model_validate(manifest_data)
        assert manifest.model_id == "test-exported-bundle"
        assert manifest.audio_specs.target_sr == 32000
        assert manifest.classes == ["Especie 1", "Especie 2"]
        assert manifest.metrics["f1_macro"] == 0.912

        # Validar que weights.pt contenga el state_dict de PyTorch
        state_dict = torch.load(weights_file, weights_only=True)
        assert "fc.weight" in state_dict
