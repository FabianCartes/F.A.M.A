"""
backend/tests/test_additive_mixing.py
Pruebas de TDD para la síntesis aditiva física de fallas mecánicas compuestas en formas de onda de audio.
"""
import pytest
import numpy as np
import pandas as pd

from training.pipelines.additive_mixing import (
    COMPOSITE_RECIPES,
    mix_additive_waveforms,
    AdditiveCompoundSampler,
)


def test_composite_recipes_definition():
    # Debe definir la descomposición física de las 4 clases compuestas del dataset
    assert "no oil_serpentine belt" in COMPOSITE_RECIPES
    assert COMPOSITE_RECIPES["no oil_serpentine belt"] == ["low_oil", "serpentine_belt"]
    assert COMPOSITE_RECIPES["power steering combined_serpentine belt"] == ["power_steering", "serpentine_belt"]
    assert COMPOSITE_RECIPES["power steering combined_no oil"] == ["power_steering", "low_oil"]
    assert len(COMPOSITE_RECIPES["power steering combined_no oil_serpentine belt"]) == 3


def test_mix_additive_waveforms_linearity_and_clipping_prevention():
    n_samples = 32000
    # Dos tonos sintéticos de amplitud 0.8
    t = np.linspace(0, 1.0, n_samples, dtype=np.float32)
    w1 = 0.8 * np.sin(2 * np.pi * 400 * t)
    w2 = 0.8 * np.sin(2 * np.pi * 2000 * t)

    # Suma directa superaría 1.0 (clipping a 1.6)
    mixed = mix_additive_waveforms([w1, w2], gains=[1.0, 1.0])

    assert len(mixed) == n_samples
    assert mixed.dtype == np.float32
    # Debe evitar el recorte digital manteniendo el pico <= 0.98
    assert np.max(np.abs(mixed)) <= 0.98
    # Debe contener energía de ambas frecuencias (no ser todo ceros)
    assert np.std(mixed) > 0.1


def test_mix_additive_waveforms_with_time_shift():
    n_samples = 1000
    w1 = np.ones(n_samples, dtype=np.float32)
    w2 = np.ones(n_samples, dtype=np.float32)

    mixed = mix_additive_waveforms([w1, w2], max_shift_samples=100)
    assert len(mixed) == n_samples


def test_additive_compound_sampler_builds_synthetic_waveform(tmp_path):
    import soundfile as sf

    # Crear audios dummy unitarios en disco
    oil_dir = tmp_path / "low_oil"
    oil_dir.mkdir()
    oil_wav = oil_dir / "oil_01.wav"
    sf.write(oil_wav, np.random.randn(32000).astype(np.float32) * 0.1, 32000)

    belt_dir = tmp_path / "serpentine_belt"
    belt_dir.mkdir()
    belt_wav = belt_dir / "belt_01.wav"
    sf.write(belt_wav, np.random.randn(32000).astype(np.float32) * 0.1, 32000)

    df = pd.DataFrame([
        {"file_path": str(oil_wav), "clase": "low_oil"},
        {"file_path": str(belt_wav), "clase": "serpentine_belt"},
    ])

    sampler = AdditiveCompoundSampler(df, target_sr=32000, duration_seconds=1.0)
    # Debe poder sintetizar la clase compuesta 'no oil_serpentine belt'
    assert sampler.can_synthesize("no oil_serpentine belt") is True
    assert sampler.can_synthesize("normal_engine_idle") is False

    synth_wave = sampler.sample_synthetic_compound("no oil_serpentine belt")
    assert synth_wave is not None
    assert len(synth_wave) == 32000


def test_build_balanced_class_sampler():
    from training.pipelines.additive_mixing import build_balanced_class_sampler
    import torch

    df = pd.DataFrame({
        "file_path": ["a.wav"] * 10 + ["b.wav"] * 2,
        "clase": ["frequent"] * 10 + ["rare"] * 2,
    })

    sampler = build_balanced_class_sampler(df, class_col="clase")
    assert isinstance(sampler, torch.utils.data.WeightedRandomSampler)
    assert len(sampler) == len(df)
    # Los pesos de la clase rara deben ser 5 veces mayores que los de la frecuente
    weights = list(sampler.weights)
    assert weights[10].item() == pytest.approx(5.0 * weights[0].item(), rel=1e-3)


def test_mix_additive_waveforms_balances_rms_power():
    # Simulamos dos señales con una disparidad energética severa de 50x (ej. low_oil vs power_steering)
    n = 16000
    t = np.linspace(0, 1.0, n, dtype=np.float32)
    w_loud = 0.5 * np.sin(2 * np.pi * 100 * t)   # RMS ~ 0.353
    w_quiet = 0.01 * np.sin(2 * np.pi * 800 * t) # RMS ~ 0.007 (50 veces menor)

    mixed = mix_additive_waveforms([w_loud, w_quiet], gains=[1.0, 1.0], balance_rms=True)

    assert len(mixed) == n
    # En el espectro, la señal débil (800 Hz) no debe haber sido ahogada por la señal fuerte (100 Hz)
    fft_mag = np.abs(np.fft.rfft(mixed))
    freqs = np.fft.rfftfreq(n, d=1.0/n)
    idx_100 = int(np.argmin(np.abs(freqs - 100)))
    idx_800 = int(np.argmin(np.abs(freqs - 800)))

    ratio = fft_mag[idx_100] / max(1e-6, fft_mag[idx_800])
    # Sin balanceo, el ratio sería ~50. Con balanceo RMS, el ratio debe estar cerca de 1.0 (< 3.0)
    assert ratio < 3.0

