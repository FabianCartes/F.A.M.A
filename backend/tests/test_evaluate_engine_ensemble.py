"""Explicit local evaluation of the served engine ensemble on prepared snapshots."""
import csv
import hashlib
import json
from pathlib import Path
import wave

import numpy as np
import pytest
import torch
from torch import nn

from training.pipelines.multitask_mapping import CLASS_NAMES_13
from training.prepare_data import _names
from app.services.predictors.engine_ensemble_predictor import DEFAULT_ENGINE_ENSEMBLE_WEIGHTS
from scripts.evaluate_engine_ensemble import evaluate_engine_ensemble


def wav(path):
    sr = 32000
    samples = (0.25 * np.sin(2 * np.pi * 180 * np.arange(sr * 2) / sr) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sr)
        output.writeframes(samples.tobytes())


def prepared_snapshot(tmp_path, *, overlap=False, label=None):
    roots = {"raw": tmp_path / "raw", "processed": tmp_path / "processed"}
    for root in roots.values():
        root.mkdir()
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    names = _names("engine_diagnostics")
    hashes = {}
    for split, filename in zip(("train", "val", "test"), names):
        name = f"{split}.wav"
        wav(roots["raw"] / name)
        recordist = "shared" if overlap else f"group-{split}"
        rows = [{"file_path": name, "file_stage": "raw", "clase": label or CLASS_NAMES_13[0],
                 "recordist": recordist, "source_id": split}]
        with (prepared / filename).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        hashes[filename] = hashlib.sha256((prepared / filename).read_bytes()).hexdigest()
    (prepared / ".complete").write_text(json.dumps({
        "schema": 1, "dataset": "engine_diagnostics", "sha256": hashes,
    }), encoding="utf-8")
    return prepared, roots


class TinyCheckpointModel(nn.Module):
    def __init__(self, num_classes, winner):
        super().__init__()
        self.logits = nn.Parameter(torch.zeros(num_classes))
        self.logits.data[winner] = 8.0

    def load_state_dict(self, state_dict, strict=True):
        assert strict
        self.logits.data.copy_(state_dict["logits"])

    def state_dict(self):
        return {"logits": self.logits.detach().clone()}

    def to(self, device):
        return self

    def eval(self):
        return self

    def forward(self, inputs):
        return self.logits.unsqueeze(0).expand(inputs.shape[0], -1)


def component_paths(tmp_path):
    winners = {"resnet": 0, "efficientnet": 1, "panns": 2}
    paths = {name: tmp_path / f"{name}.pt" for name in winners}
    for name, path in paths.items():
        torch.save({"logits": torch.eye(13)[winners[name]] * 8.0}, path)
    return paths


def install_small_architectures(monkeypatch):
    monkeypatch.setattr(
        "training.models.multitask_bioacoustic.MultiTaskBioacousticModel",
        lambda **kwargs: TinyCheckpointModel(kwargs["num_classes"], 0),
    )
    monkeypatch.setattr(
        "training.models.panns_cnn14.PannsCNN14",
        lambda **kwargs: TinyCheckpointModel(kwargs["num_classes"], 0),
    )


def test_operation_reports_combined_predictions_not_average_member_metrics(tmp_path, monkeypatch):
    prepared, roots = prepared_snapshot(tmp_path)
    checkpoints = component_paths(tmp_path)
    install_small_architectures(monkeypatch)
    output = tmp_path / "reports.json"
    result = evaluate_engine_ensemble(
        prepared_dir=prepared, dataset="engine_diagnostics", roots=roots,
        checkpoint_paths=checkpoints, output=output,
    )
    assert result["reports"]["val"]["report"]["metrics"]["accuracy"] == 1.0
    assert result["reports"]["test"]["report"]["metrics"]["accuracy"] == 1.0
    assert result["reports"]["val"]["provenance"]["split"] == "val"
    assert result["reports"]["test"]["provenance"]["split"] == "test"
    assert result["reports"]["val"]["provenance"]["manifest_sha256"] != result["reports"]["test"]["provenance"]["manifest_sha256"]
    assert "id_modelo" not in result["reports"]["val"]["provenance"]
    assert result["composite_checkpoint_sha256"] == result["reports"]["val"]["provenance"]["checkpoint_sha256"]
    assert [part["name"] for part in result["component_checkpoints"]] == list(DEFAULT_ENGINE_ENSEMBLE_WEIGHTS)
    assert json.loads(output.read_text()) == result
    with pytest.raises(FileExistsError):
        evaluate_engine_ensemble(prepared_dir=prepared, dataset="engine_diagnostics", roots=roots,
                                 checkpoint_paths=checkpoints, output=output)


