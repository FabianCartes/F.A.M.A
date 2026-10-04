"""Training configuration and execution contracts through public service seams."""
import re
from datetime import datetime, timezone

import librosa
import numpy as np
import pandas as pd
import pytest
import timm
import torch
import torchaudio

from app.models.training import Modelo
from app.services import training
from tests.test_training_flow import training_env, partitions, register


@pytest.fixture
def service_env(training_env):
    service, sessions, root, thread = training_env
    register(sessions, "AvesChilenas")
    raw = partitions(root, "AvesChilenas")
    # Two classes make loss configuration observable, unlike a one-class fixture.
    for split in ("train", "val"):
        csv = raw / f"{split}.csv"
        frame = pd.read_csv(csv)
        audio = raw / "other" / f"{split}.wav"
        audio.parent.mkdir(exist_ok=True)
        audio.write_bytes(b"synthetic audio fixture")
        other = {"clase": "Other", "nombre_archivo": audio.name,
                 "file_path": f"other/{split}.wav", "recordist": split}
        pd.concat([frame, pd.DataFrame([other])]).to_csv(csv, index=False)
    return service, sessions, root, thread


@pytest.fixture
def training_service(service_env):
    return service_env[0]


@pytest.fixture
def execution(service_env, monkeypatch):
    service, sessions, root, thread = service_env
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    class ConstantClassifier(torch.nn.Module):
        """Tiny external-model substitute with a deterministic validation plateau."""
        def __init__(self, num_classes):
            super().__init__()
            self.bias = torch.nn.Parameter(torch.zeros(1))
            self.num_classes = num_classes

        def forward(self, inputs):
            return (self.bias * 0).expand(inputs.shape[0], self.num_classes)

    monkeypatch.setattr(timm, "create_model", lambda *a, num_classes, **k: ConstantClassifier(num_classes))
    # Replace only external ML input/scheduling boundaries, not our worker or model builder.
    monkeypatch.setattr(training, "DataLoader", lambda *a, **k: [(torch.ones(1, 4096), torch.zeros(1, dtype=torch.long))])

    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    thread.side_effect = InlineThread
    return service, sessions, root


def run(service, **kwargs):
    options = {"dataset_name": "AvesChilenas", "architecture": "ConvNeXt-Nano",
               "epochs": 1, "early_stopping": False}
    options.update(kwargs)
    assert service.start_training(**options)["status"] == "started"
    progress = service.get_progress()
    assert progress["status"] == "completed", progress["error_message"]
    return progress


def history(service, sessions):
    with sessions() as db:
        return service.get_history(db)


def payloads(service, sessions):
    return {entry["architecture"]: torch.load(service.checkpoints_dir / entry["filename"], weights_only=True)
            for entry in history(service, sessions)}


def test_start_training_dynamic_duo_models_initialization(training_service):
    """A deferred duo exposes its initial execution plan without starting ML."""
    result = training_service.start_training("AvesChilenas", models=[
        {"architecture": "ConvNeXt-Nano", "weight": 0.6},
        {"architecture": "EfficientNet-B0", "weight": 0.4},
    ])
    assert result["status"] == "started"
    progress = training_service.get_progress()
    assert progress["status"] == "training"
    assert progress["total_models"] == 2
    assert progress["current_model_index"] == 1
    assert progress["current_architecture"] == "ConvNeXt-Nano"
    assert [m["weight"] for m in progress["models_config"]] == [0.6, 0.4]


def test_start_training_dynamic_trio_custom_models(training_service):
    """A custom trio preserves model order and every ensemble weight."""
    result = training_service.start_training("AvesChilenas", models=[
        {"architecture": "PANNs-CNN14", "weight": 0.5},
        {"architecture": "ResNet-34d", "weight": 0.3},
        {"architecture": "AudioCNN", "weight": 0.2},
    ])
    assert result["status"] == "started"
    progress = training_service.get_progress()
    assert progress["total_models"] == 3
    assert progress["current_architecture"] == "PANNs-CNN14"
    assert [m["architecture"] for m in progress["models_config"]] == ["PANNs-CNN14", "ResNet-34d", "AudioCNN"]
    assert [m["weight"] for m in progress["models_config"]] == [0.5, 0.3, 0.2]


