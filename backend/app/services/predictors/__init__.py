"""
Módulo de estrategias de predicción bioacústica.
"""
from app.services.predictors.base import AudioPredictor
from app.services.predictors.cnn_predictor import AudioCNNPredictor
from app.services.predictors.ensemble_predictor import ChileanBirdsEnsemblePredictor
from app.services.predictors.bundle_predictor import BundleAudioPredictor

__all__ = [
    "AudioPredictor",
    "AudioCNNPredictor",
    "ChileanBirdsEnsemblePredictor",
    "BundleAudioPredictor",
]
