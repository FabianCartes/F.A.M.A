"""Best-epoch preservation through public training interfaces, CPU only."""
import pandas as pd
import pytest
import timm
import torch
import json

from app.services import training
from tests.test_training_flow import training_env, partitions, register
from training.schemas.config import TrainingConfig
from training.trainers.standalone_trainer import GenericModelTrainer


class ScheduledClassifier(torch.nn.Module):
    """Tiny external-network adapter with observable weights and integer buffers."""

    def __init__(self):
        super().__init__()
        self.margin = torch.nn.Parameter(torch.tensor(0.0))
        self.register_buffer("revision", torch.tensor(0, dtype=torch.long))

    def forward(self, inputs):
        score = (self.margin + self.revision * 0.1).expand(inputs.shape[0])
        return torch.stack((score, -score), dim=1)


@pytest.fixture
def snapshot_env(training_env, monkeypatch):
    service, sessions, root, thread = training_env
    register(sessions, "engine_diagnostics")
    raw = partitions(root, "engine_diagnostics")
    for split in ("train", "val"):
        audio = raw / "other" / f"{split}.wav"
        audio.parent.mkdir(exist_ok=True)
        audio.write_bytes(b"synthetic audio fixture")
        index = raw / f"{split}_metadata.csv"
        frame = pd.read_csv(index)
        row = {"clase": "Other", "file_path": f"other/{split}.wav",
               "file_stage": "raw", "nombre_archivo": audio.name, "recordist": split}
        pd.concat([frame, pd.DataFrame([row])]).to_csv(index, index=False)

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    models = []
    margins = [1.0, -1.0]

    def model_factory(*args, **kwargs):
        model = ScheduledClassifier()
        models.append(model)
        return model

    monkeypatch.setattr(timm, "create_model", model_factory)
    monkeypatch.setattr(training, "DataLoader", lambda *args, **kwargs: [
        (torch.ones(1, 512), torch.zeros(1, dtype=torch.long))
    ])

    class ScheduledOptimizer(torch.optim.SGD):
        def __init__(self, params, lr, **kwargs):
            super().__init__(params, lr=lr)
            self.epoch = 0

        def step(self, closure=None):
            self.epoch += 1
            with torch.no_grad():
                models[-1].margin.fill_(margins[self.epoch - 1])
                models[-1].revision.fill_(self.epoch)

    monkeypatch.setattr(torch.optim, "AdamW", ScheduledOptimizer)

    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    thread.side_effect = InlineThread
    return service, sessions, root, margins


@pytest.mark.parametrize("margins,expected_accuracy,expected_margin,expected_revision", [
    ([1.0, -1.0], 100.0, 1.0, 1),
    ([-1.0, -2.0], 0.0, -1.0, 1),
    ([-1.0, 1.0, -2.0], 100.0, 1.0, 2),
    ([1.0, 2.0], 100.0, 1.0, 1),
])
def test_web_checkpoint_keeps_best_epoch_after_later_cpu_updates(
    snapshot_env, margins, expected_accuracy, expected_margin, expected_revision,
):
    service, sessions, _, schedule = snapshot_env
    schedule[:] = margins
    service.start_training(
        "engine_diagnostics", architecture="fixture", epochs=len(margins), batch_size=1,
        audio_config={"target_sr": 8000, "duration_seconds": 0.064, "n_mels": 32,
                      "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0},
        regularization_config={"loss_type": "cross_entropy"}, early_stopping=False,
    )

    progress = service.get_progress()
    assert progress["status"] == "completed", progress["error_message"]
    assert progress["epoch"] == len(margins)
    with sessions() as db:
        entry, = service.get_history(db)
    payload = torch.load(service.checkpoints_dir / entry["filename"], weights_only=True)

    # These belong to the external synthetic classifier, not training internals.
    assert payload["best_val_acc"] == expected_accuracy
    assert payload["state_dict"]["backbone.margin"].item() == expected_margin
    assert payload["state_dict"]["backbone.revision"].item() == expected_revision


@pytest.mark.parametrize("margins,expected_f1,expected_margin,expected_revision", [
    ([1.0, -1.0], 1.0, 1.0, 1),
    ([-1.0, -2.0], 0.0, -1.0, 1),
    ([-1.0, 1.0, -2.0], 1.0, 1.0, 2),
    ([1.0, 2.0], 1.0, 1.0, 1),
])
def test_declarative_trainer_evaluates_and_exports_best_cpu_epoch(
    snapshot_env, monkeypatch, margins, expected_f1, expected_margin, expected_revision,
):
    _, _, root, schedule = snapshot_env
    schedule[:] = margins
    raw = root / "raw" / "engine_diagnostics"
    train_df = pd.read_csv(raw / "train_metadata.csv")
    val_df = pd.read_csv(raw / "val_metadata.csv")
    test_df = val_df.copy(deep=True)
    for idx, row in test_df.iterrows():
        path = row["file_path"].replace("val.wav", "test.wav")
        (raw / path).write_bytes(b"synthetic test audio")
        test_df.loc[idx, "file_path"] = path
    monkeypatch.setattr("training.trainers.standalone_trainer.DataLoader", lambda *args, **kwargs: [
        (torch.ones(1, 512), torch.zeros(1, dtype=torch.long))
    ])
    config = TrainingConfig.model_validate({
        "experiment_id": "snapshot", "model_id": "best-cpu-epoch",
        "model_name": "Synthetic snapshot", "description": "No real training",
        "device": "cpu", "epochs": len(margins), "batch_size": 1,
        "architecture": {"type": "fixture", "pretrained": False},
        "audio": {"target_sr": 8000, "duration_seconds": 0.064, "n_mels": 32,
                  "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0},
        "augmentation": {"mixup_prob": 0.0, "spec_augment_prob": 0.0},
        "loss": {"name": "cross_entropy"},
        "dataset": {"metadata_csv": raw / "train_metadata.csv", "raw_dir": raw,
                    "num_workers": 0},
    })

    bundle, metrics = GenericModelTrainer(config, project_root=root).train_and_export(
        train_df, val_df, test_df, root / "bundles", verbose=False, roots={"raw": raw},
    )

    assert metrics["best_val_f1_macro"] == expected_f1
    assert metrics["test_accuracy"] == expected_f1
    assert metrics["test_f1_macro"] == expected_f1
    weights = torch.load(bundle / "weights.pt", weights_only=True)
    assert weights["backbone.margin"].item() == expected_margin
    assert weights["backbone.revision"].item() == expected_revision
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metrics"] == metrics
