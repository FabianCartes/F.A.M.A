import io
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import numpy as np
import soundfile as sf
import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# app.main synchronizes tables at import; HTTP contract collection must not
# connect to the default database or read dotenv configuration.
with patch("dotenv.load_dotenv", return_value=False), patch("sqlalchemy.MetaData.create_all"):
    from app.main import app, ensemble_service, SPECIES_CLASSES
    from app.database import get_db
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services import registry as registry_module
from app.services.registry import ModelRegistry, get_model_registry
from app.services.predictors.base import AudioPredictor, ModelWeightsError


class ContractPredictor(AudioPredictor):
    """Controlled HTTP fixture, not evidence of real inference quality."""

    def __init__(self, model_id="contract-birds", unavailable=False):
        self._metadata = ModelMetadata(
            id=model_id,
            name="HTTP contract fixture",
            description="Deterministic predictor for endpoint contract tests only",
            target_sr=22050,
            duration_seconds=2.0,
            classes=list(SPECIES_CLASSES),
        )
        self.unavailable = unavailable
        self.is_fallback = False

    @property
    def metadata(self):
        return self._metadata

    def predict(self, audio_file_path):
        if self.unavailable:
            raise ModelWeightsError("Controlled fixture has no weights")
        assert Path(audio_file_path).is_file()
        return PredictionResult(
            clase="Chucao",
            confianza=0.97,
            detalles={"is_mock": True, "fixture": "http-contract"},
        )


@pytest.fixture
def controlled_registry(monkeypatch):
    """Replace the singleton without discovering DB/disk models; restore on teardown."""
    registry = ModelRegistry()
    registry.register(ContractPredictor(), is_default=True)
    registry.register(ContractPredictor("unavailable-birds", unavailable=True))
    monkeypatch.setattr(registry_module, "_global_model_registry", registry)
    return registry


def create_dummy_wav_bytes(duration_sec: float = 2.0, sr: int = 22050) -> bytes:
    """Genera un archivo WAV en memoria para pruebas de endpoints."""
    samples = int(duration_sec * sr)
    t = np.linspace(0, duration_sec, samples, endpoint=False, dtype=np.float32)
    # Tono senoidal puro a 1000 Hz
    waveform = 0.5 * np.sin(2 * np.pi * 1000.0 * t)
    
    bio = io.BytesIO()
    sf.write(bio, waveform, sr, format="WAV", subtype="PCM_16")
    bio.seek(0)
    return bio.read()


@pytest.fixture
def mock_db_session():
    """Mock de sesión de base de datos SQLAlchemy."""
    mock_session = MagicMock()
    mock_session.refresh.side_effect = lambda obj: setattr(obj, "id_prediccion", 42)
    return mock_session


@pytest.fixture
def client(mock_db_session, controlled_registry, monkeypatch):
    """Exercise routes without startup model loading or database admin seeding."""
    # Response/model-info telemetry must not lazily load unrelated disk weights.
    monkeypatch.setattr(ensemble_service, "load_models", lambda: None)
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_model_registry] = lambda: controlled_registry
    test_client = TestClient(app)  # No context manager: do not run production lifespan.
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_root_and_health(client):
    """Verifica endpoints de comprobación operacional."""
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "status" in res_root.json()

    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "ok"}