def test_start_training_worker_executes_dynamic_models_sequentially(execution):
    """A duo runs the 12/10 epoch presets sequentially and saves its weights."""
    service, sessions, _ = execution
    progress = run(service, models=[
        {"architecture": "ConvNeXt-Nano", "weight": 0.7},
        {"architecture": "EfficientNet-B0", "weight": 0.3},
    ])
    assert progress["total_models"] == 2
    assert progress["current_model_index"] == 2
    metrics = progress["metrics_history"]
    assert len(metrics) == 22
    assert [(m["architecture"], m["model_index"], m["epoca"]) for m in metrics[:12]] == [
        ("ConvNeXt-Nano", 1, epoch) for epoch in range(1, 13)]
    assert [(m["architecture"], m["model_index"], m["epoca"]) for m in metrics[12:]] == [
        ("EfficientNet-B0", 2, epoch) for epoch in range(1, 11)]
    saved = payloads(service, sessions)
    assert saved["ConvNeXt-Nano"]["ensemble_weight"] == 0.7
    assert saved["EfficientNet-B0"]["ensemble_weight"] == 0.3
    assert {entry["architecture"]: len(entry["metrics"]) for entry in history(service, sessions)} == {
        "ConvNeXt-Nano": 12, "EfficientNet-B0": 10}


def test_start_training_worker_with_custom_audio_physics(execution, monkeypatch):
    """Custom physics reaches real dataset decoding and the external mel transform."""
    service, sessions, root = execution
    decoded = []
    transforms = []
    mel_transform = torchaudio.transforms.MelSpectrogram
    def decode(path, sr, **kwargs):
        decoded.append((str(path), sr))
        return np.zeros(16, dtype=np.float32), sr
    def observe_mel(**kwargs):
        transforms.append(kwargs)
        return mel_transform(**kwargs)
    def synthetic_loader(dataset, **kwargs):
        waveform, label = dataset[0]
        assert waveform.shape == (32000,)  # 16000 Hz * 2 seconds.
        return [(waveform.unsqueeze(0), label.unsqueeze(0))]
    monkeypatch.setattr(librosa, "load", decode)
    monkeypatch.setattr("random.random", lambda: 1.0)
    monkeypatch.setattr(torchaudio.transforms, "MelSpectrogram", observe_mel)
    monkeypatch.setattr(training, "DataLoader", synthetic_loader)
    physics = {"target_sr": 16000, "duration_seconds": 2.0, "f_min": 50.0, "f_max": 4000.0,
               "n_mels": 128, "n_fft": 1024, "hop_length": 256}
    run(service, architecture="EfficientNet-B0", audio_config=physics)
    assert decoded == [(str(root / "raw/AvesChilenas/fixture/train.wav"), 16000),
                       (str(root / "raw/AvesChilenas/fixture/val.wav"), 16000)]
    assert transforms
    for transform in transforms:
        assert transform["sample_rate"] == 16000
        assert transform["f_min"] == 50.0
        assert transform["f_max"] == 4000.0
        assert transform["n_mels"] == 128
        assert transform["n_fft"] == 1024
        assert transform["hop_length"] == 256
    assert payloads(service, sessions)["EfficientNet-B0"]["audio_config"] == physics


def test_start_training_worker_with_regularization_loss_config(execution):
    """Equal two-class logits distinguish cross-entropy from focal gamma 3.5."""
    service, sessions, _ = execution
    ce = run(service, regularization_config={"loss_type": "cross_entropy"})
    assert ce["train_loss"] == 0.6931
    assert ce["val_loss"] == 0.6931
    focal = run(service, regularization_config={"loss_type": "focal", "focal_gamma": 3.5})
    assert focal["train_loss"] == 0.0613  # (1 - 0.5)^3.5 * ln(2), rounded to four decimals.
    assert focal["val_loss"] == 0.0613
    assert len(history(service, sessions)) == 2


def test_checkpoint_incremental_nomenclature_versioning(execution):
    """Physical UUID names are unique; history retains display-version semantics."""
    service, sessions, _ = execution
    run(service, learning_rate=0.0005)
    entry, = history(service, sessions)
    assert re.fullmatch(r"fama_[0-9a-f]{32}_best\.pt", entry["filename"])
    assert entry["version"] == 1
    assert entry["hyperparameters"]["learning_rate"] == 0.0005
    original = (service.checkpoints_dir / entry["filename"]).read_bytes()
    run(service, learning_rate=0.0005)
    entries = history(service, sessions)
    assert len(entries) == 2
    assert {item["version"] for item in entries} == {1, 2}
    assert len({item["filename"] for item in entries}) == 2
    assert (service.checkpoints_dir / entry["filename"]).read_bytes() == original


def seed_model(db, **kwargs):
    values = {"epocas": 10, "tasa_aprendizaje": 0.001, "tamano_lote": 16,
              "tamano_bytes": 48822960, "activo": False, "estado": "entrenado"}
    values.update(kwargs)
    db.add(Modelo(**values))


