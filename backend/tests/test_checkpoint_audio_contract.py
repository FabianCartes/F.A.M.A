"""Checkpoint audio contracts through public predictor interfaces, CPU only."""
import pytest
import torch
import numpy as np
import soundfile as sf
import timm

from app.services.predictors.trained_predictor import TrainedModelPredictor, ModelWeightsError
from poc.train import AudioCNN, BioacousticModel
from poc.preprocess import (GPUAudioFrontEnd, extract_active_windows, compute_rms,
                            load_and_fix_length, extract_mel_spectrogram)
from training.pipelines.dataset import load_and_resample
from tests.test_training_flow import training_env
from tests.test_training_flow import partitions, register
from tests.test_training_persistence import persistence_env, history


@pytest.fixture(autouse=True)
def cpu_only(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)


@pytest.mark.parametrize("lazy_load", [True, False])
def test_catalogue_reports_checkpoint_audio_configuration(tmp_path, lazy_load):
    checkpoint = tmp_path / "synthetic.pt"
    torch.save({
        "architecture": "AudioCNN", "classes": ["Baja", "Alta"],
        "audio_config": {
            "target_sr": 16000, "duration_seconds": 2.0,
            "n_mels": 80, "n_fft": 512, "hop_length": 128,
            "f_min": 100.0, "f_max": 7000.0,
        },
        "state_dict": AudioCNN(num_classes=2).state_dict(),
    }, checkpoint)

    predictor = TrainedModelPredictor(checkpoint, lazy_load=lazy_load)

    assert predictor.metadata.target_sr == 16000
    assert predictor.metadata.duration_seconds == 2.0
    assert predictor.metadata.classes == ["Baja", "Alta"]


class SpectralClassifier(torch.nn.Module):
    """Tiny external-network adapter sensitive to spectral scaling and bands."""

    def __init__(self):
        super().__init__()
        self.register_buffer("scale", torch.tensor(1.0))

    def forward(self, spectrogram):
        score = spectrogram[:, :, :4, :].mean(dim=(1, 2, 3)) * self.scale
        return torch.stack((score, -score), dim=1)


@pytest.mark.parametrize("config", [{
        "target_sr": 16000, "duration_seconds": 2.0,
        "n_mels": 80, "n_fft": 512, "hop_length": 128,
        "f_min": 100.0, "f_max": 7000.0,
    }, {
        "target_sr": 32000, "duration_seconds": 2.0,
        "n_mels": 128, "n_fft": 1024, "hop_length": 512,
        "f_min": 50.0, "f_max": 16000.0,
    }, {
        "target_sr": 8000, "duration_seconds": 1.0,
        "n_mels": 32, "n_fft": 256, "hop_length": 64,
        "f_min": 0.0, "f_max": 4000.0,
    }])
def test_inference_reproduces_training_spectral_representation(tmp_path, monkeypatch, config):
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: SpectralClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False).eval()
    checkpoint = tmp_path / "synthetic.pt"
    torch.save({"architecture": "fixture", "classes": ["Baja", "Alta"],
                "audio_config": config, "state_dict": model.state_dict()}, checkpoint)
    audio = tmp_path / "signal.wav"
    time = np.arange(48000, dtype=np.float32) / 16000
    waveform = np.where(time < 1.0, 0.01, 0.1) * np.sin(2 * np.pi * 1000 * time)
    sf.write(audio, waveform, 16000, subtype="FLOAT")

    # Independent reference: the public frontend actually used during training,
    # with the declared physics and the validation dataset's energy-based crop.
    selected = load_and_resample(audio, config["target_sr"], config["duration_seconds"], strict=True)
    frontend = GPUAudioFrontEnd(sample_rate=config["target_sr"], n_mels=config["n_mels"],
                               n_fft=config["n_fft"], hop_length=config["hop_length"],
                               f_min=config["f_min"], f_max=config["f_max"])
    with torch.no_grad():
        probabilities = torch.softmax(model(frontend(torch.from_numpy(selected))), dim=1)[0]
    expected_class = ["Baja", "Alta"][int(probabilities.argmax())]
    expected_confidence = round(float(probabilities.max()), 4)

    result = TrainedModelPredictor(checkpoint, lazy_load=True).predict(audio)

    assert result.clase == expected_class
    assert result.confianza == pytest.approx(expected_confidence, abs=1e-4)
    assert result.detalles["is_mock"] is False


