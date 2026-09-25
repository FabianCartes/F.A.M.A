import pytest
from app.schemas.model_info import ModelMetadata, ModelListResponse
from app.schemas.prediction import PredictionResult, PredictionResponse


def test_model_metadata_schema():
    meta = ModelMetadata(
        id="chilean-birds-cnn",
        name="AudioCNN Baseline",
        description="Modelo baseline entrenado con VAD y Data Augmentation",
        target_sr=22050,
        duration_seconds=5.0,
        classes=["Chincol", "Zorzal patagónico"],
        is_default=True,
    )
    assert meta.id == "chilean-birds-cnn"
    assert meta.is_default is True
    assert len(meta.classes) == 2


def test_model_list_response_schema():
    meta = ModelMetadata(
        id="chilean-birds-cnn",
        name="AudioCNN Baseline",
        description="Modelo baseline",
        target_sr=22050,
        duration_seconds=5.0,
        classes=["Chincol"],
        is_default=True,
    )
    resp = ModelListResponse(models=[meta], total=1, default_model_id="chilean-birds-cnn")
    assert resp.total == 1
    assert resp.default_model_id == "chilean-birds-cnn"
    assert resp.models[0].id == "chilean-birds-cnn"


def test_prediction_schemas():
    result = PredictionResult(clase="Chincol", confianza=0.9123)
    assert result.clase == "Chincol"
    assert result.confianza == 0.9123

    resp = PredictionResponse(
        filename="test.wav",
        gcp_upload=True,
        db_id=42,
        clase="Chincol",
        confianza=0.9123,
        modelo_id="chilean-birds-cnn",
    )
    assert resp.filename == "test.wav"
    assert resp.gcp_upload is True
    assert resp.db_id == 42
    assert resp.modelo_id == "chilean-birds-cnn"
