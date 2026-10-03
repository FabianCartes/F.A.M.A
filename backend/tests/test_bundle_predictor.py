import tempfile
from pathlib import Path
import json
import torch
import torch.nn as nn
import pytest
import numpy as np
import soundfile as sf

from poc.train import AudioCNN
from app.services.predictors.base import ModelWeightsError

from training.schemas.config import (
    TrainingConfig,
    AudioConfig,
    ArchitectureConfig,
    LossConfig,
    DatasetConfig,
    SplitConfig,
)
from training.exporters.bundle_exporter import BundleExporter
from app.services.predictors.bundle_predictor import BundleAudioPredictor
from app.services.registry import ModelRegistry, discover_and_register_bundles


@pytest.fixture
def created_bundle_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        cfg = TrainingConfig(
            experiment_id="exp-auto-01",
            model_id="bundle-anfibios-test",
            model_name="Anfibios Bundle Test",
            description="Modelo exportado para prueba de serving",
            epochs=1,
            batch_size=2,
            architecture=ArchitectureConfig(type="audio_cnn", pretrained=False),
            audio=AudioConfig(target_sr=32000, duration_seconds=3.0, n_mels=64),
            loss=LossConfig(name="cross_entropy"),
            dataset=DatasetConfig(metadata_csv=Path("/tmp/m.csv"), raw_dir=Path("/tmp/r")),
            split=SplitConfig(),
        )
        model = AudioCNN(num_classes=2)
        classes = ["Rana chilena", "Sapito de cuatro ojos"]
        metrics = {"f1_macro": 0.885}

        bundle_path = BundleExporter.export(
            output_dir=root,
            model=model,
            config=cfg,
            classes=classes,
            metrics=metrics,
        )
        yield root, bundle_path


@pytest.fixture
def tonal_audio(tmp_path):
    sr = 32000
    t = np.arange(sr * 3) / sr
    path = tmp_path / "tone.wav"
    sf.write(path, 0.2 * np.sin(2 * np.pi * 440 * t), sr)
    return path


@pytest.mark.parametrize("failure", ["missing", "corrupt", "partial", "missing_buffer", "wrong_shape", "unexpected", "empty"])
@pytest.mark.parametrize("signal", ["tone", "silence", "noise"])
def test_bundle_predict_rejects_unavailable_weights(created_bundle_dir, tonal_audio, failure, signal):
    _, bundle_path = created_bundle_dir
    weights = bundle_path / "weights.pt"
    if failure == "missing":
        manifest_path = bundle_path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["model_specs"]["weights_file"] = "missing.pt"
        manifest_path.write_text(json.dumps(manifest))
    elif failure == "corrupt":
        weights.write_bytes(b"not a checkpoint")
    else:
        state = AudioCNN(num_classes=2).state_dict()
        if failure == "partial":
            state.pop("classifier.3.bias")
        elif failure == "missing_buffer":
            state = dict(state)
            state.pop("features.1.num_batches_tracked")
        elif failure == "wrong_shape":
            state["classifier.3.weight"] = torch.zeros(3, 128)
        elif failure == "unexpected":
            state["unknown.weight"] = torch.zeros(1)
        else:
            state = {}
        torch.save(state, weights)
    if signal == "silence":
        sf.write(tonal_audio, np.zeros(32000 * 3), 32000)
    elif signal == "noise":
        sf.write(tonal_audio, np.random.default_rng(42).normal(0, 0.2, 32000 * 3), 32000)

    predictor = BundleAudioPredictor(bundle_dir=bundle_path, device=torch.device("cpu"))
    with pytest.raises(ModelWeightsError):
        predictor.predict(tonal_audio)


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, TypeError])
def test_bundle_predict_propagates_forward_error(created_bundle_dir, tonal_audio, error_type):
    _, bundle_path = created_bundle_dir
    predictor = BundleAudioPredictor(
        bundle_dir=bundle_path, device=torch.device("cpu"), lazy_load=False,
    )
    failure = error_type("forward failed")

    class FailingModel(nn.Module):
        def forward(self, inputs):
            raise failure

    # Double at the external PyTorch model execution seam, not a private loader.
    predictor.model = FailingModel()
    with pytest.raises(error_type) as raised:
        predictor.predict(tonal_audio)
    assert raised.value is failure


