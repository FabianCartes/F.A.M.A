import numpy as np
import pytest
import soundfile as sf
from poc.preprocess import (
    load_and_fix_length,
    extract_mel_spectrogram,
    compute_rms,
    extract_active_windows,
    TARGET_SR,
    DURATION_SECONDS,
    TARGET_SAMPLES,
)

def test_constants():
    assert TARGET_SR == 22050
    assert DURATION_SECONDS == 5.0
    assert TARGET_SAMPLES == 110250

def test_load_and_fix_length_from_synthetic_array_short():
    synthetic_audio = np.ones(44100, dtype=np.float32)
    processed = load_and_fix_length(synthetic_audio, target_sr=22050, duration_seconds=5.0, original_sr=22050)
    
    assert isinstance(processed, np.ndarray)
    assert processed.dtype == np.float32
    assert len(processed) == 110250
    assert np.allclose(processed[:44100], 1.0)
    assert np.allclose(processed[44100:], 0.0)

def test_load_and_fix_length_from_synthetic_array_long():
    synthetic_audio = np.linspace(0, 1, 176400, dtype=np.float32)
    processed = load_and_fix_length(synthetic_audio, target_sr=22050, duration_seconds=5.0, original_sr=22050)
    
    assert len(processed) == 110250

def test_load_and_fix_length_from_file(tmp_path):
    file_path = tmp_path / "test_audio.wav"
    sr_orig = 44100
    dur = 3.0
    t = np.linspace(0, dur, int(sr_orig * dur), endpoint=False)
    sig = 0.5 * np.sin(2 * np.pi * 440 * t)
    sf.write(str(file_path), sig, sr_orig)

    processed = load_and_fix_length(file_path, target_sr=22050, duration_seconds=5.0)
    assert len(processed) == 110250
    assert processed.dtype == np.float32

def test_extract_mel_spectrogram():
    waveform = np.random.randn(110250).astype(np.float32)
    mel_spec = extract_mel_spectrogram(waveform, sr=22050, n_mels=64, n_fft=1024, hop_length=512)
    
    assert isinstance(mel_spec, np.ndarray)
    assert mel_spec.shape[0] == 64
    assert mel_spec.ndim == 2
    assert not np.isnan(mel_spec).any()
    assert not np.isinf(mel_spec).any()

def test_compute_rms():
    silence = np.zeros(22050, dtype=np.float32)
    assert compute_rms(silence) == 0.0
    
    sine = np.sin(np.linspace(0, 2 * np.pi * 100, 22050, endpoint=False)).astype(np.float32)
    rms_val = compute_rms(sine)
    # Theoretical RMS of a unit sine wave is 1/sqrt(2) approx 0.707
    assert 0.70 <= rms_val <= 0.72

def test_extract_active_windows_multiple():
    # 10 seconds of active audio at 22050 Hz
    t = np.linspace(0, 10.0, int(22050 * 10.0), endpoint=False)
    sig = 0.5 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    
    # 5s window, 2.5s hop -> windows at [0..5s], [2.5..7.5s], [5..10s] = 3 windows
    windows = extract_active_windows(sig, target_sr=22050, duration_seconds=5.0, hop_seconds=2.5)
    
    assert len(windows) == 3
    for w in windows:
        assert len(w) == 110250
        assert w.dtype == np.float32

def test_extract_active_windows_vad_discards_silence():
    # 5 seconds active tone + 5 seconds pure silence
    t = np.linspace(0, 5.0, int(22050 * 5.0), endpoint=False)
    active = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    silence = np.zeros(int(22050 * 5.0), dtype=np.float32)
    combined = np.concatenate([active, silence])
    
    # hop=2.5s:
    # w0: [0..5s] -> active tone
    # w1: [2.5..7.5s] -> half tone, half silence
    # w2: [5..10s] -> pure silence
    windows = extract_active_windows(combined, target_sr=22050, duration_seconds=5.0, hop_seconds=2.5, top_db=25.0)
    
    # The last window (pure silence) must be discarded by VAD
    assert len(windows) < 3
    for w in windows:
        assert compute_rms(w) > 0.01

def test_extract_active_windows_safeguard():
    # Very faint noise across 10 seconds (RMS very low)
    faint_noise = (np.random.randn(int(22050 * 10.0)) * 1e-6).astype(np.float32)
    windows = extract_active_windows(faint_noise, target_sr=22050, duration_seconds=5.0, hop_seconds=2.5, top_db=25.0)
    
    # Safeguard should return at least 1 window (the highest energy one)
    assert len(windows) >= 1
    assert len(windows[0]) == 110250


def test_extract_active_windows_dense_hop():
    """Verifica que densidades de hop 1.25s y 1.0s generen la cantidad exacta de ventanas y desplazamientos."""
    sr = 22050
    audio_10s = np.arange(sr * 10, dtype=np.float32)

    # hop_seconds=1.25 genera 5 ventanas candidatas (desplazamientos 0.0, 1.25, 2.5, 3.75, 5.0 s)
    windows_125 = extract_active_windows(
        audio_10s, target_sr=sr, duration_seconds=5.0, hop_seconds=1.25, top_db=100.0
    )
    assert len(windows_125) == 5
    hop_samples_125 = int(sr * 1.25)
    for i, w in enumerate(windows_125):
        assert len(w) == int(sr * 5.0)
        assert w[0] == float(i * hop_samples_125)

    # hop_seconds=1.0 genera 6 ventanas candidatas (desplazamientos 0.0, 1.0, 2.0, 3.0, 4.0, 5.0 s)
    windows_100 = extract_active_windows(
        audio_10s, target_sr=sr, duration_seconds=5.0, hop_seconds=1.0, top_db=100.0
    )
    assert len(windows_100) == 6
    hop_samples_100 = int(sr * 1.0)
    for i, w in enumerate(windows_100):
        assert len(w) == int(sr * 5.0)
        assert w[0] == float(i * hop_samples_100)


