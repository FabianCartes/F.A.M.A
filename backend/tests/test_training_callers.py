"""Public training entrypoints prepare canonical rows before expensive ML work."""
import numpy as np
import pandas as pd
import pytest
import soundfile as sf
import torch
import yaml

from training.schemas.config import TrainingConfig
from training.trainers.standalone_trainer import GenericModelTrainer


class PreparedSplits(Exception):
    """Stop at the torch loader boundary, before model construction/training."""


@pytest.fixture
def source(tmp_path):
    roots = {stage: tmp_path / stage for stage in ("raw", "processed")}
    for stage, root in roots.items():
        root.mkdir()
        # Same name, different physical audio: extension cannot select the stage.
        sf.write(root / "001.wav", np.full(8000, 0.25 if stage == "raw" else -0.5), 8000)
    frame = pd.DataFrame([{
        "file_path": "001.wav", "file_stage": "processed", "clase": "normal",
        "id": "001", "source_group": "0007", "recordist": "009",
        "hash": "00abc", "labels": "['normal']",
    }])
    config = TrainingConfig.model_validate({
        "experiment_id": "fixture", "model_id": "fixture", "model_name": "Fixture",
        "description": "Temporary source", "device": "cpu", "epochs": 1,
        "architecture": {"type": "audio_cnn", "pretrained": False},
        "audio": {"target_sr": 8000, "duration_seconds": 1.0},
        "augmentation": {"gain_prob": 0, "noise_prob": 0},
        "dataset": {"metadata_csv": roots["raw"] / "train_metadata.csv",
                    "raw_dir": roots["raw"], "num_workers": 0},
    })
    return roots, frame, config


def stop_after_preparation(monkeypatch):
    prepared = []

    def loader(dataset, **kwargs):
        waveform, label = dataset[0]
        prepared.append((dataset.df.copy(deep=True), waveform, label))
        if len(prepared) == 3:
            raise PreparedSplits
        return []

    monkeypatch.setattr("training.trainers.standalone_trainer.DataLoader", loader)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    return prepared


@pytest.mark.parametrize("stage,level", [("raw", 0.25), ("processed", -0.5)])
def test_trainer_prepares_all_splits_with_explicit_custom_roots(source, tmp_path, monkeypatch, stage, level):
    roots, frame, config = source
    frame = frame.assign(file_stage=stage)
    prepared = stop_after_preparation(monkeypatch)
    trainer = GenericModelTrainer(config, project_root=tmp_path)
    with pytest.raises(PreparedSplits):
        trainer.train_and_export(frame, frame, frame, tmp_path / "checkpoints", roots=roots)
    assert len(prepared) == 3
    for actual, waveform, label in prepared:
        pd.testing.assert_frame_equal(actual, frame)
        assert torch.allclose(waveform, torch.full((8000,), level))
        assert label.item() == 0


@pytest.mark.parametrize("split", [0, 1, 2])
@pytest.mark.parametrize("invalid", ["missing_stage", "missing_path", "absolute", "unknown_stage", "missing_file", "missing_root", "alias"])
def test_trainer_rejects_invalid_split_before_ml(source, tmp_path, monkeypatch, split, invalid):
    roots, frame, config = source
    stop_after_preparation(monkeypatch)
    frames = [frame.copy(deep=True) for _ in range(3)]
    if invalid == "missing_stage":
        frames[split] = frame.drop(columns="file_stage")
    elif invalid == "missing_path":
        frames[split] = frame.drop(columns="file_path")
    elif invalid == "absolute":
        frames[split].loc[0, "file_path"] = str(roots["processed"] / "001.wav")
    elif invalid == "unknown_stage":
        frames[split].loc[0, "file_stage"] = "legacy"
    elif invalid == "missing_file":
        frames[split].loc[0, "file_path"] = "absent.wav"
    elif invalid == "missing_root":
        roots = {"raw": roots["raw"]}
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(roots["processed"], target_is_directory=True)
        roots = {**roots, "processed": alias}
    trainer = GenericModelTrainer(config, project_root=tmp_path)
    with pytest.raises(ValueError):
        trainer.train_and_export(*frames, tmp_path / "checkpoints", roots=roots)


def test_trainer_requires_root_binding(source, tmp_path):
    _, frame, config = source
    trainer = GenericModelTrainer(config, project_root=tmp_path)
    with pytest.raises(TypeError, match="roots"):
        trainer.train_and_export(frame, frame, frame, tmp_path / "checkpoints")


def test_car_entrypoint_preserves_canonical_csv_identity(source, tmp_path, monkeypatch):
    import train_car_engine_model as script

    roots, frame, config = source
    for split in ("train", "val", "test"):
        frame.to_csv(roots["raw"] / f"{split}_metadata.csv", index=False)
    recipe_dir = tmp_path / "backend/training/recipes"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "car_engine_diagnostics_resnet34d.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(script, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(script, "get_raw_data_dir", lambda name: roots["raw"])
    monkeypatch.setattr(script, "get_dataset_roots", lambda name: dict(roots))
    prepared = stop_after_preparation(monkeypatch)
    with pytest.raises(PreparedSplits):
        script.main()
    for actual, waveform, _ in prepared:
        pd.testing.assert_frame_equal(actual, frame)
        assert torch.allclose(waveform, torch.full((8000,), -0.5))
    for split in ("train", "val", "test"):
        pd.testing.assert_frame_equal(
            pd.read_csv(roots["raw"] / f"{split}_metadata.csv", dtype=str, keep_default_na=False), frame)


