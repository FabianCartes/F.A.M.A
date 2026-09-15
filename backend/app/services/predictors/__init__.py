"""
Módulo de estrategias de predicción bioacústica.
"""
from app.services.predictors.base import AudioPredictor
from app.services.predictors.cnn_predictor import AudioCNNPredictor
from app.services.predictors.ensemble_predictor import ChileanBirdsEnsemblePredictor

__all__ = [
    "AudioPredictor",
    "AudioCNNPredictor",
    "ChileanBirdsEnsemblePredictor",
]
