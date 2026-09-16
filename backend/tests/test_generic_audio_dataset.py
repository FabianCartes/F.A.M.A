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
