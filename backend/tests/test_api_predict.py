import io
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

from app.main import app, ensemble_service, SPECIES_CLASSES
from app.database import get_db


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
    mock_prediction = MagicMock()
    mock_prediction.id_prediccion = 42
    mock_session.refresh.side_effect = lambda obj: setattr(obj, "id_prediccion", 42)
    return mock_session


@pytest.fixture
def client(mock_db_session):
    """Cliente de prueba de FastAPI con dependencia de DB sobreescrita."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


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
def test_predict_success_with_super_ensemble(mock_gcp, client):
    """
    Verifica que el endpoint /api/predict ejecute el pipeline completo:
    1. Subida a GCP (simulada).
    2. Inferencia con el Super-Ensamble Tri-Modelo (Dense TTA + Micro-batching).
    3. Persistencia en DB (simulada).
    4. Respuesta 200 con clase y confianza real.
    """
    mock_gcp.return_value = True
    wav_data = create_dummy_wav_bytes(duration_sec=2.0)

    files = {"file": ("test_chucao.wav", wav_data, "audio/wav")}
    response = client.post("/api/predict", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "test_chucao.wav"
    assert data["gcp_upload"] is True
    assert data["db_id"] == 42
    assert data["clase"] in SPECIES_CLASSES
    assert isinstance(data["confianza"], float)
    assert 0.0 <= data["confianza"] <= 1.0
    assert "modelo" in data
    assert "is_fallback" in data
    assert "modelos_activos" in data


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

