import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_get_training_hardware(client):
    """GET /api/training/hardware retorna telemetría de GPU/CPU y memoria."""
    res = client.get("/api/training/hardware")
    assert res.status_code == 200
    data = res.json()
    assert "cuda_available" in data
    assert "device_name" in data
    assert "vram_total_gb" in data
    assert "vram_used_gb" in data


def test_get_training_datasets(client):
    """GET /api/training/datasets retorna lista de datasets listos para entrenar."""
    res = client.get("/api/training/datasets")
    assert res.status_code == 200
    data = res.json()
    assert "datasets" in data
    assert isinstance(data["datasets"], list)


def test_training_lifecycle(client):
    """Prueba el ciclo de vida: iniciar entrenamiento, consultar progreso y detener."""
    with patch("app.services.training.training_service.start_training") as mock_start, \
         patch("app.services.training.training_service.get_progress") as mock_progress, \
         patch("app.services.training.training_service.stop_training") as mock_stop:

        mock_start.return_value = {
            "status": "started",
            "job_id": "train_job_123",
            "message": "Entrenamiento iniciado en segundo plano",
        }
        mock_progress.return_value = {
            "status": "training",
            "epoch": 2,
            "total_epochs": 10,
            "train_loss": 0.85,
            "val_loss": 0.72,
            "train_acc": 65.0,
            "val_acc": 70.5,
            "logs": ["Época 1 finalizada", "Época 2 finalizada"],
        }
        mock_stop.return_value = {
            "status": "stopped",
            "message": "Entrenamiento detenido por el usuario",
        }

        # 1. Iniciar entrenamiento
        payload = {
            "dataset_name": "AvesChilenas",
            "architecture": "AudioCNN",
            "epochs": 10,
            "learning_rate": 0.001,
            "batch_size": 16,
            "framework": "pytorch",
        }
        start_res = client.post("/api/training/start", json=payload)
        assert start_res.status_code == 200
        assert start_res.json()["status"] == "started"

        # 2. Consultar progreso
        prog_res = client.get("/api/training/progress")
        assert prog_res.status_code == 200
        assert prog_res.json()["epoch"] == 2

        # 3. Detener entrenamiento
        stop_res = client.post("/api/training/stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["status"] == "stopped"


def test_get_training_history(client):
    """GET /api/training/history retorna el catálogo histórico de modelos."""
    res = client.get("/api/training/history")
    assert res.status_code == 200
    data = res.json()
    assert "history" in data
    assert isinstance(data["history"], list)


def test_training_lifecycle_triad(client):
    """Verifica que POST /api/training/start soporte is_tri_model=True."""
    with patch("app.services.training.training_service.start_training") as mock_start:
        mock_start.return_value = {
            "status": "started",
            "job_id": "fama_triad_123",
            "message": "Pipeline de Tríada Completa iniciado.",
        }
        payload = {
            "dataset_name": "AvesChilenas",
            "architecture": "EfficientNet-B0",
            "epochs": 10,
            "learning_rate": 0.001,
            "batch_size": 16,
            "framework": "pytorch",
            "is_tri_model": True,
        }
        res = client.post("/api/training/start", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "started"
        mock_start.assert_called_once_with(
            dataset_name="AvesChilenas",
            architecture="EfficientNet-B0",
            epochs=10,
            learning_rate=0.001,
            batch_size=16,
            framework="pytorch",
            is_tri_model=True,
        )
