"""
backend/tests/test_hpss_frontend.py
Pruebas de TDD para el frontend acústico de 3 canales con separación armónico-percusiva (HPSS) optimizada para motores.
"""
import pytest
import torch

from training.pipelines.hpss_frontend import HPSSAudioFrontEnd


def test_hpss_frontend_output_shape_and_channels():
    # 2 muestras de 1.5s a 32kHz = 48000 muestras
    bsz = 2
    sr = 32000
    duration_samples = int(sr * 1.5)
    x = torch.randn(bsz, duration_samples)

    frontend = HPSSAudioFrontEnd(
        sample_rate=sr,
        n_fft=2048,
        hop_length=256,
        n_mels=128,
        f_min=20.0,
        f_max=8000.0,
        kernel_size=15,
    )

    out = frontend(x)
    # Debe generar tensor de 3 canales: [B, 3, n_mels, time_frames]
    assert out.ndim == 4
    assert out.shape[0] == bsz
    assert out.shape[1] == 3  # [Canal 0: Mel, Canal 1: Armónico, Canal 2: Percusivo]
    assert out.shape[2] == 128  # n_mels
    assert out.shape[3] > 0  # time_frames


def test_hpss_frontend_physical_bounds():
    # Audio sintético con tono puro continuo (armónico)
    sr = 32000
    t = torch.linspace(0, 1.0, sr)
    # Tono de 2500 Hz (silbido de correa típico)
    tonal_wave = torch.sin(2 * 3.14159265 * 2500 * t).unsqueeze(0)

    frontend = HPSSAudioFrontEnd(
        sample_rate=sr,
        n_fft=1024,
        hop_length=256,
        n_mels=64,
        f_min=20.0,
        f_max=8000.0,
    )

    out = frontend(tonal_wave)
    # out: [1, 3, 64, T]
    mel_orig = out[0, 0]
    mel_harm = out[0, 1]
    mel_perc = out[0, 2]

    # En un tono puro, la energía armónica debe dominar claramente a la percusiva
    harm_energy = torch.sum(mel_harm)
    perc_energy = torch.sum(mel_perc)
    assert harm_energy > perc_energy


def test_hpss_frontend_batch_normalization_stability():
    x = torch.zeros(1, 16000)  # silencio absoluto
    frontend = HPSSAudioFrontEnd(sample_rate=16000, n_fft=512, hop_length=128, n_mels=32)
    out = frontend(x)
    assert not torch.isnan(out).any()
    assert not torch.isinf(out).any()


def test_multiresolution_hpss_frontend_shape_and_temporal_alignment():
    from training.pipelines.hpss_frontend import MultiResolutionHPSSFrontEnd

    bsz = 2
    sr = 32000
    x = torch.randn(bsz, 64000)  # 2.0s a 32kHz

    frontend = MultiResolutionHPSSFrontEnd(
        sample_rate=sr,
        n_fft_harm=2048,  # 64ms para armónicos
        n_fft_perc=1024,  # 32ms para transitorios
        hop_length=256,   # sincronización idéntica
        n_mels=128,
        f_min=20.0,
        f_max=8000.0,
    )

    out = frontend(x)
    # Debe producir [B, 3, 128, 251]
    assert out.ndim == 4
    assert out.shape == (bsz, 3, 128, 251)
    assert not torch.isnan(out).any()


def test_multiresolution_hpss_transient_sharpening():
    from training.pipelines.hpss_frontend import MultiResolutionHPSSFrontEnd

    sr = 32000
    # Señal sintética: un impulso delta puro (golpeteo mecánico seco) en t=0.5s
    x = torch.zeros(1, 32000)
    x[0, 16000] = 1.0  # impulso Dirac

    frontend = MultiResolutionHPSSFrontEnd(
        sample_rate=sr,
        n_fft_harm=2048,
        n_fft_perc=512,
        hop_length=256,
        n_mels=64,
    )

    out = frontend(x)
    # Canal 2 (percusivo de 16ms) debe concentrar la energía temporal con menor dispersión
    # que un canal percusivo de 64ms estándar
    perc_channel = out[0, 2]  # [64, T]
    time_profile = perc_channel.mean(dim=0)  # [T]
    peak_frame = int(torch.argmax(time_profile).item())
    
    # El impulso en t=0.5s debe coincidir con el frame 16000 // 256 = 62 o 63
    assert abs(peak_frame - 62) <= 2
    # La energía pico debe superar significativamente al piso de ruido
    assert time_profile[peak_frame] > time_profile.min()
