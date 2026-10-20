"""Best-epoch preservation through public training interfaces, CPU only."""
import pytest
import timm
import torch

from app.services import training
from tests.test_training_flow import training_env, partitions, register


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
    partitions(root, "engine_diagnostics", classes=("Fixture", "Other"))

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


@pytest.mark.parametrize("margins,expected_accuracy,expected_margin,expected_revision,expected_loss", [
    ([1.0, -1.0], 100.0, 1.0, 1, 0.1051),
    ([-1.0, -2.0], 0.0, -1.0, 1, 1.9530),
    ([-1.0, 1.0, -2.0], 100.0, 1.0, 2, 0.0868),
    ([1.0, 2.0], 100.0, 1.0, 1, 0.1051),
])
def test_web_checkpoint_keeps_best_epoch_after_later_cpu_updates(
    snapshot_env, margins, expected_accuracy, expected_margin, expected_revision, expected_loss,
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
    # Cross-entropy of the selected synthetic logits, independently worked out.
    # An equal accuracy keeps the first checkpoint even if a later loss is lower.
    assert entry["accuracy"] == expected_accuracy
    assert entry["loss"] == expected_loss
    assert payload["checkpoint_epoch"] == expected_revision
    assert payload["checkpoint_val_loss"] == expected_loss
