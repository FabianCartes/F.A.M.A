"""
Módulo de arquitecturas y entrenamiento profundo para F.A.M.A.
Re-exporta las abstracciones de poc.train.
"""
from poc.train import (
    BioacousticModel,
    AudioCNN,
    FocalLoss,
    apply_mixup,
    train_pipeline,
)

__all__ = [
    "BioacousticModel",
    "AudioCNN",
    "FocalLoss",
    "apply_mixup",
    "train_pipeline",
]
