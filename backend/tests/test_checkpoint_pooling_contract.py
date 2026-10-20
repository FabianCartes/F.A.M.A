"""Pooling declared by checkpoints, tested through public prediction only."""
import numpy as np
import pytest
import soundfile as sf
import timm
import torch

from app.services.predictors.trained_predictor import TrainedModelPredictor, ModelWeightsError
from poc.train import AudioCNN, BioacousticModel
from poc.preprocess import load_and_fix_length, extract_mel_spectrogram


class PooledClassifier(torch.nn.Module):
    """External network adapter with different average/GeM predictions."""
    def __init__(self):
        super().__init__()
        self.global_pool = torch.nn.AdaptiveAvgPool2d(1)
        self.classifier = torch.nn.Linear(1, 2, bias=False)
        with torch.no_grad():
            self.classifier.weight.copy_(torch.tensor([[1.0], [-1.0]]))

    def forward(self, value):
        return self.classifier(self.global_pool(value).flatten(1))


@pytest.mark.parametrize("lazy_load", [False, True])
def test_explicit_average_pooling_checkpoint_predicts_without_inventing_gem_parameter(tmp_path, monkeypatch, lazy_load):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("efficientnet_b0", num_classes=2, pretrained=False, pool_type="avg")
    checkpoint = tmp_path / "synthetic-average.pt"
    torch.save({"architecture": "EfficientNet-B0", "pool_type": "avg", "classes": ["Positive", "Negative"],
                "model_state_dict": model.state_dict()}, checkpoint)
    audio = tmp_path / "tone.wav"
    waveform = 0.3 * np.sin(2 * np.pi * 440 * np.arange(16000, dtype=np.float32) / 8000)
    sf.write(audio, waveform, 8000)

    predictor = TrainedModelPredictor(checkpoint, lazy_load=lazy_load)
    result = predictor.predict(audio)

    assert result.clase == "Negative"
    assert result.confianza > 0.99
    assert result.detalles["status"] == "classified"