@pytest.mark.parametrize("module,function", [
    ("train_v2_and_compare", "train_recipe"),
    ("train_and_ensemble_engines", "train_model"),
])
def test_recipe_entrypoints_keep_custom_source_binding(source, tmp_path, monkeypatch, module, function):
    import importlib

    script = importlib.import_module(module)
    roots, frame, config = source
    recipe_dir = tmp_path / "backend/training/recipes"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "fixture.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(script, "get_project_root", lambda: tmp_path)
    prepared = stop_after_preparation(monkeypatch)
    with pytest.raises(PreparedSplits):
        getattr(script, function)("fixture.yaml", frame, frame, frame, roots=roots)
    assert len(prepared) == 3
    for actual, waveform, _ in prepared:
        pd.testing.assert_frame_equal(actual, frame)
        assert torch.allclose(waveform, torch.full((8000,), -0.5))


@pytest.mark.parametrize("module,function", [
    ("train_v2_and_compare", "evaluate_models"),
    ("train_and_ensemble_engines", "evaluate_ensemble"),
])
@pytest.mark.parametrize("stage,level", [("raw", 0.25), ("processed", -0.5)])
def test_public_inference_reads_explicit_stage(source, monkeypatch, module, function, stage, level):
    import importlib

    script = importlib.import_module(module)
    roots, frame, config = source
    frame = frame.assign(file_stage=stage)
    monkeypatch.setattr(script, "GPUAudioFrontEnd", lambda **kwargs: torch.nn.Identity())

    class AcousticModel(torch.nn.Module):
        def forward(self, waveform):
            assert torch.allclose(waveform, torch.full((1, 8000), level))
            return torch.ones((len(waveform), 1))

    result = getattr(script, function)([AcousticModel()], [1.0], frame, config.audio,
                                      torch.device("cpu"), roots=roots)
    assert result[:2] == (1.0, 1.0)
    assert frame.loc[0, "id"] == "001"


@pytest.mark.parametrize("module", [
    "train_efficientnet_hpss_additive", "train_panns_transfer", "train_panns_hpss_additive",
    "train_multitask_hpss", "train_multitask_hpss_wideband", "train_multitask_hpss_rms_balanced",
    "train_multitask_hpss_balanced_additive", "train_multitask_multires_hpss",
    "train_multitask_hpss_asl", "train_multitask_hpss_additive",
])
@pytest.mark.parametrize("stage,level", [("raw", 0.25), ("processed", -0.5)])
def test_hpss_entrypoints_prepare_canonical_splits(source, tmp_path, monkeypatch, module, stage, level):
    import hashlib
    import importlib

    roots, frame, config = source
    frame = frame.assign(file_stage=stage)
    # Match hardcoded 32 kHz / 2 s recipes so stage evidence excludes resampling/padding.
    for name, root in roots.items():
        sf.write(root / "001.wav", np.full(64000, 0.25 if name == "raw" else -0.5), 32000)
    config.audio.target_sr = 32000
    config.audio.duration_seconds = 2.0
    for split in ("train", "val", "test"):
        frame.to_csv(roots["raw"] / f"{split}_metadata.csv", index=False)
    recipe_dir = tmp_path / "backend/training/recipes"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "car_engine_diagnostics_resnet34d_multitask_hpss.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    # All relative output/checkpoint locations, including legacy script constants, are temporary.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    script = importlib.import_module(module)
    monkeypatch.setattr(script, "get_raw_data_dir", lambda name: roots["raw"])
    monkeypatch.setattr(script, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(script, "get_dataset_roots", lambda name: dict(roots))
    monkeypatch.setattr(script, "FROZEN_ENGINE_TEST_SHA256",
                        hashlib.sha256((roots["raw"] / "test_metadata.csv").read_bytes()).hexdigest())
    frontend_name = "MultiResolutionHPSSFrontEnd" if module == "train_multitask_multires_hpss" else "HPSSAudioFrontEnd"
    monkeypatch.setattr(script, frontend_name, lambda **kwargs: torch.nn.Identity())
    prepared = []

    def loader(dataset, **kwargs):
        waveform, _ = dataset[0]
        pd.testing.assert_frame_equal(dataset.df, frame)
        # Evaluation is deterministic; train retains its original stochastic augmentation.
        if not dataset.is_train:
            assert torch.allclose(waveform, torch.full(waveform.shape, level))
        prepared.append(dataset)
        if len(prepared) == 3:
            raise PreparedSplits
        return []

    monkeypatch.setattr(script, "DataLoader", loader)
    with pytest.raises(PreparedSplits):
        script.main()
    assert len(prepared) == 3