def test_training_persists_effective_domain_audio_defaults(persistence_env, monkeypatch):
    from app.services import training

    service, sessions, _, _ = persistence_env
    monkeypatch.setattr(training, "DataLoader", lambda *args, **kwargs: [
        (torch.ones(1, 4096), torch.zeros(1, dtype=torch.long))
    ])

    service.start_training("engine_diagnostics", architecture="fixture", epochs=1,
                           batch_size=1, early_stopping=False)

    progress = service.get_progress()
    assert progress["status"] == "completed", progress["error_message"]
    entry, = history(service, sessions)
    payload = torch.load(service.checkpoints_dir / entry["filename"], weights_only=True)
    assert payload["audio_config"] == {
        "target_sr": 32000, "duration_seconds": 2.0, "n_mels": 128,
        "n_fft": 1024, "hop_length": 512, "f_min": 50.0, "f_max": 16000.0,
    }


@pytest.mark.parametrize("lazy_load", [True, False])
@pytest.mark.parametrize("configuration", [
    {}, [], {"target_sr": 16000},
    {"target_sr": 16000, "duration_seconds": 2.0, "n_mels": 80,
     "n_fft": 512, "hop_length": 128, "f_min": 100.0, "f_max": 12000.0},
])
def test_invalid_explicit_audio_contract_never_falls_back(tmp_path, lazy_load, configuration):
    checkpoint = tmp_path / "invalid-config.pt"
    torch.save({"architecture": "AudioCNN", "classes": ["Baja", "Alta"],
                "audio_config": configuration,
                "state_dict": AudioCNN(num_classes=2).state_dict()}, checkpoint)

    with pytest.raises(ModelWeightsError, match="configuración acústica"):
        TrainedModelPredictor(checkpoint, lazy_load=lazy_load)


def test_bird_training_records_its_validation_window_selection(persistence_env, monkeypatch):
    from app.services import training

    service, sessions, root, _ = persistence_env
    register(sessions, "AvesChilenas")
    partitions(root, "AvesChilenas")
    monkeypatch.setattr(training, "DataLoader", lambda *args, **kwargs: [
        (torch.ones(1, 4096), torch.zeros(1, dtype=torch.long))
    ])

    service.start_training("AvesChilenas", architecture="fixture", epochs=1,
                           batch_size=1, early_stopping=False)

    progress = service.get_progress()
    assert progress["status"] == "completed", progress["error_message"]
    entry, = history(service, sessions)
    payload = torch.load(service.checkpoints_dir / entry["filename"], weights_only=True)
    assert payload["audio_config"] == {
        "target_sr": 22050, "duration_seconds": 5.0, "n_mels": 128,
        "n_fft": 2048, "hop_length": 512, "f_min": 800.0, "f_max": 10000.0,
    }
    assert payload["preprocessing"] == {
        "version": 1, "frontend": "gpu_mel_zscore", "window_selection": "active_max_rms",
    }


def test_inference_preserves_bird_validation_window_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: SpectralClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False).eval()
    checkpoint = tmp_path / "bird.pt"
    torch.save({
        "architecture": "fixture", "classes": ["Baja", "Alta"],
        "audio_config": {"target_sr": 22050, "duration_seconds": 5.0,
                         "n_mels": 128, "n_fft": 2048, "hop_length": 512,
                         "f_min": 800.0, "f_max": 10000.0},
        "preprocessing": {"version": 1, "frontend": "gpu_mel_zscore",
                          "window_selection": "active_max_rms"},
        "state_dict": model.state_dict(),
    }, checkpoint)
    audio = tmp_path / "bird.wav"
    time = np.arange(22050 * 11, dtype=np.float32) / 22050
    waveform = np.where((time >= 1) & (time < 6), 0.1, 0.001) * np.sin(2 * np.pi * 1000 * time)
    sf.write(audio, waveform, 22050, subtype="FLOAT")
    windows = extract_active_windows(audio, hop_seconds=2.5, top_db=25.0)
    selected = max(windows, key=compute_rms)
    frontend = GPUAudioFrontEnd(n_fft=2048, n_mels=128, f_min=800.0, f_max=10000.0)
    with torch.no_grad():
        probabilities = torch.softmax(model(frontend(torch.from_numpy(selected))), dim=1)[0]

    result = TrainedModelPredictor(checkpoint).predict(audio)

    assert result.clase == ["Baja", "Alta"][int(probabilities.argmax())]
    assert result.confianza == pytest.approx(round(float(probabilities.max()), 4), abs=1e-4)