def test_get_history_enriches_model_technical_sheet(service_env):
    """Historical models retain their complete technical sheets and first versions."""
    service, sessions, _, _ = service_env
    with sessions() as db:
        seed_model(db, id_modelo=1, clase_objetivo="13 Clases (engine_diagnostics)", arquitectura="EfficientNet-B0",
                   precision=68.12, perdida=1.0297, fecha_entrenamiento=datetime(2026, 9, 29, 0, 52, 14, tzinfo=timezone.utc),
                   ruta_binario_gcp="models/fama_efficientnet_b0_1790642923_efficientnet_b0_best.pt")
        seed_model(db, id_modelo=6, clase_objetivo="15 Clases (AvesChilenas)", arquitectura="EfficientNet-B0",
                   precision=77.78, perdida=0.35, tamano_lote=32, activo=True,
                   fecha_entrenamiento=datetime(2026, 9, 29, 0, 6, 31, tzinfo=timezone.utc),
                   ruta_binario_gcp="models/fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt")
        db.commit()
    entries = history(service, sessions)
    assert len(entries) == 2
    item_1 = next(h for h in entries if h["id"] == 1)
    assert item_1["version"] == 1
    assert "v1" in item_1["name"]
    assert "Motores" in item_1["name"]
    assert item_1["filename"] == "fama_efficientnet_b0_1790642923_efficientnet_b0_best.pt"
    assert item_1["hyperparameters"]["learning_rate"] == 0.001
    assert item_1["hyperparameters"]["batch_size"] == 16
    assert item_1["hyperparameters"]["optimizer"] == "AdamW"
    assert item_1["hyperparameters"]["loss_type"] in ["Focal Loss", "CrossEntropy"]
    assert item_1["audio_specs"]["target_sr"] == 32000
    assert item_1["audio_specs"]["duration_seconds"] == 1.5
    assert item_1["audio_specs"]["fmax"] == 16000
    assert item_1["classes_count"] == 13
    assert item_1["file_size_bytes"] == 48822960
    item_6 = next(h for h in entries if h["id"] == 6)
    assert item_6["version"] == 1
    assert "v1" in item_6["name"]
    assert "Aves Chilenas" in item_6["name"]
    assert item_6["filename"] == "fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt"
    assert item_6["hyperparameters"]["learning_rate"] == 0.001
    assert item_6["hyperparameters"]["batch_size"] == 32
    assert item_6["audio_specs"]["target_sr"] == 22050
    assert item_6["audio_specs"]["duration_seconds"] == 5.0
    assert item_6["audio_specs"]["fmax"] == 11025
    assert item_6["classes_count"] == 15
    assert item_6["file_size_bytes"] == 48822960


def test_get_history_semantic_versioning_per_dataset_and_architecture(service_env):
    """Display versions remain independent for each dataset/architecture pair."""
    service, sessions, _, _ = service_env
    rows = [(1, "engine_diagnostics", "EfficientNet-B0", 0, 52, "motores_eff_1.pt"),
            (6, "AvesChilenas", "EfficientNet-B0", 0, 6, "aves_eff_1.pt"),
            (7, "AvesChilenas", "EfficientNet-B0", 1, 0, "aves_eff_2.pt"),
            (8, "AvesChilenas", "ResNet-34d", 1, 15, "aves_res_1.pt"),
            (9, "engine_diagnostics", "ResNet-34d", 1, 30, "motores_res_1.pt")]
    with sessions() as db:
        for identifier, dataset, arch, hour, minute, filename in rows:
            classes = 13 if dataset == "engine_diagnostics" else 15
            seed_model(db, id_modelo=identifier, clase_objetivo=f"{classes} Clases ({dataset})", arquitectura=arch,
                       fecha_entrenamiento=datetime(2026, 9, 29, hour, minute, tzinfo=timezone.utc),
                       ruta_binario_gcp=f"models/{filename}")
        db.commit()
    by_id = {h["id"]: h for h in history(service, sessions)}
    assert by_id[1]["name"] == "Motores · EfficientNet-B0 (v1)"
    assert by_id[1]["version"] == 1
    assert by_id[6]["name"] == "Aves Chilenas · EfficientNet-B0 (v1)"
    assert by_id[6]["version"] == 1
    assert by_id[7]["name"] == "Aves Chilenas · EfficientNet-B0 (v2)"
    assert by_id[7]["version"] == 2
    assert by_id[8]["name"] == "Aves Chilenas · ResNet-34d (v1)"
    assert by_id[8]["version"] == 1
    assert by_id[9]["name"] == "Motores · ResNet-34d (v1)"
    assert by_id[9]["version"] == 1


