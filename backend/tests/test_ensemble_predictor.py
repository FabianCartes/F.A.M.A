import pytest
from pathlib import Path
from app.services.predictors.ensemble_predictor import ChileanBirdsEnsemblePredictor
from app.schemas.prediction import PredictionResult


def test_ensemble_predictor_metadata():
    pred = ChileanBirdsEnsemblePredictor(lazy_load=True)
    meta = pred.metadata
    assert meta.id == "chilean-birds-ensemble"
    assert "Super-Ensamble" in meta.name
    assert meta.metrics["f1_macro"] == 0.8868
    assert meta.target_sr == 22050
    assert len(meta.classes) == 15


def test_ensemble_predictor_predict_mock_fallback():
    # Instanciar con rutas inexistentes para validar el fallback seguro de contingencia
    pred = ChileanBirdsEnsemblePredictor(
        checkpoint_paths=[Path("/tmp/fake1.pt"), Path("/tmp/fake2.pt")],
        lazy_load=False,
    )
    result = pred.predict(Path("/tmp/non_existent.wav"))
    assert isinstance(result, PredictionResult)
    assert result.confianza >= 0.0
