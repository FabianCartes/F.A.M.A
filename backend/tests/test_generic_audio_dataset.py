import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
import soundfile as sf
import torch
import pytest

from training.schemas.config import AudioConfig, AugmentationConfig
from training.pipelines.dataset import GenericAudioDataset, load_and_resample


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
            {"nombre_archivo": "aud1.wav", "file_path": f1.name, "file_stage": "raw", "clase": "sp_a", "labels": ["sp_a"], "recordist": "rec1"},
            {"nombre_archivo": "aud2.wav", "file_path": f2.name, "file_stage": "raw", "clase": "sp_b", "labels": ["sp_a", "sp_b"], "recordist": "rec2"},
        ])
        yield df, {"raw": root}


def test_dataset_respects_custom_sample_rate_and_duration(dummy_audio_df):
    audio_cfg = AudioConfig(target_sr=32000, duration_seconds=3.0)
    label_to_idx = {"sp_a": 0, "sp_b": 1}

    ds = GenericAudioDataset(
        df=dummy_audio_df[0],
        roots=dummy_audio_df[1],
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
        df=dummy_audio_df[0],
        roots=dummy_audio_df[1],
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
        df=dummy_audio_df[0],
        roots=dummy_audio_df[1],
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


@pytest.mark.parametrize("stage,level", [("raw", 0.25), ("processed", -0.5)])
def test_dataset_uses_declared_physical_stage_not_extension_or_cwd(tmp_path, monkeypatch, stage, level):
    roots = {name: tmp_path / name for name in ("raw", "processed")}
    for name, root in roots.items():
        root.mkdir()
        sf.write(root / "001.wav", np.full(8000, 0.25 if name == "raw" else -0.5), 8000)
    sf.write(tmp_path / "001.wav", np.zeros(8000), 8000)
    monkeypatch.chdir(tmp_path)
    frame = pd.DataFrame([{"file_path": "001.wav", "file_stage": stage, "clase": "normal"}])
    dataset = GenericAudioDataset(frame, AudioConfig(target_sr=8000, duration_seconds=1.0),
                                  {"normal": 0}, roots=roots, is_train=False)
    waveform, label = dataset[0]
    assert torch.allclose(waveform, torch.full((8000,), level))
    assert label.item() == 0
    pd.testing.assert_frame_equal(dataset.df, frame)


@pytest.mark.parametrize("missing", ["file_stage", "file_path"])
def test_dataset_rejects_legacy_index_without_enrolling_audio(tmp_path, missing):
    sf.write(tmp_path / "001.wav", np.zeros(8000), 8000)
    frame = pd.DataFrame([{"file_path": "001.wav", "file_stage": "raw", "clase": "normal"}])
    with pytest.raises(ValueError, match="file_path and file_stage"):
        GenericAudioDataset(frame.drop(columns=missing), AudioConfig(), {"normal": 0},
                            roots={"raw": tmp_path})


def test_dataset_requires_explicit_roots(dummy_audio_df):
    with pytest.raises(TypeError, match="roots"):
        GenericAudioDataset(dummy_audio_df[0], AudioConfig(), {"sp_a": 0, "sp_b": 1})


def test_dataset_revalidates_reference_before_audio_decode(tmp_path):
    path = tmp_path / "001.wav"
    sf.write(path, np.zeros(8000), 8000)
    frame = pd.DataFrame([{"file_path": path.name, "file_stage": "raw", "clase": "normal"}])
    dataset = GenericAudioDataset(frame, AudioConfig(), {"normal": 0}, roots={"raw": tmp_path})
    replacement = tmp_path / "other.wav"
    sf.write(replacement, np.ones(8000), 8000)
    # Replace only the temporary fixture with an alias after constructor validation.
    path.rename(tmp_path / "original.wav")
    path.symlink_to(replacement)
    with pytest.raises(ValueError, match="symlink"):
        dataset[0]


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


def test_strict_loader_rejects_corrupt_audio_with_decode_cause(tmp_path):
    from training.pipelines.dataset import MalformedAudioError

    path = tmp_path / "corrupt.wav"
    path.write_bytes(b"not an audio file")
    with pytest.raises(MalformedAudioError) as caught:
        load_and_resample(path, 16000, 1.0, strict=True)
    assert isinstance(caught.value.__cause__, sf.LibsndfileError)
    assert caught.value.__cause__.code == 1


@pytest.mark.parametrize("code", [1, 3, 4])
def test_strict_loader_classifies_only_format_errors(tmp_path, monkeypatch, code):
    from training.pipelines.dataset import MalformedAudioError

    error = sf.LibsndfileError(code)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("librosa.load", fail)
    with pytest.raises(MalformedAudioError) as caught:
        load_and_resample(tmp_path / "input.wav", 16000, 1.0, strict=True)
    assert caught.value.__cause__ is error


@pytest.mark.parametrize("error", [
    PermissionError("denied"), FileNotFoundError("missing"),
    RuntimeError("decoder failed"), ValueError("internal failure"),
    OSError("I/O failure"), sf.LibsndfileError(2), sf.LibsndfileError(0),
])
def test_strict_loader_preserves_non_format_errors(tmp_path, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("librosa.load", fail)
    with pytest.raises(type(error)) as caught:
        load_and_resample(tmp_path / "input.wav", 16000, 1.0, strict=True)
    assert caught.value is error


def test_strict_loader_preserves_real_silence(tmp_path):
    path = tmp_path / "silence.wav"
    sf.write(path, np.zeros(8000), 8000)
    waveform = load_and_resample(path, 16000, 1.0, strict=True)
    assert waveform.shape == (16000,)
    assert waveform.dtype == np.float32
    assert not waveform.any()


def test_corrupt_audio_remains_tolerant_for_training_and_additive_mixing(tmp_path):
    from training.pipelines.additive_mixing import AdditiveCompoundSampler

    path = tmp_path / "corrupt.wav"
    path.write_bytes(b"not audio")
    waveform = load_and_resample(path, 16000, 1.0)
    assert waveform.shape == (16000,)
    assert waveform.dtype == np.float32
    assert not waveform.any()
    df = pd.DataFrame([
        {"file_path": str(path), "clase": "low_oil"},
        {"file_path": str(path), "clase": "serpentine_belt"},
    ])
    canonical_df = df.assign(file_path=path.name, file_stage="raw")
    dataset = GenericAudioDataset(canonical_df, AudioConfig(target_sr=16000, duration_seconds=1.0),
                                  {"low_oil": 0, "serpentine_belt": 1}, roots={"raw": tmp_path})
    wave_tensor, label = dataset[0]
    assert wave_tensor.shape == (16000,)
    assert not wave_tensor.any()
    assert label.item() == 0
    sampler = AdditiveCompoundSampler(canonical_df, roots={"raw": tmp_path}, target_sr=16000, duration_seconds=1.0)
    mixed = sampler.sample_synthetic_compound("no oil_serpentine belt")
    assert mixed.shape == (16000,)
    assert not mixed.any()


def test_dataset_with_additive_compound_sampler(tmp_path):
    from training.pipelines.additive_mixing import AdditiveCompoundSampler
    import soundfile as sf

    sr = 32000
    oil_wav = tmp_path / "oil.wav"
    belt_wav = tmp_path / "belt.wav"
    sf.write(oil_wav, np.random.randn(sr).astype(np.float32) * 0.1, sr)
    sf.write(belt_wav, np.random.randn(sr).astype(np.float32) * 0.1, sr)

    df = pd.DataFrame([
        {"file_path": str(oil_wav), "clase": "low_oil"},
        {"file_path": str(belt_wav), "clase": "serpentine_belt"},
        {"file_path": str(oil_wav), "clase": "no oil_serpentine belt"},
    ])

    canonical_df = df.assign(file_path=[oil_wav.name, belt_wav.name, oil_wav.name], file_stage="raw")
    sampler = AdditiveCompoundSampler(canonical_df, roots={"raw": tmp_path}, target_sr=sr, duration_seconds=1.0)
    audio_cfg = AudioConfig(target_sr=sr, duration_seconds=1.0)
    label_to_idx = {"low_oil": 0, "serpentine_belt": 1, "no oil_serpentine belt": 2}

    # Both readers consume the same portable index and declared root.
    ds = GenericAudioDataset(
        df=canonical_df,
        roots={"raw": tmp_path},
        audio_config=audio_cfg,
        label_to_idx=label_to_idx,
        is_train=True,
        additive_sampler=sampler,
        synth_prob=1.0,
    )

    # El índice 2 es la clase compuesta 'no oil_serpentine belt'
    waveform, label = ds[2]
    assert len(waveform) == sr
    assert label.item() == 2


