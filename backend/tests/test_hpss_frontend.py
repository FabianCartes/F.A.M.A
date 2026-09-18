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
