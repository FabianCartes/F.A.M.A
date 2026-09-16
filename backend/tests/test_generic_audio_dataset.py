import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
import soundfile as sf
import torch
import pytest

from training.schemas.config import AudioConfig, AugmentationConfig
from training.pipelines.dataset import GenericAudioDataset


@pytest.fixture
def dummy_audio_df():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        sr = 44100  # Archivo original a 44.1 kHz
        data = np.random.randn(sr * 4).astype(np.float32) * 0.1

        f1 = root / "aud1.wav"
        f2 = root / "aud2.wav"
        sf.write(f1, data, sr)
        sf.write(f2, data, sr)

        df = pd.DataFrame([
            {"nombre_archivo": "aud1.wav", "file_path": str(f1), "clase": "sp_a", "labels": ["sp_a"], "recordist": "rec1"},
            {"nombre_archivo": "aud2.wav", "file_path": str(f2), "clase": "sp_b", "labels": ["sp_a", "sp_b"], "recordist": "rec2"},
        ])
        yield df


def test_dataset_respects_custom_sample_rate_and_duration(dummy_audio_df):
    audio_cfg = AudioConfig(target_sr=32000, duration_seconds=3.0)
    label_to_idx = {"sp_a": 0, "sp_b": 1}

    ds = GenericAudioDataset(
        df=dummy_audio_df,
        audio_config=audio_cfg,
        label_to_idx=label_to_idx,
        is_train=False,
        return_raw_waveform=True,
    )

    waveform, label = ds[0]
    # Comprobar que target_samples sea 32000 * 3.0 = 96000
    assert waveform.shape == (96000,)
    assert isinstance(waveform, torch.Tensor)
    assert waveform.dtype == torch.float32
    assert label.item() == 0


def test_dataset_deterministic_when_eval(dummy_audio_df):
    audio_cfg = AudioConfig(target_sr=22050, duration_seconds=2.0)
    label_to_idx = {"sp_a": 0, "sp_b": 1}

    ds = GenericAudioDataset(
        df=dummy_audio_df,
        audio_config=audio_cfg,
        label_to_idx=label_to_idx,
        is_train=False,
        return_raw_waveform=True,
    )

    w1, _ = ds[0]
    w2, _ = ds[0]
    # En modo eval (is_train=False) debe ser 100% determinista
    assert torch.equal(w1, w2)


def test_dataset_multilabel_tensor_vector(dummy_audio_df):
    audio_cfg = AudioConfig(target_sr=22050, duration_seconds=2.0)
    label_to_idx = {"sp_a": 0, "sp_b": 1}

    ds = GenericAudioDataset(
        df=dummy_audio_df,
        audio_config=audio_cfg,
        label_to_idx=label_to_idx,
        is_train=False,
        multilabel=True,
        return_raw_waveform=True,
    )

    _, l0 = ds[0]  # labels: ['sp_a'] -> [1.0, 0.0]
    assert l0.shape == (2,)
    assert l0.dtype == torch.float32
    assert torch.equal(l0, torch.tensor([1.0, 0.0]))

    _, l1 = ds[1]  # labels: ['sp_a', 'sp_b'] -> [1.0, 1.0]
    assert torch.equal(l1, torch.tensor([1.0, 1.0]))


def test_load_and_resample_selects_highest_energy_window(tmp_path):
    from training.pipelines.dataset import load_and_resample

    sr = 16000
    duration = 3.0
    target_samples = int(sr * duration)

    # 6 segundos totales: primeros 3s silencio, siguientes 3s señal fuerte
    silence = np.zeros(target_samples, dtype=np.float32)
    loud_signal = (np.sin(2 * np.pi * 440 * np.linspace(0, 3, target_samples))).astype(np.float32) * 0.8
    full_audio = np.concatenate([silence, loud_signal])

    wav_file = tmp_path / "energy_test.wav"
    sf.write(wav_file, full_audio, sr)

    # Cargar pidiendo 3.0 segundos
    result = load_and_resample(wav_file, target_sr=sr, duration_seconds=duration)
    assert len(result) == target_samples

    rms = np.sqrt(np.mean(result ** 2))
    # El RMS de la señal fuerte de seno con amplitud 0.8 es ~0.56. Si seleccionó silencio, RMS es 0.0.
    assert rms > 0.3