def test_operation_rejects_missing_component_before_constructing_predictor(tmp_path):
    prepared, roots = prepared_snapshot(tmp_path)
    output = tmp_path / "reports.json"
    class ForbiddenFactory:
        def __init__(self, **kwargs):
            pytest.fail("Missing component must fail before predictor construction")
    with pytest.raises(ValueError, match="All three"):
        evaluate_engine_ensemble(prepared_dir=prepared, dataset="engine_diagnostics", roots=roots,
                                 checkpoint_paths={"resnet": tmp_path / "r.pt"}, output=output,
                                 predictor_factory=ForbiddenFactory)
    assert not output.exists()


def test_operation_preflight_rejects_split_group_overlap_before_model_load(tmp_path):
    prepared, roots = prepared_snapshot(tmp_path, overlap=True)
    class ForbiddenFactory:
        def __init__(self, **kwargs):
            pytest.fail("Invalid prepared groups must fail before model loading")
    with pytest.raises(ValueError, match="Group leakage"):
        evaluate_engine_ensemble(prepared_dir=prepared, dataset="engine_diagnostics", roots=roots,
                                 checkpoint_paths={name: tmp_path / f"{name}.pt" for name in DEFAULT_ENGINE_ENSEMBLE_WEIGHTS},
                                 output=tmp_path / "reports.json", predictor_factory=ForbiddenFactory)


def test_operation_component_mutation_during_inference_never_writes_reports(tmp_path, monkeypatch):
    prepared, roots = prepared_snapshot(tmp_path)
    checkpoints = component_paths(tmp_path)
    install_small_architectures(monkeypatch)
    original_forward = TinyCheckpointModel.forward
    mutated = False
    def mutate_once(self, inputs):
        nonlocal mutated
        if not mutated:
            mutated = True
            checkpoints["panns"].write_bytes(b"changed during inference")
        return original_forward(self, inputs)
    monkeypatch.setattr(TinyCheckpointModel, "forward", mutate_once)
    output = tmp_path / "reports.json"
    with pytest.raises(ValueError, match="changed during evaluation"):
        evaluate_engine_ensemble(prepared_dir=prepared, dataset="engine_diagnostics", roots=roots,
                                 checkpoint_paths=checkpoints, output=output)
    assert not output.exists()


def test_operation_audio_mutation_during_prediction_never_writes_reports(tmp_path, monkeypatch):
    prepared, roots = prepared_snapshot(tmp_path)
    checkpoints = component_paths(tmp_path)
    install_small_architectures(monkeypatch)
    audio_path = roots["raw"] / "val.wav"
    original_forward = TinyCheckpointModel.forward
    mutated = False
    def mutate_audio_once(self, inputs):
        nonlocal mutated
        if not mutated:
            mutated = True
            audio_path.write_bytes(b"changed during prediction")
        return original_forward(self, inputs)
    monkeypatch.setattr(TinyCheckpointModel, "forward", mutate_audio_once)
    output = tmp_path / "reports.json"
    with pytest.raises(ValueError, match="Audio changed during inference"):
        evaluate_engine_ensemble(prepared_dir=prepared, dataset="engine_diagnostics", roots=roots,
                                 checkpoint_paths=checkpoints, output=output)
    assert not output.exists()


def test_operation_preflight_rejects_unknown_class_before_model_load(tmp_path):
    prepared, roots = prepared_snapshot(tmp_path, label="not-a-served-class")
    class ForbiddenFactory:
        def __init__(self, **kwargs):
            pytest.fail("Unknown class must fail before model loading")
    with pytest.raises(ValueError, match="served ensemble class order"):
        evaluate_engine_ensemble(prepared_dir=prepared, dataset="engine_diagnostics", roots=roots,
                                 checkpoint_paths={name: tmp_path / f"{name}.pt" for name in DEFAULT_ENGINE_ENSEMBLE_WEIGHTS},
                                 output=tmp_path / "reports.json", predictor_factory=ForbiddenFactory)
