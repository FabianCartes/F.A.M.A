"""
Módulo de evaluación e inferencia bioacústica para F.A.M.A.
Re-exporta las abstracciones de poc.evaluate para acceso modular limpio desde ml_core.
"""
from poc.evaluate import (
    EnsembleClassifier,
    predict_audio_tta,
    load_checkpoint_model,
    compute_metrics_and_matrix,
    evaluate_test_set,
    run_evaluation,
)

__all__ = [
    "EnsembleClassifier",
    "predict_audio_tta",
    "load_checkpoint_model",
    "compute_metrics_and_matrix",
    "evaluate_test_set",
    "run_evaluation",
]