def test_start_training_worker_receives_weight_decay(execution, monkeypatch):
    """The requested decay reaches the external optimizer and its parameter groups."""
    service, _, _ = execution
    optimizer = torch.optim.AdamW
    observed = []
    def observe_optimizer(parameters, **kwargs):
        instance = optimizer(parameters, **kwargs)
        observed.extend(group["weight_decay"] for group in instance.param_groups)
        return instance
    monkeypatch.setattr(torch.optim, "AdamW", observe_optimizer)
    run(service, epochs=5, learning_rate=0.0005, weight_decay=0.05)
    assert observed == [0.05]


def test_start_training_dynamic_ensemble_preserves_custom_epochs(training_service):
    """Public progress preserves each model's custom epoch count."""
    assert training_service.start_training("AvesChilenas", models=[
        {"architecture": "ResNet-34d", "weight": 0.6, "epochs": 35},
        {"architecture": "EfficientNet-B0", "weight": 0.4, "epochs": 10},
    ])["status"] == "started"
    models = training_service.get_progress()["models_config"]
    assert models[0]["epochs"] == 35
    assert models[1]["epochs"] == 10
    assert [model["weight"] for model in models] == [0.6, 0.4]


def test_start_training_dynamic_ensemble_preserves_custom_hyperparameters(execution):
    """Per-model epochs, rates, batches and weights survive execution and persistence."""
    service, sessions, _ = execution
    progress = run(service, models=[
        {"architecture": "ResNet-34d", "weight": 0.6, "epochs": 35, "learning_rate": 0.0007, "batch_size": 32},
        {"architecture": "EfficientNet-B0", "weight": 0.4, "epochs": 10, "learning_rate": 0.001, "batch_size": 16},
    ])
    models = progress["models_config"]
    assert models[0]["learning_rate"] == 0.0007
    assert models[0]["batch_size"] == 32
    assert models[1]["learning_rate"] == 0.001
    assert models[1]["batch_size"] == 16
    entries = {entry["architecture"]: entry for entry in history(service, sessions)}
    assert entries["ResNet-34d"]["epochs"] == 35
    assert len(entries["ResNet-34d"]["metrics"]) == 35
    assert entries["ResNet-34d"]["hyperparameters"]["learning_rate"] == 0.0007
    assert entries["ResNet-34d"]["hyperparameters"]["batch_size"] == 32
    assert entries["EfficientNet-B0"]["epochs"] == 10
    assert len(entries["EfficientNet-B0"]["metrics"]) == 10
    assert entries["EfficientNet-B0"]["hyperparameters"]["learning_rate"] == 0.001
    assert entries["EfficientNet-B0"]["hyperparameters"]["batch_size"] == 16
    saved = payloads(service, sessions)
    assert saved["ResNet-34d"]["ensemble_weight"] == 0.6
    assert saved["EfficientNet-B0"]["ensemble_weight"] == 0.4


def test_start_training_propagates_early_stopping_flag(execution):
    """The default stops on a plateau; explicit False completes the full schedule."""
    service, _, _ = execution
    # Do not pass early_stopping for the first job: exercise the public default.
    assert service.start_training("AvesChilenas", architecture="ConvNeXt-Nano", epochs=10)["status"] == "started"
    assert service.get_progress()["status"] == "completed"
    assert service.get_progress()["epoch"] == 6
    assert run(service, epochs=10, early_stopping=False)["epoch"] == 10


def test_training_worker_early_stopping_halts_on_patience_exhaustion(execution):
    """One improvement followed by five flat validation epochs stops at epoch six."""
    service, sessions, _ = execution
    progress = run(service, epochs=10, early_stopping=True)
    assert progress["epoch"] == 6
    assert len(progress["metrics_history"]) == 6
    assert {metric["val_loss"] for metric in progress["metrics_history"]} == {0.1733}
    assert any("Early Stopping activado en época 6" in log["message"] and log["level"] == "WARN"
               for log in progress["logs"])
    entry, = history(service, sessions)
    assert len(entry["metrics"]) == 6


def test_training_worker_disabled_early_stopping_runs_all_epochs(execution):
    """Disabling early stopping retains all ten flat validation epochs."""
    service, sessions, _ = execution
    progress = run(service, epochs=10, early_stopping=False)
    assert progress["epoch"] == 10
    assert len(progress["metrics_history"]) == 10
    assert {metric["val_loss"] for metric in progress["metrics_history"]} == {0.1733}
    assert not any("Early Stopping activado" in log["message"] for log in progress["logs"])
    entry, = history(service, sessions)
    assert len(entry["metrics"]) == 10
