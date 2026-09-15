import io
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient
import soundfile as sf
import numpy as np

from app.main import app
from app.database import get_db
from app.schemas.prediction import PredictionResult
from app.services.registry import get_model_registry, ModelRegistry
from app.services.predictors.base import AudioPredictor
from app.schemas.model_info import ModelMetadata


class DummyPredictor(AudioPredictor):
    def __init__(self, model_id: str, label: str = "Chincol", conf: float = 0.95):
        self._meta = ModelMetadata(
            id=model_id,
            name=f"Dummy {model_id}",
            description="Dummy model for api tests",
            target_sr=22050,
            duration_seconds=5.0,
            classes=["Chincol", "Zorzal"],
            is_default=(model_id == "default-model"),
        )
        self.label = label
        self.conf = conf

    @property
    def metadata(self) -> ModelMetadata:
        return self._meta

    def predict(self, audio_file_path) -> PredictionResult:
        return PredictionResult(clase=self.label, confianza=self.conf)


@pytest.fixture
def mock_registry():
    reg = ModelRegistry()
    reg.register(DummyPredictor("default-model", "Zorzal", 0.90), is_default=True)
    reg.register(DummyPredictor("custom-model", "Chincol", 0.99), is_default=False)
    return reg


@pytest.fixture
def mock_db():
    session = MagicMock()
    # Simular asignación de id_prediccion al refrescar
    def mock_refresh(instance):
        instance.id_prediccion = 101
    session.refresh.side_effect = mock_refresh
    return session


@pytest.fixture
def client(mock_registry, mock_db):
    app.dependency_overrides[get_model_registry] = lambda: mock_registry
    app.dependency_overrides[get_db] = lambda: mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def create_dummy_wav_bytes() -> bytes:
    buf = io.BytesIO()
    samples = np.zeros(22050, dtype=np.float32)
    sf.write(buf, samples, 22050, format="WAV")
    buf.seek(0)
    return buf.read()


def test_get_models_catalogue(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert data["total"] == 2
    assert data["default_model_id"] == "default-model"
    model_ids = [m["id"] for m in data["models"]]
    assert "default-model" in model_ids
    assert "custom-model" in model_ids


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_default_model(mock_upload, client, mock_db):
    mock_upload.return_value = True
    wav_bytes = create_dummy_wav_bytes()

    response = client.post(
        "/api/predict",
        files={"file": ("canto.wav", wav_bytes, "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "canto.wav"
    assert data["gcp_upload"] is True
    assert data["db_id"] == 101
    assert data["clase"] == "Zorzal"
    assert data["confianza"] == 0.90
    assert data["modelo_id"] == "default-model"

    mock_upload.assert_called_once()
    assert mock_db.commit.called


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_explicit_model(mock_upload, client, mock_db):
    mock_upload.return_value = True
    wav_bytes = create_dummy_wav_bytes()

    response = client.post(
        "/api/predict?model_id=custom-model",
        files={"file": ("canto.wav", wav_bytes, "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["clase"] == "Chincol"
    assert data["confianza"] == 0.99
    assert data["modelo_id"] == "custom-model"


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_invalid_model_returns_404_and_aborts_gcs(mock_upload, client):
    wav_bytes = create_dummy_wav_bytes()

    response = client.post(
        "/api/predict?model_id=modelo-fantasma",
        files={"file": ("canto.wav", wav_bytes, "audio/wav")},
    )

    assert response.status_code == 404
    assert "modelo-fantasma" in response.json()["detail"]
    # Garantía de seguridad: GCS NUNCA se invoca si el modelo no existe
    mock_upload.assert_not_called()


def test_predict_invalid_format_returns_400(client):
    response = client.post(
        "/api/predict",
        files={"file": ("audio.mp3", b"fake mp3 data", "audio/mp3")},
    )
    assert response.status_code == 400
    assert "Solo se permiten archivos de audio con extensión .wav" in response.json()["detail"]
