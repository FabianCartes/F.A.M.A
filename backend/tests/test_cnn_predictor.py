import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf
import pytest

from app.services.predictors.cnn_predictor import AudioCNNPredictor
from app.schemas.prediction import PredictionResult


@pytest.fixture
def predictor():
    # Instancia con ruta inexistente para usar el modo simulación/contingencia
    return AudioCNNPredictor(checkpoint_path=Path("/tmp/non_existent_ckpt.pt"))


def test_cnn_predictor_metadata(predictor):
    meta = predictor.metadata
    assert meta.id == "chilean-birds-cnn"
    assert meta.target_sr == 22050
    assert meta.duration_seconds == 5.0
    assert len(meta.classes) == 15
    assert "Chincol" in meta.classes


def test_cnn_predictor_detects_silence(predictor):
    # Generar audio de 5 segundos de puro silencio (amplitud 0)
    sr = 22050
    samples = np.zeros(sr * 5, dtype=np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, samples, sr)
        tmp_path = Path(tmp.name)

    try:
        result = predictor.predict(tmp_path)
        assert isinstance(result, PredictionResult)
        assert result.clase == "Silencio / No detectado"
        assert result.confianza == 0.0
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def test_cnn_predictor_detects_noise(predictor):
    # Generar ruido blanco con alta planitud espectral (> 0.15)
    sr = 22050
    samples = np.random.randn(sr * 5).astype(np.float32) * 0.2
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, samples, sr)
        tmp_path = Path(tmp.name)

    try:
        result = predictor.predict(tmp_path)
        assert isinstance(result, PredictionResult)
        assert result.clase == "Ruido / Señal no biológica"
        assert result.confianza == 0.0
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
