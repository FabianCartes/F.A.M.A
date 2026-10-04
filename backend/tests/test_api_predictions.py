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
from app.services.predictors.base import AudioPredictor, ModelWeightsError
from training.pipelines.dataset import MalformedAudioError, load_and_resample
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


class StrictLoaderPredictor(DummyPredictor):
    """API boundary fixture using the production strict decoder, without decoder mocks."""

    def predict(self, audio_file_path) -> PredictionResult:
        self.audio_path = audio_file_path
        try:
            load_and_resample(audio_file_path, 22050, 5.0, strict=True)
        except MalformedAudioError as error:
            self.decode_error = error
            raise
        return super().predict(audio_file_path)


class FailingPredictor(DummyPredictor):
    def __init__(self, error):
        super().__init__("failing-model")
        self.error = error

    def predict(self, audio_file_path) -> PredictionResult:
        self.audio_path = audio_file_path
        raise self.error


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


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_corrupt_wav_returns_safe_400_without_persistence(
    mock_upload, client, mock_registry, mock_db,
):
    mock_upload.return_value = True
    predictor = StrictLoaderPredictor("strict-loader")
    mock_registry.register(predictor)
    corrupt_wav = b"not an audio file"

    response = client.post(
        "/api/predict?model_id=strict-loader",
        files={"file": ("corrupt.wav", corrupt_wav, "audio/wav")},
    )

    assert response.status_code == 400, response.json()
    assert response.json() == {
        "detail": "Audio inválido o no soportado. Proporcione un archivo WAV válido."
    }
    assert isinstance(predictor.decode_error, MalformedAudioError)
    assert isinstance(predictor.decode_error.__cause__, sf.LibsndfileError)
    assert str(predictor.audio_path) in str(predictor.decode_error)
    assert str(predictor.audio_path) not in response.text
    assert not predictor.audio_path.exists()
    assert mock_upload.await_args.args[0] == corrupt_wav
    assert mock_upload.await_args.kwargs["filename"].endswith(".wav")
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()
    mock_db.refresh.assert_not_called()


@pytest.mark.parametrize(
    "error, expected_status",
    [
        (ModelWeightsError("required weights unavailable"), 503),
        (RuntimeError("forward failed"), 500),
        (ValueError("invalid internal tensor shape"), 500),
        (PermissionError("decoder access denied"), 500),
        (OSError("decoder system failure"), 500),
    ],
    ids=["weights", "runtime", "internal-value", "permission", "system"],
)
@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_inference_failure_never_persists_or_fabricates_success(
    mock_upload, client, mock_registry, mock_db, error, expected_status,
):
    mock_upload.return_value = True
    predictor = FailingPredictor(error)
    mock_registry.register(predictor)

    response = client.post(
        "/api/predict?model_id=failing-model",
        files={"file": ("canto.wav", create_dummy_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == expected_status
    assert set(response.json()) == {"detail"}
    assert str(error) in response.json()["detail"]
    if expected_status == 503:
        assert "failing-model" in response.json()["detail"]
    assert not predictor.audio_path.exists()
    mock_upload.assert_awaited_once()
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()
    mock_db.refresh.assert_not_called()


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_unnormalized_decoder_error_stays_500_without_persistence(
    mock_upload, client, mock_registry, mock_db,
):
    mock_upload.return_value = True
    predictor = StrictLoaderPredictor("strict-loader")
    mock_registry.register(predictor)

    response = client.post(
        "/api/predict?model_id=strict-loader",
        files={"file": (
            "corrupt.wav", b"RIFF\x24\x00\x00\x00WAVEcorrupt audio payload", "audio/wav",
        )},
    )

    assert response.status_code == 500
    assert set(response.json()) == {"detail"}
    assert not predictor.audio_path.exists()
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()
    mock_db.refresh.assert_not_called()


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_valid_wav_through_strict_loader_preserves_success(
    mock_upload, client, mock_registry, mock_db,
):
    mock_upload.return_value = True
    predictor = StrictLoaderPredictor("strict-loader")
    mock_registry.register(predictor)

    response = client.post(
        "/api/predict?model_id=strict-loader",
        files={"file": ("silence.wav", create_dummy_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "silence.wav"
    assert data["gcp_upload"] is True
    assert data["db_id"] == 101
    assert data["modelo_id"] == "strict-loader"
    assert data["clase"] == "Chincol"
    assert data["confianza"] == 0.95
    assert not predictor.audio_path.exists()
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()
    saved_prediction = mock_db.add.call_args.args[0]
    assert saved_prediction.modelo_id == data["modelo_id"]
    assert saved_prediction.etiqueta_predicha == data["clase"]
    assert saved_prediction.confianza == data["confianza"]


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_same_filename_predictions_have_distinct_recoverable_sources(mock_upload, client, mock_db):
    mock_upload.return_value = True
    audio = create_dummy_wav_bytes()
    for _ in range(2):
        response = client.post("/api/predict", files={"file": ("same.wav", audio, "audio/wav")})
        assert response.status_code == 200
    saved = [call.args[0] for call in mock_db.add.call_args_list]
    sources = [prediction.ruta_audio_prueba for prediction in saved]
    assert len(set(sources)) == 2
    for source, upload in zip(sources, mock_upload.await_args_list):
        assert source == "raw_audios/" + upload.kwargs["filename"]
        assert upload.args[0] == audio


@pytest.mark.parametrize("failure", [False, OSError("cloud unavailable")])
@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_unconfirmed_source_never_produces_success(mock_upload, client, mock_db, failure):
    if isinstance(failure, Exception):
        mock_upload.side_effect = failure
    else:
        mock_upload.return_value = failure
    response = client.post("/api/predict", files={"file": ("same.wav", create_dummy_wav_bytes(), "audio/wav")})
    assert response.status_code == 500
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


def test_predict_invalid_format_returns_400(client):
    response = client.post(
        "/api/predict",
        files={"file": ("audio.mp3", b"fake mp3 data", "audio/mp3")},
    )
    assert response.status_code == 400
    assert "Solo se permiten archivos de audio con extensión .wav" in response.json()["detail"]
