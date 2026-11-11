"""Real spawn supervision through the public training service boundary."""
import os
import threading
import time
from pathlib import Path
import pytest

from app.services import training
from tests.test_training_flow import training_env, partitions, register


def flood_progress(config, checkpoints, publish, stop_event):
    for epoch in range(1500):
        publish({"status": "training", "epoch": epoch, "logs": [{"message": "x" * 4096}]})
    publish({"status": "completed", "epoch": 1500})
    Path(checkpoints, "child-returned").touch()


def test_service_drains_spawn_without_http_polling(training_env, monkeypatch):
    from app.services.training_process import TrainingProcess

    service, sessions, root, _ = training_env
    register(sessions, "AvesChilenas")
    partitions(root, "AvesChilenas")
    monkeypatch.setattr(training, "threading", threading)
    children = []

    def factory(target, *, args, seed):
        child = TrainingProcess(flood_progress, args=args, seed=seed)
        children.append(child)
        return child

    service._process_factory = factory
    service.start_training("AvesChilenas", epochs=1)
    # No progress request until supervision has observed and reaped the child.
    deadline = time.monotonic() + 30
    while service.status == "training" and time.monotonic() < deadline:
        time.sleep(0.02)
    progress = service.get_progress()
    assert progress["status"] == "completed", progress
    assert progress["epoch"] == 1500
    assert (service.checkpoints_dir / "child-returned").is_file()
    assert service.wait_for_completion(timeout=10)


def misleading_completion(config, checkpoints, publish, stop_event):
    publish({"status": "completed"})
    # Fail during interpreter shutdown, after the wrapper emitted "finished".
    def fail_late():
        time.sleep(0.5)
        os._exit(7)
    threading.Thread(target=fail_late).start()


def silent_exit(config, checkpoints, publish, stop_event):
    os._exit(0)


def stopped_worker(config, checkpoints, publish, stop_event):
    publish({"status": "training"})
    assert stop_event.wait(15)
    publish({"status": "stopped"})


@pytest.mark.parametrize("target, expected", [
    (misleading_completion, "failed"), (silent_exit, "failed"), (stopped_worker, "stopped"),
])
def test_service_reconciles_exit_and_cooperative_stop(training_env, monkeypatch, target, expected):
    from app.services.training_process import TrainingProcess

    service, sessions, root, _ = training_env
    register(sessions, "AvesChilenas")
    partitions(root, "AvesChilenas")
    monkeypatch.setattr(training, "threading", threading)
    service._process_factory = lambda worker, **kwargs: TrainingProcess(target, **kwargs)
    service.start_training("AvesChilenas", epochs=1)
    if target is stopped_worker:
        assert service.stop_training()["status"] == "stopping"
    assert service.wait_for_completion(timeout=30)
    progress = service.get_progress()
    assert progress["status"] == expected
    if expected == "failed":
        assert progress["error_message"]


def test_supervisor_start_failure_does_not_leave_an_unowned_child(training_env, monkeypatch):
    from multiprocessing import active_children
    from types import SimpleNamespace
    from app.services.training_process import TrainingProcess

    service, sessions, root, _ = training_env
    register(sessions, "AvesChilenas")
    partitions(root, "AvesChilenas")
    service._process_factory = lambda worker, **kwargs: TrainingProcess(stopped_worker, **kwargs)
    def fail_thread(**kwargs):
        raise RuntimeError("synthetic supervisor start failure")
    monkeypatch.setattr(training, "threading", SimpleNamespace(Event=threading.Event, Thread=fail_thread))
    try:
        with pytest.raises(RuntimeError, match="synthetic supervisor"):
            service.start_training("AvesChilenas")
        assert service.get_progress()["status"] == "failed"
        assert service.wait_for_completion(timeout=1)
        assert not any(child.name == "FamaTrainingProcess" for child in active_children())
    finally:
        for child in active_children():
            if child.name == "FamaTrainingProcess":
                child.terminate()
                child.join(5)


def rng_snapshot(_config, _checkpoints, publish, _stop_event):
    import random
    import numpy as np
    import torch
    publish({"values": [random.random(), float(np.random.random()), torch.rand(1).item()]})