@pytest.mark.parametrize("profile", [
    {"version": 2, "frontend": "gpu_mel_zscore", "window_selection": "max_rms"},
    {"version": 1, "frontend": "hpss", "window_selection": "max_rms"},
    {"version": 1, "frontend": "gpu_mel_zscore", "window_selection": "unknown"},
    {},
])
def test_unknown_preprocessing_profile_is_rejected(tmp_path, profile):
    checkpoint = tmp_path / "unsupported.pt"
    torch.save({
        "architecture": "AudioCNN", "classes": ["Baja", "Alta"],
        "audio_config": {"target_sr": 16000, "duration_seconds": 2.0,
                         "n_mels": 80, "n_fft": 512, "hop_length": 128,
                         "f_min": 100.0, "f_max": 7000.0},
        "preprocessing": profile, "state_dict": AudioCNN(num_classes=2).state_dict(),
    }, checkpoint)

    with pytest.raises(ModelWeightsError, match="preprocesamiento"):
        TrainedModelPredictor(checkpoint, lazy_load=True)


def test_historical_checkpoint_keeps_legacy_inference_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: SpectralClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False).eval()
    checkpoint = tmp_path / "historical.pt"
    torch.save({"architecture": "fixture", "classes": ["Baja", "Alta"],
                "state_dict": model.state_dict()}, checkpoint)
    audio = tmp_path / "legacy.wav"
    time = np.arange(22050, dtype=np.float32) / 22050
    sf.write(audio, 0.1 * np.sin(2 * np.pi * 1000 * time), 22050, subtype="FLOAT")
    waveform = load_and_fix_length(audio)
    legacy_mel = torch.from_numpy(extract_mel_spectrogram(waveform)).unsqueeze(0).unsqueeze(0)
    with torch.no_grad():
        probabilities = torch.softmax(model(legacy_mel), dim=1)[0]

    predictor = TrainedModelPredictor(checkpoint)
    result = predictor.predict(audio)

    assert predictor.metadata.target_sr == 22050
    assert predictor.metadata.duration_seconds == 5.0
    assert result.clase == ["Baja", "Alta"][int(probabilities.argmax())]
    assert result.confianza == pytest.approx(round(float(probabilities.max()), 4), abs=1e-4)
    assert result.detalles["preprocessing_mode"] == "legacy_librosa"


def test_training_persists_resolved_partial_audio_configuration(persistence_env):
    service, sessions, _, _ = persistence_env

    service.start_training("engine_diagnostics", architecture="fixture", epochs=1,
                           batch_size=1, early_stopping=False,
                           audio_config={"target_sr": 16000, "duration_seconds": 1.0, "n_mels": 32,
                                         "n_fft": 512, "f_max": 8000.0})

    progress = service.get_progress()
    assert progress["status"] == "completed", progress["error_message"]
    entry, = history(service, sessions)
    payload = torch.load(service.checkpoints_dir / entry["filename"], weights_only=True)
    assert payload["audio_config"] == {
        "target_sr": 16000, "duration_seconds": 1.0, "n_mels": 32,
        "n_fft": 512, "hop_length": 512, "f_min": 50.0, "f_max": 8000.0,
    }
    assert payload["preprocessing"]["window_selection"] == "max_rms"


@pytest.mark.parametrize('invalid', [
    {'audio_config': {}},
    {'preprocessing': {'version': True, 'frontend': 'gpu_mel_zscore', 'window_selection': 'max_rms'}},
])
def test_lazy_acoustic_rejection_preserves_identity_and_can_retry(tmp_path, monkeypatch, invalid):
    import hashlib

    monkeypatch.setattr(timm, 'create_model', lambda *args, **kwargs: SpectralClassifier())
    config = {'target_sr': 8000, 'duration_seconds': 1.0, 'n_mels': 32, 'n_fft': 256,
              'hop_length': 64, 'f_min': 0.0, 'f_max': 4000.0}
    payload = {'architecture': 'fixture', 'classes': ['Baja', 'Alta'], 'audio_config': config,
               'state_dict': BioacousticModel('fixture', num_classes=2, pretrained=False).state_dict()}
    checkpoint = tmp_path / 'retry.pt'
    audio = tmp_path / 'tone.wav'
    sf.write(audio, 0.3 * np.sin(2 * np.pi * 440 * np.arange(8000) / 8000), 8000)
    torch.save(payload, checkpoint)
    original = checkpoint.read_bytes()
    predictor = TrainedModelPredictor(checkpoint, lazy_load=True)
    torch.save({**payload, **invalid}, checkpoint)
    before = checkpoint.read_bytes(), audio.read_bytes()
    with pytest.raises(ModelWeightsError):
        predictor.predict(audio)
    assert (checkpoint.read_bytes(), audio.read_bytes()) == before
    assert predictor.metadata.loaded_checkpoint_sha256 is None
    assert predictor.metadata.target_sr == 8000
    checkpoint.write_bytes(original)
    result = predictor.predict(audio)
    expected = hashlib.sha256(original).hexdigest()
    assert result.detalles['status'] == 'classified'
    assert result.detalles['loaded_checkpoint_sha256'] == expected
    assert predictor.metadata.loaded_checkpoint_sha256 == expected