@pytest.mark.parametrize("failure", ["partial", "wrong_shape"])
def test_bundle_predict_retries_failed_load_until_repaired(created_bundle_dir, tonal_audio, failure):
    _, bundle_path = created_bundle_dir
    model = AudioCNN(num_classes=2)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.classifier[3].bias.copy_(torch.tensor([0.0, 2.0]))
    valid_state = model.state_dict()
    invalid_state = dict(valid_state)
    if failure == "partial":
        invalid_state.pop("classifier.3.bias")
    else:
        invalid_state["classifier.3.bias"] = torch.zeros(3)
    weights = bundle_path / "weights.pt"
    torch.save(invalid_state, weights)
    predictor = BundleAudioPredictor(bundle_dir=bundle_path, device=torch.device("cpu"))

    for _ in range(2):
        with pytest.raises(ModelWeightsError):
            predictor.predict(tonal_audio)

    torch.save(valid_state, weights)
    result = predictor.predict(tonal_audio)
    assert result.clase == "Sapito de cuatro ojos"
    assert result.confianza == pytest.approx(0.8808)
    assert result.detalles["status"] == "bundle_classified"


@pytest.mark.parametrize("lazy_load", [True, False])
def test_exported_bundle_predicts_using_manifest_preprocessing(created_bundle_dir, tonal_audio, lazy_load):
    _, bundle_path = created_bundle_dir
    model = AudioCNN(num_classes=2)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.classifier[3].bias.copy_(torch.tensor([0.0, 2.0]))
    torch.save(model.state_dict(), bundle_path / "weights.pt")
    manifest_path = bundle_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["audio_specs"].update(
        target_sr=16000, duration_seconds=1.0, n_mels=32,
        n_fft=512, hop_length=160, f_min=100, f_max=7000,
    )
    manifest["diagnostics"]["default_temperature"] = 2.0
    manifest_path.write_text(json.dumps(manifest))
    predictor = BundleAudioPredictor(
        bundle_dir=bundle_path, device=torch.device("cpu"), lazy_load=lazy_load,
    )

    result = predictor.predict(tonal_audio)
    assert result.clase == "Sapito de cuatro ojos"
    assert result.confianza == pytest.approx(0.7311)
    assert result.detalles["status"] == "bundle_classified"
    assert result.detalles["windows_count"] == 3


@pytest.mark.parametrize("signal, expected_status", [("silence", "silence"), ("noise", "noise")])
def test_available_bundle_preserves_domain_negatives(created_bundle_dir, tonal_audio, signal, expected_status):
    _, bundle_path = created_bundle_dir
    waveform = np.zeros(32000 * 3) if signal == "silence" else np.random.default_rng(42).normal(0, 0.2, 32000 * 3)
    sf.write(tonal_audio, waveform, 32000)
    predictor = BundleAudioPredictor(bundle_dir=bundle_path, device=torch.device("cpu"))

    result = predictor.predict(tonal_audio)
    assert result.confianza == 0.0
    assert result.detalles["status"] == expected_status
    assert result.clase == ("Silencio / No detectado" if signal == "silence" else "Ruido / Señal no biológica")


def test_bundle_audio_predictor_reads_manifest(created_bundle_dir):
    _, bundle_path = created_bundle_dir
    predictor = BundleAudioPredictor(bundle_dir=bundle_path)

    assert predictor.model_id == "bundle-anfibios-test"
    meta = predictor.metadata
    assert meta.id == "bundle-anfibios-test"
    assert meta.target_sr == 32000
    assert meta.duration_seconds == 3.0
    assert meta.classes == ["Rana chilena", "Sapito de cuatro ojos"]
    assert meta.metrics["f1_macro"] == 0.885