def test_predict_invalid_extension(client):
    """Verifica rechazo con código 400 si el archivo no es .wav."""
    files = {"file": ("audio.mp3", b"fake mp3 data", "audio/mpeg")}
    response = client.post("/api/predict", files=files)
    assert response.status_code == 400
    assert "Solo se permiten archivos de audio con extensión .wav" in response.json()["detail"]


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_success_contract(mock_gcp, client, mock_db_session):
    """Verify upload, persistence and response mapping, not model quality."""
    mock_gcp.return_value = True
    wav_data = create_dummy_wav_bytes(duration_sec=2.0)

    files = {"file": ("test_chucao.wav", wav_data, "audio/wav")}
    response = client.post("/api/predict", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "test_chucao.wav"
    assert data["gcp_upload"] is True
    assert data["db_id"] == 42
    assert data["clase"] == "Chucao"
    assert data["confianza"] == 0.97
    assert data["modelo_id"] == "contract-birds"
    assert data["modelo"] == "HTTP contract fixture"
    assert data["is_fallback"] is False
    assert isinstance(data["modelos_activos"], list)
    assert data["detalles"] == {"is_mock": True, "fixture": "http-contract"}
    mock_gcp.assert_awaited_once_with(wav_data, filename="test_chucao.wav")
    mock_db_session.add.assert_called_once()
    saved = mock_db_session.add.call_args.args[0]
    assert saved.etiqueta_predicha == "Chucao"
    assert saved.confianza == 0.97
    assert saved.modelo_id == "contract-birds"
    mock_db_session.commit.assert_called_once()
    mock_db_session.refresh.assert_called_once_with(saved)


def test_ensemble_service_weights_and_configuration():
    """Verifica que el servicio tenga calibrados los pesos 0.55, 0.30 y 0.15."""
    assert ensemble_service.weights == [0.55, 0.30, 0.15]
    assert len(ensemble_service.classes) == 15


def test_get_model_info(client):
    """Verifica el endpoint GET /api/model-info para monitoreo de modelos activos."""
    response = client.get("/api/model-info")
    assert response.status_code == 200
    data = response.json()
    assert "is_fallback" in data
    assert "model_name" in data
    assert "active_models" in data
    assert "total_classes" in data
    assert data["total_classes"] == 15
    assert isinstance(data["active_models"], list)
    assert "triad_status" in data
    assert "ensemble_ready" in data
    assert "selected_domain" in data
    assert len(data["triad_status"]) == 3


def test_get_model_info_custom_dataset(client):
    """Verifica GET /api/model-info con dataset_name para evaluar modelos faltantes."""
    response = client.get("/api/model-info?dataset_name=MaquinariaMinas")
    assert response.status_code == 200
    data = response.json()
    assert data["selected_domain"] == "MaquinariaMinas"
    assert "triad_status" in data
    assert "missing_models" in data
    assert isinstance(data["missing_models"], list)


def test_super_ensemble_service_find_checkpoint(tmp_path):
    """Verifica que _find_checkpoint busque tanto en directorio explícito como en rutas candidatas."""
    from app.main import SuperEnsembleService

    # Crear una carpeta alternativa simulando checkpoints de la raíz
    alt_dir = tmp_path / "root_checkpoints"
    alt_dir.mkdir()
    dummy_ckpt = alt_dir / "custom_model.pt"
    dummy_ckpt.write_bytes(b"dummy")

    service = SuperEnsembleService(checkpoints_dir=tmp_path / "non_existent")
    # Inyectar alt_dir como una ruta candidata adicional
    found = service._find_checkpoint("custom_model.pt", extra_dirs=[alt_dir])
    assert found == dummy_ckpt
    assert found.exists()


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_unavailable_model_fails_closed(mock_gcp, client, mock_db_session):
    """Missing weights must produce 503, not fabricated success or DB persistence."""
    mock_gcp.return_value = True
    response = client.post(
        "/api/predict?model_id=unavailable-birds",
        files={"file": ("audio.wav", create_dummy_wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 503
    assert set(response.json()) == {"detail"}
    assert "unavailable-birds" in response.json()["detail"]
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_called()
    mock_db_session.refresh.assert_not_called()


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_predict_real_chucao_quality(mock_gcp, client, controlled_registry):
    """Opt-in quality diagnostic using an explicit compatible trained checkpoint.

    Set FAMA_QUALITY_MODEL_ID, FAMA_QUALITY_CHECKPOINT (trusted .pt under
    backend/checkpoints), and FAMA_QUALITY_AUDIO (known Chucao WAV under
    audios_prueba). Paths must be absolute. No newest-model discovery, downloads,
    home-directory search, or unrestricted pickle loading is permitted here.
    Missing prerequisites skip; configured incompatible models or bad results fail.
    This diagnostic is separate from the controlled HTTP contract proof.
    """
    required = ("FAMA_QUALITY_MODEL_ID", "FAMA_QUALITY_CHECKPOINT", "FAMA_QUALITY_AUDIO")
    config = {key: os.environ.get(key) for key in required}
    missing = [key for key, value in config.items() if not value]
    if missing:
        pytest.skip("Real Chucao quality prerequisites unset: " + ", ".join(missing))

    checkpoint = Path(config["FAMA_QUALITY_CHECKPOINT"])
    audio_path = Path(config["FAMA_QUALITY_AUDIO"])
    for path, root, suffix in (
        (checkpoint, _BACKEND_ROOT / "checkpoints", ".pt"),
        (audio_path, _BACKEND_ROOT.parent / "audios_prueba", ".wav"),
    ):
        assert path.is_absolute(), f"Quality prerequisite must be absolute: {path}"
        assert path.resolve().is_relative_to(root.resolve()), f"Quality artifact must be under {root}"
        assert path.suffix.lower() == suffix, f"Quality artifact must have extension {suffix}"
        if not path.is_file():
            pytest.skip(f"Real Chucao quality prerequisite unavailable: {path}")

    import torch
    from app.services.predictors.trained_predictor import TrainedModelPredictor

    original_load = torch.load

    def safe_load(*args, **kwargs):
        kwargs["weights_only"] = True
        return original_load(*args, **kwargs)

    # Require restricted deserialization even if the installed torch default changes.
    with patch.object(torch, "load", side_effect=safe_load):
        predictor = TrainedModelPredictor(
            checkpoint_path=checkpoint,
            model_id=config["FAMA_QUALITY_MODEL_ID"],
            lazy_load=False,
        )
        assert "Chucao" in predictor.metadata.classes, "Quality checkpoint must support Chucao"
        controlled_registry.register(predictor)
        mock_gcp.return_value = True
        response = client.post(
            "/api/predict",
            params={"model_id": predictor.model_id},
            files={"file": (audio_path.name, audio_path.read_bytes(), "audio/wav")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["modelo_id"] == config["FAMA_QUALITY_MODEL_ID"]
    assert data["clase"] == "Chucao"
    assert data["confianza"] >= 0.95
    assert data.get("is_fallback") is False
    assert "detalles" in data
    assert data["detalles"].get("is_mock") is False