def test_extract_active_windows_invalid_hop():
    """Verifica que hop_seconds <= 0 lance ValueError."""
    sr = 22050
    audio = np.ones(sr * 5, dtype=np.float32)
    with pytest.raises(ValueError, match="hop_seconds debe ser mayor a 0"):
        extract_active_windows(audio, target_sr=sr, hop_seconds=0.0)
    with pytest.raises(ValueError, match="hop_seconds debe ser mayor a 0"):
        extract_active_windows(audio, target_sr=sr, hop_seconds=-1.0)


def test_gpu_audio_frontend():
    import torch
    from poc.preprocess import GPUAudioFrontEnd

    frontend = GPUAudioFrontEnd(n_mels=128, f_min=800.0, f_max=10000.0)
    # Batch de 2 audios de 5 segundos a 22050 Hz
    x = torch.randn(2, 110250)
    mel = frontend(x)

    assert isinstance(mel, torch.Tensor)
    assert mel.shape[0] == 2
    assert mel.shape[1] == 1  # 1 channel
    assert mel.shape[2] == 128  # 128 mel bins
    assert mel.ndim == 4  # [B, 1, 128, T]
    assert not torch.isnan(mel).any()
    assert not torch.isinf(mel).any()


def test_gpu_audio_frontend_normalization():
    import torch
    from poc.preprocess import GPUAudioFrontEnd

    frontend = GPUAudioFrontEnd(n_mels=128, normalize=True)
    x = torch.randn(2, 110250)
    mel = frontend(x)

    for b in range(2):
        instance = mel[b, 0]
        assert torch.isclose(instance.mean(), torch.tensor(0.0), atol=1e-2)
        assert torch.isclose(instance.std(), torch.tensor(1.0), atol=1e-2)

    frontend_raw = GPUAudioFrontEnd(n_mels=128, normalize=False)
    mel_raw = frontend_raw(x)
    assert not torch.isclose(mel_raw.mean(), torch.tensor(0.0), atol=1.0)


def test_gpu_spec_augment():
    import torch
    from poc.preprocess import GPUSpecAugment

    spec_aug = GPUSpecAugment(freq_mask_param=8, time_mask_param=16, prob=1.0)
    spec_aug.train()
    x = torch.ones(2, 1, 128, 216)
    out = spec_aug(x)

    assert out.shape == x.shape
    assert out.sum() < x.sum()

    # In eval mode, must not apply any masking
    spec_aug.eval()
    out_eval = spec_aug(x)
    assert torch.equal(out_eval, x)


def test_gpu_spec_augment_pitch_shift_properties():
    """Verifica que Spectral Pitch Shift conserve forma, sea determinista en eval, desplace energía y preserve gradientes."""
    import torch
    from poc.preprocess import GPUSpecAugment

    spec_aug = GPUSpecAugment(
        freq_mask_param=0,
        time_mask_param=0,
        prob=1.0,
        pitch_shift_max_bins=2,
        pitch_shift_prob=1.0,
    )

    B, C, F, T_dim = 2, 1, 128, 216
    x = torch.zeros(B, C, F, T_dim, requires_grad=True)
    # Impulso espectral en bin 50
    x.data[:, :, 50, :] = 10.0

    spec_aug.train()
    out = spec_aug(x)

    # Conserva forma [B, 1, 128, 216]
    assert out.shape == (B, C, F, T_dim)

    # Desplaza la energía espectral hacia arriba o abajo
    for b in range(B):
        peak_bin = int(torch.argmax(out[b, 0, :, 0]).item())
        assert peak_bin in (48, 49, 51, 52), f"Pico esperado en 48, 49, 51 o 52, pero fue {peak_bin}"
        assert peak_bin != 50

    # Gradientes finitos y válidos en .backward()
    loss = out.sum()
    loss.backward()
    assert x.grad is not None
    assert torch.isfinite(x.grad).all()

    # En modo eval, el tensor de salida debe ser idéntico al de entrada (determinismo)
    spec_aug.eval()
    x_eval = torch.randn(B, C, F, T_dim)
    out_eval = spec_aug(x_eval)
    assert torch.equal(out_eval, x_eval)


def test_gpu_spec_augment_pitch_shift_disabled():
    """Verifica que con bins=0 o prob=0 no se aplique desplazamiento tonal."""
    import torch
    from poc.preprocess import GPUSpecAugment

    spec_aug = GPUSpecAugment(
        freq_mask_param=0,
        time_mask_param=0,
        prob=0.0,
        pitch_shift_max_bins=0,
        pitch_shift_prob=0.0,
    )
    spec_aug.train()
    x = torch.randn(2, 1, 128, 216)
    out = spec_aug(x)
    assert torch.equal(out, x)





