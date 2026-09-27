import pytest
from pathlib import Path
import tempfile
import numpy as np
import soundfile as sf

from app.services.predictors.trained_predictor import (
    TrainedModelPredictor,
    ModelWeightsError,
)
from app.schemas.prediction import PredictionResult


CHECKPOINT_PATH = Path("backend/checkpoints/fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt")
AUDIO_PRUEBA_PATH = Path("/home/kevin/Downloads/audio_prueba.wav")


def test_trained_predictor_infers_real_audio():
    """
    Verifica que TrainedModelPredictor cargue el checkpoint entrenado en GPU
    y clasifique con alta confianza 'Chucao' en el audio real de prueba.
    """
    if not CHECKPOINT_PATH.exists():
        pytest.skip(f"Checkpoint no disponible en {CHECKPOINT_PATH}")
    if not AUDIO_PRUEBA_PATH.exists():
        pytest.skip(f"Audio de prueba no disponible en {AUDIO_PRUEBA_PATH}")

    predictor = TrainedModelPredictor(checkpoint_path=CHECKPOINT_PATH)
    assert predictor.model_id is not None
    assert len(predictor.classes) == 15
    assert "Chucao" in predictor.classes

    result = predictor.predict(AUDIO_PRUEBA_PATH)
    assert isinstance(result, PredictionResult)
    assert result.clase == "Chucao"
    assert result.confianza >= 0.95
    assert result.detalles is not None
    assert result.detalles.get("is_mock") is False
    assert result.detalles.get("checkpoint_name") == CHECKPOINT_PATH.name
    assert "device" in result.detalles
    assert result.detalles.get("latency_ms", 0) > 0


def test_trained_predictor_fails_fast_when_checkpoint_missing():
    """
    Invariante crítica: Si los pesos no existen, debe fallar con error explícito.
    Está terminantemente prohibido retornar mocks silenciosos.
    """
    missing_path = Path("/tmp/non_existent_weights_12345.pt")
    with pytest.raises(ModelWeightsError):
        TrainedModelPredictor(checkpoint_path=missing_path)


def test_trained_predictor_fails_fast_when_checkpoint_corrupted(tmp_path):
    """
    Si el archivo de pesos está corrupto o es inválido, falla ruidosamente.
    """
    corrupt_ckpt = tmp_path / "corrupt_model.pt"
    corrupt_ckpt.write_bytes(b"THIS_IS_NOT_A_VALID_TORCH_STATE_DICT")
    with pytest.raises(ModelWeightsError):
        TrainedModelPredictor(checkpoint_path=corrupt_ckpt)


def test_trained_predictor_fails_fast_when_audio_missing():
    """
    Si el archivo de audio a clasificar no existe, lanza FileNotFoundError.
    """
    if not CHECKPOINT_PATH.exists():
        pytest.skip(f"Checkpoint no disponible en {CHECKPOINT_PATH}")

    predictor = TrainedModelPredictor(checkpoint_path=CHECKPOINT_PATH)
    with pytest.raises(FileNotFoundError):
        predictor.predict(Path("/tmp/non_existent_audio_sample_9999.wav"))


def test_trained_predictor_detects_silence():
    """
    Valida que el filtro acústico VAD de energía detecte silencio absoluto.
    """
    if not CHECKPOINT_PATH.exists():
        pytest.skip(f"Checkpoint no disponible en {CHECKPOINT_PATH}")

    predictor = TrainedModelPredictor(checkpoint_path=CHECKPOINT_PATH)
    sr = 22050
    samples = np.zeros(sr * 3, dtype=np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, samples, sr)
        tmp_path = Path(tmp.name)

    try:
        res = predictor.predict(tmp_path)
        assert res.clase == "Silencio / No detectado"
        assert res.confianza == 0.0
        assert res.detalles["status"] == "silence"
        assert res.detalles["is_mock"] is False
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
