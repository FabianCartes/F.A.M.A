import pytest
from pathlib import Path
import numpy as np
import soundfile as sf
from app.services.predictors.ensemble_predictor import ChileanBirdsEnsemblePredictor
from app.services.predictors.trained_predictor import ModelWeightsError


def test_ensemble_predictor_metadata():
    pred = ChileanBirdsEnsemblePredictor(lazy_load=True)
    meta = pred.metadata
    assert meta.id == "chilean-birds-ensemble"
    assert "Super-Ensamble" in meta.name
    assert meta.metrics["f1_macro"] == 0.8868
    assert meta.target_sr == 22050
    assert len(meta.classes) == 15


def test_ensemble_predictor_predict_fails_when_checkpoint_missing(tmp_path):
    # Instanciar con rutas inexistentes para validar que no haya mocks silenciosos
    pred = ChileanBirdsEnsemblePredictor(
        checkpoint_paths=[Path("/tmp/fake1.pt"), Path("/tmp/fake2.pt")],
        lazy_load=False,
    )
    # Audio sintético válido que no sea silencio ni ruido
    dummy_wav = tmp_path / "valid_signal.wav"
    sr = 22050
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    waveform = 0.5 * np.sin(2 * np.pi * 1000.0 * t)
    sf.write(dummy_wav, waveform, sr)

    with pytest.raises(ModelWeightsError):
        pred.predict(dummy_wav)

