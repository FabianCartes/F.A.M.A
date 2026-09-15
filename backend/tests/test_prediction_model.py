import pytest
from app.models.prediction import Prediccion


def test_prediccion_model_instantiation_with_modelo_id():
    """Verifica que el modelo relacional acepte modelo_id explícito."""
    pred = Prediccion(
        ruta_audio_prueba="test_audio.wav",
        etiqueta_predicha="Zorzal patagónico",
        confianza=0.9250,
        modelo_id="chilean-birds-cnn",
    )
    assert pred.ruta_audio_prueba == "test_audio.wav"
    assert pred.etiqueta_predicha == "Zorzal patagónico"
    assert pred.confianza == 0.9250
    assert pred.modelo_id == "chilean-birds-cnn"


def test_prediccion_model_backward_compatibility_without_modelo_id():
    """Verifica que la creación de Prediccion sin modelo_id no falle (retrocompatibilidad)."""
    pred = Prediccion(
        ruta_audio_prueba="legacy_audio.wav",
        etiqueta_predicha="Chincol",
        confianza=0.8500,
    )
    assert pred.ruta_audio_prueba == "legacy_audio.wav"
    assert pred.etiqueta_predicha == "Chincol"
    assert pred.confianza == 0.8500
    # Por defecto debe ser None o el default definido en columna
    assert hasattr(pred, "modelo_id")
