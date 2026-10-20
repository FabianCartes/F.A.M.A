"""Technical history describes explicit artifacts, never guessed domain presets."""
import pytest
import torch

from app.models.training import Modelo
from tests.test_training_flow import training_env
from tests.test_training_persistence import persistence_env, start, history


def test_history_uses_effective_checkpoint_physics_and_labels(persistence_env):
    service, sessions, _, _ = persistence_env
    start(service)
    assert service.get_progress()["status"] == "completed"

    entry, = history(service, sessions)

    assert entry["classes"] == ["Fixture"]
    assert entry["classes_count"] == 1
    assert entry["audio_specs"] == {
        "target_sr": 8000, "duration_seconds": 0.064, "n_mels": 32,
        "n_fft": 256, "hop_length": 64, "fmin": 0.0, "fmax": 4000.0,
    }


@pytest.mark.parametrize("artifact", ["missing", "corrupt", "invalid_metadata"])
def test_history_preserves_records_without_inventing_technical_facts(training_env, artifact):
    service, sessions, _, _ = training_env
    checkpoint = service.checkpoints_dir / "historical.pt"
    if artifact == "corrupt":
        checkpoint.write_bytes(b"not a checkpoint")
    elif artifact == "invalid_metadata":
        torch.save({"classes": [123], "audio_config": {"target_sr": -1}}, checkpoint)
    with sessions() as db:
        db.add(Modelo(arquitectura="EfficientNet-B0", clase_objetivo="15 Clases (AvesChilenas)",
                      epocas=10, tasa_aprendizaje=0.002, tamano_lote=8,
                      ruta_binario_gcp="models/historical.pt", tamano_bytes=0))
        db.commit()
        entry, = service.get_history(db)

    assert entry["architecture"] == "EfficientNet-B0"
    assert entry["hyperparameters"]["learning_rate"] == 0.002
    assert entry["hyperparameters"]["batch_size"] == 8
    assert entry["hyperparameters"]["optimizer"] is None
    assert entry["hyperparameters"]["loss_type"] is None
    assert entry["audio_specs"] is None
    assert entry["classes"] == []
    assert entry["classes_count"] is None
    assert entry["file_size_bytes"] == (None if artifact == "missing" else checkpoint.stat().st_size)


def test_history_reports_loss_and_optimizer_actually_used(persistence_env):
    service, sessions, _, _ = persistence_env
    start(service)
    assert service.get_progress()["status"] == "completed"

    entry, = history(service, sessions)

    assert entry["hyperparameters"]["optimizer"] == "AdamW"
    assert entry["hyperparameters"]["loss_type"] == "CrossEntropy"


def test_history_without_database_does_not_invent_saved_models(training_env):
    service, _, _, _ = training_env

    assert service.get_history() == []


def test_history_reads_metadata_with_lazy_tensor_storage(persistence_env, monkeypatch):
    service, sessions, _, _ = persistence_env
    start(service)
    assert service.get_progress()["status"] == "completed"
    load = torch.load

    def bounded_artifact_reader(*args, **kwargs):
        # External storage-adapter constraint: history cannot materialize all
        # tensor bytes just to display metadata. Preserve real deserialization.
        if kwargs.get("mmap") is not True or kwargs.get("map_location") != "cpu":
            raise MemoryError("Synthetic reader forbids eager tensor storage")
        return load(*args, **kwargs)

    monkeypatch.setattr(torch, "load", bounded_artifact_reader)

    entry, = history(service, sessions)

    assert entry["classes"] == ["Fixture"]
    assert entry["audio_specs"]["target_sr"] == 8000


@pytest.mark.parametrize("outside_root", [False, True])
def test_history_preserves_database_bytes_for_local_artifact_metadata(training_env, outside_root):
    import hashlib

    service, sessions, root, _ = training_env
    artifact = service.checkpoints_dir / "probe_v0.pt"
    payload = {"classes": ["One", "One"]}
    if outside_root:
        target = root / "outside.pt"
        torch.save(payload, target)
        artifact.symlink_to(target)
    else:
        torch.save(payload, artifact)
    with sessions() as db:
        db.add(Modelo(arquitectura="fixture", clase_objetivo="Motores", epocas=2,
                      tasa_aprendizaje=0.0, tamano_lote=0, precision=0.0, perdida=0.0,
                      ruta_binario_gcp="models/probe_v0.pt", tamano_bytes=0))
        db.commit()
        connection = db.connection().connection.driver_connection
        before = hashlib.sha256(connection.serialize()).digest()
        artifact_before = hashlib.sha256(artifact.read_bytes()).digest()
        entry, = service.get_history(db)
        assert hashlib.sha256(connection.serialize()).digest() == before
        assert hashlib.sha256(artifact.read_bytes()).digest() == artifact_before
        assert entry["version"] == 0
        assert entry["accuracy"] == entry["loss"] == 0.0
        assert entry["hyperparameters"]["learning_rate"] == 0.0
        assert entry["hyperparameters"]["batch_size"] == 0
        assert entry["classes"] == []
        assert entry["classes_count"] is None
        assert entry["audio_specs"] is None
        assert entry["file_size_bytes"] == (None if outside_root else artifact.stat().st_size)
