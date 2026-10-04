"""Persistence through public training seams with tiny, synthetic ML execution."""
import hashlib

import pytest
import torch
import timm
from sqlalchemy import event

from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo
from app.services import training
from tests.test_training_flow import training_env, partitions, register


@pytest.fixture
def persistence_env(training_env, monkeypatch):
    service, sessions, root, thread = training_env
    dataset_id = register(sessions, "engine_diagnostics")
    partitions(root, "engine_diagnostics")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    # External ML library boundaries: no pretrained downloads or real audio input.
    def tiny_model(*args, num_classes, **kwargs):
        model = torch.nn.Sequential(torch.nn.AdaptiveAvgPool2d(1), torch.nn.Flatten(),
                                    torch.nn.Linear(1, num_classes))
        for parameter in model.parameters():
            torch.nn.init.zeros_(parameter)
        return model
    monkeypatch.setattr(timm, "create_model", tiny_model)
    monkeypatch.setattr(training, "DataLoader", lambda *a, **k: [(torch.ones(1, 512), torch.zeros(1, dtype=torch.long))])

    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    thread.side_effect = InlineThread
    yield service, sessions, root, dataset_id


def start(service, **kwargs):
    return service.start_training(
        "engine_diagnostics", architecture="fixture", epochs=1, batch_size=1,
        audio_config={"target_sr": 8000, "duration_seconds": 0.064, "n_mels": 32,
                      "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0},
        regularization_config={"loss_type": "cross_entropy"}, early_stopping=False, **kwargs)


def history(service, sessions):
    with sessions() as db:
        return service.get_history(db)


def test_repeated_jobs_never_overwrite_an_existing_checkpoint(persistence_env):
    service, sessions, _, _ = persistence_env
    legacy = service.checkpoints_dir / "engine_diagnostics_fixture_v1.pt"
    legacy.write_bytes(b"pre-existing checkpoint")
    first = start(service)
    assert service.get_progress()["status"] == "completed", service.get_progress()["error_message"]
    first_files = {p.name: p.read_bytes() for p in service.checkpoints_dir.iterdir()}
    second = start(service)
    assert service.get_progress()["status"] == "completed"
    assert legacy.read_bytes() == b"pre-existing checkpoint"
    assert first["job_id"] != second["job_id"]
    for name, content in first_files.items():
        assert (service.checkpoints_dir / name).read_bytes() == content
    entries = history(service, sessions)
    assert len(entries) == 2
    assert len({entry["filename"] for entry in entries}) == 2
    assert all((service.checkpoints_dir / entry["filename"]).is_file() for entry in entries)


def test_commit_failure_is_failed_and_does_not_leave_unregistered_artifacts(persistence_env):
    service, sessions, _, _ = persistence_env
    legacy = service.checkpoints_dir / "existing.pt"
    legacy.write_bytes(b"existing")
    def reject_commit(db):
        raise RuntimeError("Synthetic DB commit failure")
    event.listen(sessions, "before_commit", reject_commit)
    start(service)
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert "Synthetic DB commit failure" in progress["error_message"]
    assert [p.name for p in service.checkpoints_dir.iterdir()] == ["existing.pt"]
    assert legacy.read_bytes() == b"existing"
    assert history(service, sessions) == []
    assert not any("finalizado" in log["message"] for log in progress["logs"])


@pytest.mark.parametrize("mutation", ["renamed", "deleted"])
def test_dataset_identity_must_still_match_when_registering(persistence_env, monkeypatch, mutation):
    service, sessions, _, dataset_id = persistence_env
    save = torch.save
    def mutate_after_save(payload, output):
        save(payload, output)
        with sessions() as db:
            dataset = db.get(ConjuntoDatos, dataset_id)
            if mutation == "renamed":
                dataset.nombre = "different_source"
            else:
                db.delete(dataset)
            db.commit()
    monkeypatch.setattr(torch, "save", mutate_after_save)
    start(service)
    assert service.get_progress()["status"] == "failed"
    assert "dataset" in service.get_progress()["error_message"].lower()
    assert history(service, sessions) == []
    assert list(service.checkpoints_dir.iterdir()) == []


def test_completed_history_and_checkpoint_expose_verified_provenance(persistence_env):
    service, sessions, root, dataset_id = persistence_env
    accepted = start(service)
    assert service.get_progress()["status"] == "completed"
    entry, = history(service, sessions)
    assert entry["dataset_id"] == dataset_id
    assert entry["dataset_name"] == "engine_diagnostics"
    assert [(m["epoca"], m["precision"], m["perdida"]) for m in entry["metrics"]] == [(1, 100.0, 0.0)]
    checkpoint = service.checkpoints_dir / entry["filename"]
    assert entry["sha256"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert entry["file_size_bytes"] == checkpoint.stat().st_size
    payload = torch.load(checkpoint, weights_only=True)
    assert payload["dataset_id"] == dataset_id
    assert payload["dataset_name"] == "engine_diagnostics"
    assert payload["job_id"] == accepted["job_id"]
    assert payload["source_directory"] == str(root / "raw" / "engine_diagnostics")
    assert payload["model_index"] == 1


@pytest.mark.parametrize("failure", ["serialize", "fsync", "publish", "session", "flush", "metric"])
def test_external_save_failures_are_visible_and_clean_only_new_files(persistence_env, monkeypatch, request, failure):
    service, sessions, _, _ = persistence_env
    legacy = service.checkpoints_dir / "existing.pt"
    legacy.write_bytes(b"existing")
    def fail(*args, **kwargs):
        raise RuntimeError(f"Synthetic {failure} failure")
    if failure == "serialize":
        def partial_save(payload, output):
            output.write(b"incomplete")
            fail()
        monkeypatch.setattr(torch, "save", partial_save)
    elif failure in {"fsync", "publish"}:
        monkeypatch.setattr(training.os, "fsync" if failure == "fsync" else "link", fail)
    elif failure == "session":
        save = torch.save
        def lose_connection(payload, output):
            save(payload, output)
            monkeypatch.setattr(training, "SessionLocal", fail)
        monkeypatch.setattr(torch, "save", lose_connection)
    elif failure == "flush":
        event.listen(sessions, "before_flush", fail)
    else:
        from app.models.training import MetricaEntrenamiento
        event.listen(MetricaEntrenamiento, "before_insert", fail)
        request.addfinalizer(lambda: event.remove(MetricaEntrenamiento, "before_insert", fail))
    start(service)
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert f"Synthetic {failure} failure" in progress["error_message"]
    assert history(service, sessions) == []
    assert [p.name for p in service.checkpoints_dir.iterdir()] == ["existing.pt"]
    assert legacy.read_bytes() == b"existing"
    assert not any("guardados" in log["message"] or "finalizado" in log["message"] for log in progress["logs"])


@pytest.mark.parametrize("collision", ["final", "temporary"])
def test_uuid_collision_never_replaces_existing_files(persistence_env, monkeypatch, collision):
    from types import SimpleNamespace
    service, sessions, _, _ = persistence_env
    monkeypatch.setattr(training.uuid, "uuid4", lambda: SimpleNamespace(hex="collision"))
    name = "fama_collision_best.pt" if collision == "final" else "fama_collision_best.collision.tmp"
    existing = service.checkpoints_dir / name
    existing.write_bytes(b"owned by another job")
    start(service)
    assert service.get_progress()["status"] == "failed"
    assert existing.read_bytes() == b"owned by another job"
    assert [p.name for p in service.checkpoints_dir.iterdir()] == [name]
    assert history(service, sessions) == []


def test_partial_ensemble_failure_keeps_only_the_committed_model(persistence_env):
    service, sessions, _, _ = persistence_env
    commits = []
    def second_commit_fails(db):
        commits.append(True)
        if len(commits) == 2:
            raise RuntimeError("Second model commit failed")
    event.listen(sessions, "before_commit", second_commit_fails)
    start(service, models=[{"architecture": "fixture", "epochs": 1}, {"architecture": "fixture2", "epochs": 1}])
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert progress["error_message"] == "Second model commit failed"
    entry, = history(service, sessions)
    assert entry["architecture"] == "fixture"
    assert len(entry["metrics"]) == 1
    assert [p.name for p in service.checkpoints_dir.iterdir()] == [entry["filename"]]
    assert not any("Todos los modelos" in log["message"] for log in progress["logs"])


def test_ambiguous_post_commit_error_preserves_registered_checkpoint(persistence_env):
    service, sessions, _, _ = persistence_env
    def lost_acknowledgement(db):
        raise RuntimeError("Commit acknowledgement lost")
    event.listen(sessions, "after_commit", lost_acknowledgement)
    start(service)
    assert service.get_progress()["status"] == "failed"
    assert "Commit acknowledgement lost" in service.get_progress()["error_message"]
    entry, = history(service, sessions)
    assert entry["dataset_name"] == "engine_diagnostics"
    assert len(entry["metrics"]) == 1
    assert (service.checkpoints_dir / entry["filename"]).is_file()


def test_unverifiable_commit_retains_artifact_and_reports_uncertainty(persistence_env, monkeypatch):
    service, sessions, _, _ = persistence_env
    def lost_connection(db):
        def unavailable():
            raise RuntimeError("Registration verification unavailable")
        monkeypatch.setattr(training, "SessionLocal", unavailable)
        raise RuntimeError("Commit outcome unknown")
    event.listen(sessions, "before_commit", lost_connection)
    start(service)
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert progress["error_message"] == "Commit outcome unknown"
    assert history(service, sessions) == []
    assert len(list(service.checkpoints_dir.glob("*.pt"))) == 1
    assert any("indeterminado" in log["message"] for log in progress["logs"])


def test_job_without_epoch_metrics_cannot_claim_completed(persistence_env):
    service, sessions, _, _ = persistence_env
    start(service, models=[{"architecture": "fixture", "epochs": 0}])
    assert service.get_progress()["status"] == "failed"
    assert "métricas" in service.get_progress()["error_message"]
    assert history(service, sessions) == []
    assert list(service.checkpoints_dir.iterdir()) == []
