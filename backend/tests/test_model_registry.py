import pytest
from pathlib import Path
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services.predictors.base import AudioPredictor
from app.services.registry import ModelRegistry, ModelNotFoundError


class FakeAudioPredictor(AudioPredictor):
    """Implementación fake de prueba para el contrato AudioPredictor."""

    def __init__(self, model_id: str, name: str, is_default: bool = False):
        self._meta = ModelMetadata(
            id=model_id,
            name=name,
            description="Fake predictor for unit tests",
            target_sr=22050,
            duration_seconds=5.0,
            classes=["Especie A", "Especie B"],
            is_default=is_default,
        )

    @property
    def metadata(self) -> ModelMetadata:
        return self._meta

    def predict(self, audio_file_path: Path) -> PredictionResult:
        return PredictionResult(clase="Especie A", confianza=0.95)


def test_registry_register_and_get():
    registry = ModelRegistry()
    fake_predictor = FakeAudioPredictor(model_id="test-model-1", name="Test Model 1")

    registry.register(fake_predictor, is_default=True)

    # Obtener por ID exacto
    pred = registry.get("test-model-1")
    assert pred.model_id == "test-model-1"

    # Obtener sin ID (debe retornar el default)
    default_pred = registry.get(None)
    assert default_pred.model_id == "test-model-1"

    assert registry.get_default_model_id() == "test-model-1"


def test_registry_multiple_models_and_list():
    registry = ModelRegistry()
    m1 = FakeAudioPredictor(model_id="cnn", name="CNN Model", is_default=True)
    m2 = FakeAudioPredictor(model_id="ensemble", name="Ensemble Model")

    registry.register(m1, is_default=True)
    registry.register(m2, is_default=False)

    models = registry.list_models()
    assert len(models) == 2
    ids = [m.id for m in models]
    assert "cnn" in ids
    assert "ensemble" in ids


def test_registry_unknown_model_raises_model_not_found_error():
    registry = ModelRegistry()
    m1 = FakeAudioPredictor(model_id="cnn", name="CNN Model", is_default=True)
    registry.register(m1, is_default=True)

    with pytest.raises(ModelNotFoundError) as exc_info:
        registry.get("non-existent-model")

    assert "non-existent-model" in str(exc_info.value)


def test_registry_no_default_configured():
    registry = ModelRegistry()
    with pytest.raises(ModelNotFoundError):
        registry.get(None)


def test_get_model_registry_default_population():
    from app.services.registry import get_model_registry, set_global_model_registry
    set_global_model_registry(None)  # Reset singleton
    reg = get_model_registry()

    assert reg.has_model("chilean-birds-cnn")
    assert reg.has_model("chilean-birds-ensemble")
    assert reg.get_default_model_id() == "chilean-birds-cnn"

    cnn = reg.get("chilean-birds-cnn")
    assert cnn.model_id == "chilean-birds-cnn"

    default_model = reg.get(None)
    assert default_model.model_id == "chilean-birds-cnn"

