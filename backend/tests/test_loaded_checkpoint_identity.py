import hashlib
import io
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import numpy as np
import pytest
import torch
from torch import nn

from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services.predictors.base import AudioPredictor
from app.services.predictors import trained_predictor as predictor_module
from app.services.predictors.trained_predictor import TrainedModelPredictor


class CountingPublicPredictor(AudioPredictor):
    def __init__(self, model_id):
        self._metadata = ModelMetadata(
            id=model_id, name=model_id, description="synthetic public-seam predictor",
            is_default=False,
        )
        self.metadata_reads = 0
        self.prediction_calls = 0

    @property
    def metadata(self):
        self.metadata_reads += 1
        return self._metadata

    @property
    def is_default(self):
        return self._metadata.is_default

    @is_default.setter
    def is_default(self, value):
        self._metadata.is_default = value

    def predict(self, audio_file_path):
        self.prediction_calls += 1
        return PredictionResult(clase="A", confianza=1.0)


class SnapshotAudioCNN(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        self.register_buffer("selected_index", torch.tensor(0, dtype=torch.long))
        self.num_classes = num_classes

    def forward(self, inputs):
        logits = torch.zeros((inputs.shape[0], self.num_classes), device=inputs.device)
        logits[:, int(self.selected_index.item())] = 10.0
        return logits


def _checkpoint_bytes(selected_index):
    model = SnapshotAudioCNN(num_classes=2)
    model.selected_index.fill_(selected_index)
    stream = io.BytesIO()
    torch.save({
        "architecture": "AudioCNN",
        "classes": ["Instantánea A", "Instantánea B"],
        "state_dict": model.state_dict(),
    }, stream)
    return stream.getvalue()


def test_predictor_hashes_and_deserializes_one_checkpoint_snapshot(tmp_path, monkeypatch):
    checkpoint_path = tmp_path / "checkpoint.pt"
    snapshot_a = _checkpoint_bytes(0)
    checkpoint_path.write_bytes(snapshot_a)
    expected_hash = hashlib.sha256(snapshot_a).hexdigest()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio fixture")

    monkeypatch.setattr(predictor_module, "AudioCNN", SnapshotAudioCNN)
    monkeypatch.setattr(
        predictor_module, "load_and_fix_length",
        lambda *args, **kwargs: np.full(2048, 0.1, dtype=np.float32),
    )
    monkeypatch.setattr(predictor_module, "extract_mel_spectrogram", lambda *args, **kwargs: np.zeros((2, 2)))
    monkeypatch.setattr(
        predictor_module.librosa.feature, "spectral_flatness",
        lambda **kwargs: np.array([[0.01]], dtype=np.float32),
    )

    original_load = torch.load
    load_calls = 0

    def replace_checkpoint_before_deserialization(source, *args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        if load_calls == 2:
            checkpoint_path.write_bytes(_checkpoint_bytes(1))
        return original_load(source, *args, **kwargs)

    monkeypatch.setattr(torch, "load", replace_checkpoint_before_deserialization)

    predictor = TrainedModelPredictor(
        checkpoint_path=checkpoint_path,
        expected_checkpoint_sha256=expected_hash,
        lazy_load=True,
    )
    result = predictor.predict(audio_path)

    assert result.clase == "Instantánea A"
    assert result.detalles["loaded_checkpoint_sha256"] == expected_hash
    assert predictor.metadata.loaded_checkpoint_sha256 == expected_hash
    assert predictor.metadata.checkpoint_sha256 == hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()


def test_loaded_predictor_keeps_identity_after_checkpoint_is_replaced(tmp_path, monkeypatch):
    checkpoint_path = tmp_path / "loaded-checkpoint.pt"
    snapshot_a = _checkpoint_bytes(0)
    checkpoint_path.write_bytes(snapshot_a)
    hash_a = hashlib.sha256(snapshot_a).hexdigest()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio fixture")

    monkeypatch.setattr(predictor_module, "AudioCNN", SnapshotAudioCNN)
    monkeypatch.setattr(
        predictor_module, "load_and_fix_length",
        lambda *args, **kwargs: np.full(2048, 0.1, dtype=np.float32),
    )
    monkeypatch.setattr(predictor_module, "extract_mel_spectrogram", lambda *args, **kwargs: np.zeros((2, 2)))
    monkeypatch.setattr(
        predictor_module.librosa.feature, "spectral_flatness",
        lambda **kwargs: np.array([[0.01]], dtype=np.float32),
    )
    predictor = TrainedModelPredictor(
        checkpoint_path=checkpoint_path,
        expected_checkpoint_sha256=hash_a,
    )
    snapshot_b = _checkpoint_bytes(1)
    checkpoint_path.write_bytes(snapshot_b)

    result = predictor.predict(audio_path)

    assert result.clase == "Instantánea A"
    assert result.detalles["loaded_checkpoint_sha256"] == hash_a
    assert predictor.metadata.loaded_checkpoint_sha256 == hash_a
    assert predictor.metadata.checkpoint_sha256 == hashlib.sha256(snapshot_b).hexdigest()


def test_standalone_predictor_without_expected_hash_reports_loaded_snapshot(tmp_path, monkeypatch):
    checkpoint_path = tmp_path / "standalone.pt"
    snapshot = _checkpoint_bytes(0)
    checkpoint_path.write_bytes(snapshot)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio fixture")

    monkeypatch.setattr(predictor_module, "AudioCNN", SnapshotAudioCNN)
    monkeypatch.setattr(
        predictor_module, "load_and_fix_length",
        lambda *args, **kwargs: np.full(2048, 0.1, dtype=np.float32),
    )
    monkeypatch.setattr(predictor_module, "extract_mel_spectrogram", lambda *args, **kwargs: np.zeros((2, 2)))
    monkeypatch.setattr(
        predictor_module.librosa.feature, "spectral_flatness",
        lambda **kwargs: np.array([[0.01]], dtype=np.float32),
    )
    predictor = TrainedModelPredictor(checkpoint_path=checkpoint_path, lazy_load=True)
    result = predictor.predict(audio_path)

    assert predictor.expected_checkpoint_sha256 is None
    assert result.clase == "Instantánea A"
    assert result.detalles["loaded_checkpoint_sha256"] == hashlib.sha256(snapshot).hexdigest()


@pytest.mark.parametrize("signal_kind", ["silence", "noise"])
def test_silence_and_noise_results_report_loaded_checkpoint_identity(
    tmp_path, monkeypatch, signal_kind,
):
    checkpoint_path = tmp_path / "signal-checkpoint.pt"
    snapshot = _checkpoint_bytes(0)
    checkpoint_path.write_bytes(snapshot)
    expected_hash = hashlib.sha256(snapshot).hexdigest()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio fixture")

    monkeypatch.setattr(predictor_module, "AudioCNN", SnapshotAudioCNN)
    waveform = (np.zeros(2048, dtype=np.float32) if signal_kind == "silence"
                else np.full(2048, 0.1, dtype=np.float32))
    monkeypatch.setattr(
        predictor_module, "load_and_fix_length",
        lambda *args, **kwargs: waveform,
    )
    monkeypatch.setattr(
        predictor_module.librosa.feature, "spectral_flatness",
        lambda **kwargs: np.array([[0.2]], dtype=np.float32),
    )
    predictor = TrainedModelPredictor(
        checkpoint_path=checkpoint_path,
        expected_checkpoint_sha256=expected_hash,
        lazy_load=True,
    )

    result = predictor.predict(audio_path)

    assert result.detalles["status"] == signal_kind
    assert result.detalles["loaded_checkpoint_sha256"] == expected_hash


def test_concurrent_lazy_predictions_publish_one_coherent_checkpoint_identity(tmp_path, monkeypatch):
    checkpoint_path = tmp_path / "concurrent-checkpoint.pt"
    snapshot = _checkpoint_bytes(0)
    checkpoint_path.write_bytes(snapshot)
    expected_hash = hashlib.sha256(snapshot).hexdigest()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio fixture")
    entered_load = Event()
    finish_load = Event()
    count_lock = Lock()
    constructions = 0

    class ConcurrentSnapshotAudioCNN(SnapshotAudioCNN):
        def __init__(self, num_classes):
            nonlocal constructions
            with count_lock:
                constructions += 1
            entered_load.set()
            assert finish_load.wait(timeout=5)
            super().__init__(num_classes)

    monkeypatch.setattr(predictor_module, "AudioCNN", ConcurrentSnapshotAudioCNN)
    monkeypatch.setattr(
        predictor_module, "load_and_fix_length",
        lambda *args, **kwargs: np.full(2048, 0.1, dtype=np.float32),
    )
    monkeypatch.setattr(predictor_module, "extract_mel_spectrogram", lambda *args, **kwargs: np.zeros((2, 2)))
    monkeypatch.setattr(
        predictor_module.librosa.feature, "spectral_flatness",
        lambda **kwargs: np.array([[0.01]], dtype=np.float32),
    )
    predictor = TrainedModelPredictor(
        checkpoint_path=checkpoint_path,
        expected_checkpoint_sha256=expected_hash,
        lazy_load=True,
    )
    start = Barrier(3)

    def predict():
        start.wait(timeout=5)
        return predictor.predict(audio_path)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(predict) for _ in range(2)]
        start.wait(timeout=5)
        assert entered_load.wait(timeout=5)
        finish_load.set()
        predictions = [future.result(timeout=5) for future in results]

    assert constructions == 1
    assert [result.clase for result in predictions] == ["Instantánea A", "Instantánea A"]
    assert all(result.detalles["loaded_checkpoint_sha256"] == expected_hash for result in predictions)
    assert predictor.metadata.loaded_checkpoint_sha256 == expected_hash


def test_lazy_predictor_rejects_checkpoint_replacement_before_first_load(tmp_path):
    checkpoint_path = tmp_path / "lazy-checkpoint.pt"
    snapshot_a = _checkpoint_bytes(0)
    checkpoint_path.write_bytes(snapshot_a)
    expected_hash = hashlib.sha256(snapshot_a).hexdigest()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio fixture")

    predictor = TrainedModelPredictor(
        checkpoint_path=checkpoint_path,
        expected_checkpoint_sha256=expected_hash,
        lazy_load=True,
    )
    assert predictor.metadata.loaded_checkpoint_sha256 is None
    checkpoint_path.write_bytes(_checkpoint_bytes(1))

    from app.services.predictors.base import ModelWeightsError
    with pytest.raises(ModelWeightsError, match="no coincide con el hash SHA-256 registrado"):
        predictor.predict(audio_path)

    assert predictor.model is None
    assert predictor.metadata.loaded_checkpoint_sha256 is None


@pytest.mark.parametrize("persisted_hash", [None, "not-a-sha256"])
def test_registry_blocks_db_models_without_a_valid_persisted_checkpoint_hash(
    tmp_path, persisted_hash,
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.predictors.base import ModelWeightsError
    from app.services.registry import ModelRegistry

    checkpoint_path = tmp_path / "fama_missing_hash_best.pt"
    checkpoint_path.write_bytes(b"untrusted model artifact" * 1000)
    model = SimpleNamespace(
        id_modelo=91,
        activo=True,
        arquitectura="fixture",
        ruta_binario_gcp=f"models/{checkpoint_path.name}",
        conjunto_datos=None,
        hash_binario=persisted_hash,
    )
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = [model]
    registry = ModelRegistry()

    registry.register_from_db(db, tmp_path)

    assert not registry.has_model("fama_trained_model_91")
    with pytest.raises(ModelWeightsError, match="hash SHA-256 registrado"):
        registry.get("fama_trained_model_91")
    with pytest.raises(ModelWeightsError, match="hash SHA-256 registrado"):
        registry.get()


def test_registry_does_not_reuse_cached_model_after_registered_hash_changes(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.predictors.base import ModelWeightsError
    from app.services.registry import ModelRegistry

    checkpoint_path = tmp_path / "fama_cached_identity_best.pt"
    torch.save({
        "architecture": "AudioCNN",
        "classes": ["A", "B"],
        "padding": "x" * 12000,
    }, checkpoint_path)
    checkpoint_hash = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    model = SimpleNamespace(
        id_modelo=92,
        activo=False,
        arquitectura="fixture",
        ruta_binario_gcp=f"models/{checkpoint_path.name}",
        conjunto_datos=None,
        hash_binario=checkpoint_hash,
    )
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = [model]
    registry = ModelRegistry()

    registry.register_from_db(db, tmp_path)
    cached = registry.get("92")
    assert cached.expected_checkpoint_sha256 == checkpoint_hash

    model.hash_binario = "b" * 64
    registry.register_from_db(db, tmp_path)

    with pytest.raises(ModelWeightsError, match="no coincide con el hash SHA-256 registrado"):
        registry.get("92")
    assert not registry.has_model("fama_trained_model_92")


def test_checkpoint_discovery_does_not_alias_db_model_blocked_by_missing_hash(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.registry import ModelRegistry, discover_and_register_checkpoints

    checkpoint_path = tmp_path / "fama_blocked_93_best.pt"
    model = SnapshotAudioCNN(num_classes=2)
    torch.save({
        "architecture": "AudioCNN",
        "classes": ["A", "B"],
        "state_dict": model.state_dict(),
        "padding": torch.zeros(300000),
    }, checkpoint_path)
    monkeypatch.setattr(predictor_module, "AudioCNN", SnapshotAudioCNN)
    db_model = SimpleNamespace(
        id_modelo=93,
        activo=True,
        arquitectura="AudioCNN",
        ruta_binario_gcp=f"models/{checkpoint_path.name}",
        conjunto_datos=None,
        hash_binario=None,
    )
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = [db_model]
    registry = ModelRegistry()

    discovered = discover_and_register_checkpoints(registry, tmp_path, db=db)

    assert discovered == 0
    assert not registry.has_model(checkpoint_path.name)
    assert not registry.has_model(checkpoint_path.stem)
    from app.services.predictors.base import ModelWeightsError
    with pytest.raises(ModelWeightsError, match="hash SHA-256 registrado"):
        registry.get(checkpoint_path.stem)


@pytest.mark.parametrize("entrypoint", ["publish_from_db", "register_from_db"])
@pytest.mark.parametrize("persisted_hash,expected_code", [
    (None, "checkpoint_hash_missing"),
    ("not-a-sha256", "checkpoint_hash_invalid"),
])
@pytest.mark.parametrize("alias_kind", ["model_id", "filename", "stem", "numeric_id"])
def test_blocked_persisted_alias_precedes_unrelated_registered_predictor(
    tmp_path, entrypoint, persisted_hash, expected_code, alias_kind,
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.predictors.base import ModelWeightsError
    from app.services.registry import ModelRegistry

    model_id = 137
    key = f"fama_trained_model_{model_id}"
    filename = "fama_collision_137.pt"
    aliases = {
        "model_id": key,
        "filename": filename,
        "stem": Path(filename).stem,
        "numeric_id": str(model_id),
    }
    collided_alias = aliases[alias_kind]
    checkpoint = tmp_path / filename
    checkpoint_bytes = b"synthetic blocked checkpoint" * 500
    checkpoint.write_bytes(checkpoint_bytes)
    model = SimpleNamespace(
        id_modelo=model_id,
        activo=False,
        arquitectura="fixture",
        ruta_binario_gcp=f"models/{filename}",
        conjunto_datos=None,
        hash_binario=persisted_hash,
    )
    persisted_fields = (model.ruta_binario_gcp, model.hash_binario, model.activo)
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = [model]
    registry = ModelRegistry()
    default_predictor = CountingPublicPredictor("unrelated-default")
    colliding_predictor = CountingPublicPredictor(collided_alias)
    registry.register(default_predictor, is_default=True)
    registry.register(colliding_predictor)
    default_predictor.metadata_reads = 0
    colliding_predictor.metadata_reads = 0

    if entrypoint == "publish_from_db":
        errors = registry.publish_from_db(db, checkpoints_root=tmp_path)
        assert errors == [{"model_id": key, "code": expected_code}]
    else:
        assert registry.register_from_db(db, checkpoints_root=tmp_path) is None

    with pytest.raises(ModelWeightsError, match="hash SHA-256 registrado"):
        registry.get(collided_alias)

    # A rejected lookup leaves explicit registrations and the selected fallback intact.
    assert registry.has_model(collided_alias)
    assert registry.get("unrelated-default") is default_predictor
    assert registry.get() is default_predictor
    assert registry.get_default_model_id() == "unrelated-default"
    assert (model.ruta_binario_gcp, model.hash_binario, model.activo) == persisted_fields
    assert checkpoint.read_bytes() == checkpoint_bytes
    db.add.assert_not_called()
    db.commit.assert_not_called()
    assert default_predictor.metadata_reads == 0
    assert colliding_predictor.metadata_reads == 0
    assert default_predictor.prediction_calls == 0
    assert colliding_predictor.prediction_calls == 0


@pytest.mark.parametrize("entrypoint", ["publish_from_db", "register_from_db"])
@pytest.mark.parametrize("persisted_hash,expected_code", [
    (None, "checkpoint_hash_missing"),
    ("malformed", "checkpoint_hash_invalid"),
])
def test_blocked_active_persisted_model_rejects_unrelated_default_resolution(
    tmp_path, entrypoint, persisted_hash, expected_code,
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.predictors.base import ModelWeightsError
    from app.services.registry import ModelRegistry

    filename = "fama_active_blocked_138.pt"
    checkpoint = tmp_path / filename
    checkpoint_bytes = b"synthetic blocked active checkpoint" * 500
    checkpoint.write_bytes(checkpoint_bytes)
    model = SimpleNamespace(
        id_modelo=138,
        activo=True,
        arquitectura="fixture",
        ruta_binario_gcp=f"models/{filename}",
        conjunto_datos=None,
        hash_binario=persisted_hash,
    )
    persisted_fields = (model.ruta_binario_gcp, model.hash_binario, model.activo)
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = [model]
    registry = ModelRegistry()
    unrelated_default = CountingPublicPredictor("unrelated-active-fallback")
    registry.register(unrelated_default, is_default=True)
    unrelated_default.metadata_reads = 0

    if entrypoint == "publish_from_db":
        errors = registry.publish_from_db(db, checkpoints_root=tmp_path)
        assert errors == [{"model_id": "fama_trained_model_138", "code": expected_code}]
    else:
        assert registry.register_from_db(db, checkpoints_root=tmp_path) is None

    with pytest.raises(ModelWeightsError, match="hash SHA-256 registrado"):
        registry.get()
    with pytest.raises(ModelWeightsError, match="hash SHA-256 registrado"):
        registry.get("default")
    with pytest.raises(ModelWeightsError, match="hash SHA-256 registrado"):
        registry.get_active_predictor()

    # Explicit access remains available; only default resolution fails closed.
    assert registry.get("unrelated-active-fallback") is unrelated_default
    assert registry.get_default_model_id() == "unrelated-active-fallback"
    assert (model.ruta_binario_gcp, model.hash_binario, model.activo) == persisted_fields
    assert checkpoint.read_bytes() == checkpoint_bytes
    db.add.assert_not_called()
    db.commit.assert_not_called()
    assert unrelated_default.metadata_reads == 0
    assert unrelated_default.prediction_calls == 0