def test_bundle_predict_rejects_corrupt_audio(created_bundle_dir, tmp_path):
    from training.pipelines.dataset import MalformedAudioError

    _, bundle_path = created_bundle_dir
    predictor = BundleAudioPredictor(bundle_path, device=torch.device("cpu"))
    audio_path = tmp_path / "corrupt.wav"
    audio_path.write_bytes(b"not audio")

    with pytest.raises(MalformedAudioError) as caught:
        predictor.predict(audio_path)
    assert isinstance(caught.value.__cause__, sf.LibsndfileError)


@pytest.mark.parametrize("error", [
    RuntimeError("secondary decoder failed"), PermissionError("denied"),
    sf.LibsndfileError(1),
])
def test_bundle_tta_decode_failure_propagates(
    created_bundle_dir, tonal_audio, monkeypatch, error,
):
    import librosa

    _, bundle_path = created_bundle_dir
    predictor = BundleAudioPredictor(bundle_path, device=torch.device("cpu"))
    original_load = librosa.load
    initial_decode = True

    def decode_then_fail(*args, **kwargs):
        nonlocal initial_decode
        if initial_decode:
            initial_decode = False
            return original_load(*args, **kwargs)
        raise error

    # Decoder seam: the initial waveform is valid, but the full TTA read fails.
    monkeypatch.setattr(librosa, "load", decode_then_fail)
    with pytest.raises(type(error)) as caught:
        predictor.predict(tonal_audio)
    assert caught.value is error


def test_bundle_predict_rejects_missing_audio(created_bundle_dir):
    _, bundle_path = created_bundle_dir
    predictor = BundleAudioPredictor(bundle_dir=bundle_path)

    with pytest.raises(FileNotFoundError):
        predictor.predict(bundle_path / "missing.wav")


def test_discover_and_register_bundles(created_bundle_dir):
    root, _ = created_bundle_dir
    registry = ModelRegistry()

    assert not registry.has_model("bundle-anfibios-test")

    # Ejecutar autodescubrimiento
    discover_and_register_bundles(registry=registry, checkpoints_root=root)

    assert registry.has_model("bundle-anfibios-test")
    predictor = registry.get("bundle-anfibios-test")
    assert predictor.model_id == "bundle-anfibios-test"


def test_discover_bundles_handles_corrupted_manifest_gracefully():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        corrupt_dir = root / "corrupt_bundle"
        corrupt_dir.mkdir()
        # Escribir manifest roto
        (corrupt_dir / "manifest.json").write_text("{ broken json: true", encoding="utf-8")

        registry = ModelRegistry()
        # No debe lanzar excepción no controlada
        discover_and_register_bundles(registry=registry, checkpoints_root=root)
        assert len(registry.list_models()) == 0


def test_engine_diagnostics_bundle_predictor_predicts_audio(tmp_path):
    import soundfile as sf
    import numpy as np

    bundle_dir = Path(__file__).resolve().parents[1] / "checkpoints/car-engine-diagnostics-resnet34d"
    if not bundle_dir.exists():
        pytest.skip("Car engine diagnostics bundle not found")

    predictor = BundleAudioPredictor(bundle_dir=bundle_dir, lazy_load=False)
    assert predictor.model_id == "car-engine-diagnostics-resnet34d"

    sr = 32000
    t = np.linspace(0, 5.0, int(sr * 5.0), endpoint=False)
    waveform = (0.2 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
    wav_path = tmp_path / "engine_sample.wav"
    sf.write(wav_path, waveform, sr)

    result = predictor.predict(wav_path)
    assert result.clase in predictor.metadata.classes
    assert result.confianza > 0.0
    assert result.detalles["status"] == "bundle_classified"
    assert result.detalles.get("windows_count", 1) >= 1


