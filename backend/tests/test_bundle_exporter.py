import tempfile
import hashlib
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
        dataset_name="fixture",
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


def _evaluation_entries(bundle, *, class_override=None, val_overrides=None, test_overrides=None):
    from app.schemas.evaluation import EvaluationProvenance
    from ml_core.classification_metrics import calculate_classification_report

    manifest = ModelManifest.model_validate_json((bundle / "manifest.json").read_text())
    digest = hashlib.sha256((bundle / "weights.pt").read_bytes()).hexdigest()
    from app.services.predictors.bundle_predictor import BundleAudioPredictor

    effective = BundleAudioPredictor(bundle).evaluation_config
    base_classes = class_override or manifest.classes
    entries = {}
    for split, overrides in (("val", val_overrides or {}), ("test", test_overrides or {})):
        classes = overrides.get("classes", base_classes)
        schema_version = overrides.get("schema_version", 1)
        provenance = EvaluationProvenance(
            schema_version=schema_version,
            evaluator_version=overrides.get("evaluator_version", "recording-v1"),
            checkpoint_sha256=digest,
            dataset=overrides.get("dataset", "fixture"), split=split,
            manifest_sha256=("c" if split == "val" else "d") * 64, classes=classes,
            sample_count=2,
            predictor_config=overrides.get("predictor_config", effective["predictor_config"]),
            preprocessing_config=overrides.get("preprocessing_config", effective["preprocessing_config"]),
            aggregation_config=overrides.get("aggregation_config", effective["aggregation_config"]),
        )
        entries[split] = {
            "provenance": provenance.model_dump(),
            "report": calculate_classification_report(
                classes, classes, classes,
                rejection_label="__rejected__" if schema_version == 2 else None,
            ),
        }
    return entries


def test_official_bundle_manifest_roundtrips_weight_bound_split_reports(dummy_training_config, tmp_path):
    model = DummyModel()
    provisional_root = tmp_path / '.test-exported-bundle.provisional-valid'
    bundle = BundleExporter.export(provisional_root, model, dummy_training_config, ['a', 'b'])
    digest = hashlib.sha256((bundle / 'weights.pt').read_bytes()).hexdigest()
    reports = _evaluation_entries(bundle)
    published = BundleExporter.publish_official(bundle, reports)
    manifest = ModelManifest.model_validate_json((published / 'manifest.json').read_text())
    assert manifest.final_evaluations.weights_sha256 == digest
    assert set(manifest.final_evaluations.reports) == {'val', 'test'}
    assert manifest.final_evaluations.reports['test'].report['metrics']['accuracy'] == 1.0
    assert not bundle.exists()


def _provisional_bundle(tmp_path, config):
    stage = tmp_path / f".{config.model_id}.provisional-test"
    return BundleExporter.export(stage, DummyModel(), config, ["a", "b"])


def test_official_publish_rejects_report_class_order_different_from_bundle(dummy_training_config, tmp_path):
    bundle = _provisional_bundle(tmp_path, dummy_training_config)
    reports = _evaluation_entries(bundle, class_override=["b", "a"])
    with pytest.raises(ValueError):
        BundleExporter.publish_official(bundle, reports)
    assert bundle.is_dir()
    assert not (tmp_path / dummy_training_config.model_id).exists()


@pytest.mark.parametrize("field", [
    "dataset", "evaluator_version", "predictor_config", "preprocessing_config", "aggregation_config",
])
def test_official_publish_rejects_val_test_identity_mismatch(dummy_training_config, tmp_path, field):
    bundle = _provisional_bundle(tmp_path, dummy_training_config)
    reports = _evaluation_entries(bundle)
    reports["test"]["provenance"][field] = (
        "other-dataset" if field == "dataset" else
        "recording-other" if field == "evaluator_version" else {"changed": True}
    )
    # Keep the test report internally valid after changing provenance.
    from app.schemas.evaluation import EvaluationProvenance
    reports["test"]["provenance"] = EvaluationProvenance.model_validate(
        reports["test"]["provenance"]
    ).model_dump()
    with pytest.raises(ValueError):
        BundleExporter.publish_official(bundle, reports)
    assert bundle.is_dir()
    assert not (tmp_path / dummy_training_config.model_id).exists()


def test_official_publish_rejects_val_test_schema_version_mismatch(dummy_training_config, tmp_path):
    bundle = _provisional_bundle(tmp_path, dummy_training_config)
    reports = _evaluation_entries(bundle, test_overrides={"schema_version": 2})
    with pytest.raises(ValueError):
        BundleExporter.publish_official(bundle, reports)
    assert bundle.is_dir()
    assert not (tmp_path / dummy_training_config.model_id).exists()


def test_official_publish_rejects_manifest_config_mutated_after_evaluation(dummy_training_config, tmp_path):
    bundle = _provisional_bundle(tmp_path, dummy_training_config)
    reports = _evaluation_entries(bundle)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["audio_specs"]["target_sr"] = 16000
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        BundleExporter.publish_official(bundle, reports)
    assert bundle.is_dir()
    assert not (tmp_path / dummy_training_config.model_id).exists()