def test_unknown_pooling_is_not_silently_treated_as_average(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("efficientnet_b0", num_classes=2, pretrained=False, pool_type="avg")
    checkpoint = tmp_path / "unknown-pooling.pt"
    torch.save({"architecture": "EfficientNet-B0", "pool_type": "unsupported", "classes": ["Positive", "Negative"],
                "model_state_dict": model.state_dict()}, checkpoint)

    with pytest.raises(ModelWeightsError, match="pooling"):
        TrainedModelPredictor(checkpoint)


@pytest.mark.parametrize("metadata,producer_pool,expected_label", [
    ({"pool_type": "gem"}, "gem", "Positive"),
    ({}, "gem", "Positive"),
    ({"pool_type": None}, "avg", "Negative"),
], ids=["explicit-gem", "unchanged-default", "explicit-null-average"])
def test_supported_pooling_and_existing_default_keep_their_behavior(tmp_path, monkeypatch, metadata, producer_pool, expected_label):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("efficientnet_b0", num_classes=2, pretrained=False, pool_type=producer_pool)
    checkpoint = tmp_path / "synthetic-supported.pt"
    torch.save({"architecture": "EfficientNet-B0", "classes": ["Positive", "Negative"],
                "model_state_dict": model.state_dict(), **metadata}, checkpoint)
    audio = tmp_path / "tone.wav"
    sf.write(audio, 0.3 * np.sin(2 * np.pi * 440 * np.arange(16000, dtype=np.float32) / 8000), 8000)

    result = TrainedModelPredictor(checkpoint).predict(audio)

    assert result.clase == expected_label
    assert result.detalles["status"] == "classified"


def test_pooling_declaration_cannot_bypass_strict_weight_compatibility(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    gem = BioacousticModel("efficientnet_b0", num_classes=2, pretrained=False, pool_type="gem")
    checkpoint = tmp_path / "mismatched-pooling.pt"
    torch.save({"architecture": "EfficientNet-B0", "pool_type": "avg", "classes": ["Positive", "Negative"],
                "model_state_dict": gem.state_dict()}, checkpoint)

    with pytest.raises(ModelWeightsError, match="Incompatibilidad"):
        TrainedModelPredictor(checkpoint)


def test_poc_model_type_format_uses_its_existing_average_pooling_default(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("efficientnet_b0", num_classes=2, pretrained=False, pool_type="avg")
    checkpoint = tmp_path / "legacy-poc.pt"
    torch.save({"model_type": "efficientnet_b0", "classes": ["Positive", "Negative"],
                "model_state_dict": model.state_dict()}, checkpoint)
    audio = tmp_path / "tone.wav"
    sf.write(audio, 0.3 * np.sin(2 * np.pi * 440 * np.arange(16000, dtype=np.float32) / 8000), 8000)

    result = TrainedModelPredictor(checkpoint).predict(audio)

    assert result.clase == "Negative"
    assert result.confianza > 0.99


class FirstBandsClassifier(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("scale", torch.tensor(0.01))

    def forward(self, value):
        score = value[:, :, :8, :].mean(dim=(1, 2, 3)) * self.scale
        return torch.stack((score, -score), dim=1)


def test_declared_legacy_mel_bands_are_used_instead_of_fixed_64(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: FirstBandsClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False, pool_type="avg").eval()
    checkpoint = tmp_path / "legacy-bands.pt"
    torch.save({"model_type": "fixture", "n_mels": 128, "classes": ["Positive", "Negative"],
                "model_state_dict": model.state_dict()}, checkpoint)
    audio = tmp_path / "tone.wav"
    sf.write(audio, 0.3 * np.sin(2 * np.pi * 440 * np.arange(16000, dtype=np.float32) / 8000), 8000)
    waveform = load_and_fix_length(audio)
    with torch.no_grad():
        declared = torch.from_numpy(extract_mel_spectrogram(waveform, n_mels=128))[None, None]
        old_default = torch.from_numpy(extract_mel_spectrogram(waveform, n_mels=64))[None, None]
        expected = torch.softmax(model(declared), dim=1).max().item()
        wrong = torch.softmax(model(old_default), dim=1).max().item()
    assert abs(expected - wrong) > 0.001

    result = TrainedModelPredictor(checkpoint).predict(audio)

    assert result.confianza == pytest.approx(round(expected, 4), abs=1e-4)
    assert result.detalles["mel_bands"] == 128


@pytest.mark.parametrize("n_mels", [0, True, "128", 257])
def test_invalid_declared_legacy_bands_are_rejected_not_replaced(tmp_path, monkeypatch, n_mels):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    checkpoint = tmp_path / "invalid-bands.pt"
    torch.save({"model_type": "cnn", "n_mels": n_mels, "classes": ["Positive", "Negative"],
                "model_state_dict": AudioCNN(num_classes=2).state_dict()}, checkpoint)

    with pytest.raises(ModelWeightsError, match="n_mels"):
        TrainedModelPredictor(checkpoint, lazy_load=True)


def test_poc_cnn_alias_loads_the_recorded_audio_cnn_not_an_effnet(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    def no_timm(*args, **kwargs):
        raise AssertionError("Legacy CNN must not construct a timm backbone")

    monkeypatch.setattr(timm, "create_model", no_timm)
    checkpoint = tmp_path / "legacy-cnn.pt"
    torch.save({"model_type": "cnn", "classes": ["Positive", "Negative"],
                "model_state_dict": AudioCNN(num_classes=2).state_dict()}, checkpoint)
    audio = tmp_path / "tone.wav"
    sf.write(audio, 0.3 * np.sin(2 * np.pi * 440 * np.arange(16000, dtype=np.float32) / 8000), 8000)

    predictor = TrainedModelPredictor(checkpoint, lazy_load=True)
    result = predictor.predict(audio)

    assert "cnn" in predictor.metadata.name
    assert result.detalles["status"] == "classified"
