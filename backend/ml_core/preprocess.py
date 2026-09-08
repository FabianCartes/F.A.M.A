"""
Módulo de preprocesamiento de audio y espectrogramas para F.A.M.A.
Re-exporta las abstracciones de poc.preprocess.
"""
from poc.preprocess import (
    GPUAudioFrontEnd,
    GPUSpecAugment,
    GeM,
    load_and_fix_length,
    extract_mel_spectrogram,
    compute_rms,
    extract_active_windows,
    TARGET_SR,
    DURATION_SECONDS,
)

__all__ = [
    "GPUAudioFrontEnd",
    "GPUSpecAugment",
    "GeM",
    "load_and_fix_length",
    "extract_mel_spectrogram",
    "compute_rms",
    "extract_active_windows",
    "TARGET_SR",
    "DURATION_SECONDS",
]
