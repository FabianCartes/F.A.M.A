"""Public training entrypoints prepare canonical rows before expensive ML work."""
from types import SimpleNamespace
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
        "dataset_name": "engine_diagnostics",
    })
    return roots, frame, config


def make_disjoint_splits(roots, frame, stage="processed"):
    """Build small canonical splits with independent recording and group identities."""
    frames = []
    for split in ("train", "val", "test"):
        path = f"{split}-001.wav"
        rows = frame.assign(
            file_path=path, file_stage=stage, id=f"{split}-001",
            source_group=f"source-{split}", recordist=f"recordist-{split}",
        )
        for physical_stage, root in roots.items():
            value = 0.25 if physical_stage == "raw" else -0.5
            sf.write(root / path, np.full(8000, value, dtype=np.float32), 8000)
        frames.append(rows)
    return tuple(frames)


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
    frames = make_disjoint_splits(roots, frame, stage=stage)
    prepared = stop_after_preparation(monkeypatch)
    trainer = GenericModelTrainer(config, project_root=tmp_path)
    with pytest.raises(PreparedSplits):
        trainer.train_and_export(*frames, tmp_path / "checkpoints", roots=roots)
    assert len(prepared) == 3
    for actual, waveform, label in prepared:
        assert any(actual.equals(expected) for expected in frames)
        assert torch.allclose(waveform, torch.full((8000,), level))
        assert label.item() == 0


@pytest.mark.parametrize("split", [0, 1, 2])
@pytest.mark.parametrize("invalid", ["missing_stage", "missing_path", "absolute", "unknown_stage", "missing_file", "missing_root", "alias"])
def test_trainer_rejects_invalid_split_before_ml(source, tmp_path, monkeypatch, split, invalid):
    roots, frame, config = source
    frames = list(make_disjoint_splits(roots, frame))
    stop_after_preparation(monkeypatch)
    if invalid == "missing_stage":
        frames[split] = frames[split].drop(columns="file_stage")
    elif invalid == "missing_path":
        frames[split] = frames[split].drop(columns="file_path")
    elif invalid == "absolute":
        frames[split].loc[0, "file_path"] = str(roots["processed"] / "val-001.wav")
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