def test_spawn_replays_seed_without_mutating_parent_rngs():
    import random
    import numpy as np
    import torch
    from app.services.training_process import TrainingProcess

    before = (random.getstate(), np.random.get_state(), torch.get_rng_state().clone())
    values = []
    for _ in range(2):
        child = TrainingProcess(rng_snapshot, args=(None, None), seed=1234)
        child.start()
        try:
            values.append(child.receive(timeout=20)["snapshot"]["values"])
            assert child.receive(timeout=10)["type"] == "finished"
            child.join(10)
            assert child.exitcode == 0
        finally:
            child.close()
    assert values[0] == values[1]
    assert values[0] == pytest.approx([0.9664535356921388, 0.1915194503788923, 0.028979241847991943])
    assert random.getstate() == before[0]
    current_numpy = np.random.get_state()
    assert current_numpy[0] == before[1][0]
    assert np.array_equal(current_numpy[1], before[1][1])
    assert current_numpy[2:] == before[1][2:]
    assert torch.equal(torch.get_rng_state(), before[2])


def synthetic_pipeline(config, checkpoints, publish, stop_event):
    """Replace the external model factory only; run real training, DB and reports."""
    import socket
    from unittest.mock import patch
    import torch
    from app.services.training_process import run_training_worker

    torch.set_num_threads(1)
    def forbid_network(*args, **kwargs):
        raise AssertionError("Network access forbidden in synthetic spawn test")

    class TinyClassifier(torch.nn.Module):
        def __init__(self, num_classes):
            super().__init__()
            self.pool = torch.nn.AdaptiveAvgPool2d(1)
            self.linear = torch.nn.Linear(1, num_classes)
        def forward(self, inputs):
            if not self.training and config.get("cancel_validation") is True:
                stop_event.set()
            return self.linear(self.pool(inputs).flatten(1))

    if config.get("cancel_validation") == "registration":
        from sqlalchemy import event
        from app.database import SessionLocal
        event.listen(SessionLocal, "after_commit", lambda db: stop_event.set(), once=True)
    with patch.object(socket.socket, "connect", forbid_network), \
         patch("timm.create_model", side_effect=lambda *a, num_classes, **kw: TinyClassifier(num_classes)):
        run_training_worker(config, checkpoints, publish, stop_event)


@pytest.mark.parametrize("cancel_validation", [True, False, "registration"])
def test_spawn_pipeline_persists_checkpoint_and_reports_or_stops_before_publication(
    training_env, monkeypatch, cancel_validation,
):
    import hashlib
    import torch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models.training import Modelo, ModelEvaluation
    from app.services.training_process import TrainingProcess

    service, _, root, _ = training_env
    url = f"sqlite:///{root / 'spawn.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(training, "SessionLocal", sessions)
    dataset_id = register(sessions, "engine_diagnostics")
    partitions(root, "engine_diagnostics", classes=("Fixture", "Other"))
    def factory(target, *, args, seed):
        config, checkpoints = args
        config = dict(config, cancel_validation=cancel_validation)
        return TrainingProcess(synthetic_pipeline, args=(config, checkpoints), seed=seed)
    service._process_factory = factory
    try:
        result = service.start_training(
            "engine_diagnostics", architecture="fixture", epochs=1, batch_size=2, seed=314,
            audio_config={"target_sr": 8000, "duration_seconds": 0.064, "n_mels": 32,
                          "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": None},
            early_stopping=False,
        )
        assert service.wait_for_completion(timeout=40)
        progress = service.get_progress()
        assert progress["status"] == ("stopped" if cancel_validation else "completed"), progress
        with sessions() as db:
            history = service.get_history(db)
            if cancel_validation is True:
                assert history == []
                assert db.query(ModelEvaluation).count() == 0
                assert list(service.checkpoints_dir.iterdir()) == []
                return
            entry, = history
            path = service.checkpoints_dir / entry["filename"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            payload = torch.load(path, weights_only=True)
            assert payload["dataset_id"] == dataset_id
            assert payload["job_id"] == result["job_id"]
            assert payload["seed"] == 314
            assert payload["runtime"]["device"] == "cpu"
            assert payload["reproducibility"]["execution"] == "spawned_process"
            assert payload["reproducibility"]["cuda_bitwise_reproducible"] is False
            assert payload["initialization_mode"] == "pretrained_constructor"
            assert payload["preprocessing_contract"]["parameters"]["f_max"] is None
            reports = db.query(ModelEvaluation).order_by(ModelEvaluation.id_evaluation).all()
            if cancel_validation == "registration":
                assert reports == []
                assert entry["active"] is False
                assert entry["status"] == "standard_eval_pending"
                return
            assert [(r.split, r.status) for r in reports] == [("val", "completed"), ("test", "completed")]
            assert all(r.checkpoint_sha256 == digest for r in reports)
            assert reports[0].manifest_sha256 != reports[1].manifest_sha256
            assert db.query(Modelo).one().hash_binario == digest
    finally:
        engine.dispose()
