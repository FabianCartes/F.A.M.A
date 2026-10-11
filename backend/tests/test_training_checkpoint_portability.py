"""Portable checkpoint publication through public training interfaces."""
from tests.test_training_persistence import persistence_env, start, history
from tests.test_training_flow import training_env


def test_training_publishes_checkpoint_without_directory_descriptor_support(persistence_env, monkeypatch):
    import os

    service, sessions, _, _ = persistence_env
    monkeypatch.delattr(os, "O_DIRECTORY", raising=False)

    start(service)

    progress = service.get_progress()
    assert progress["status"] == "completed", progress["error_message"]
    entry, = history(service, sessions)
    assert (service.checkpoints_dir / entry["filename"]).is_file()
    assert entry["sha256"]
