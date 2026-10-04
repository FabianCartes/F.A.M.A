import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Disable dotenv reads and import-time DDL; lifespan is never entered by this client.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
with patch("app.database.Base.metadata.create_all"):
    from app import main
from app.database import get_db
from app.services import training
from tests.test_training_flow import training_env, partitions, register

app = main.app


@pytest.fixture
def client(training_env, monkeypatch):
    service, sessions, _, _ = training_env
    monkeypatch.setattr(main, "training_service", service)
    monkeypatch.setattr(training, "training_service", service)
    def isolated_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    # Without the context manager TestClient does not run model loading/admin seeding.
    test_client = TestClient(app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("name,registered", [("medical_cough", True), ("AvesChilenas", False), ("AvesChilenas", True)])
def test_start_rejection_is_visible_in_api_progress(client, training_env, name, registered):
    service, sessions, _, thread = training_env
    if registered:
        register(sessions, name)
    response = client.post("/api/training/start", json={"dataset_name": name})
    assert response.status_code == 400
    assert name in response.json()["detail"]
    progress = client.get("/api/training/progress").json()
    assert progress["status"] == "failed"
    assert progress["error_message"] == response.json()["detail"]
    thread.assert_not_called()


@pytest.mark.parametrize("name", ["AvesChilenas", "engine_diagnostics"])
def test_api_accepts_supported_registered_source(client, training_env, name):
    _, sessions, root, _ = training_env
    register(sessions, name)
    partitions(root, name)
    response = client.post("/api/training/start", json={"dataset_name": name})
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    progress = client.get("/api/training/progress").json()
    assert progress["status"] == "training"
    assert progress["job_id"] == response.json()["job_id"]
    conflict = client.post("/api/training/start", json={"dataset_name": name})
    assert conflict.status_code == 400
    assert client.get("/api/training/progress").json()["status"] == "training"
    assert client.get("/api/training/history").status_code == 200


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
    assert data["datasets"] == []


def test_catalog_excludes_unsupported_registered_dataset(client, training_env):
    _, sessions, root, _ = training_env
    register(sessions, "medical_cough")
    register(sessions, "engine_diagnostics")
    partitions(root, "engine_diagnostics")
    response = client.get("/api/training/datasets")
    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()["datasets"]] == ["engine_diagnostics"]


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
            weight_decay=0.01,
            batch_size=16,
            framework="pytorch",
            is_tri_model=True,
            early_stopping=True,
        )


def test_training_lifecycle_dynamic_ensemble(client):
    """Verifica que POST /api/training/start procese modelos dinámicos con ponderaciones."""
    with patch("app.services.training.training_service.start_training") as mock_start:
        mock_start.return_value = {
            "status": "started",
            "job_id": "fama_ensemble_123",
            "message": "Pipeline de Ensamble iniciado.",
        }
        payload = {
            "dataset_name": "AvesChilenas",
            "models": [
                {"architecture": "ConvNeXt-Nano", "weight": 0.6},
                {"architecture": "EfficientNet-B0", "weight": 0.4},
            ],
            "epochs": 12,
            "learning_rate": 0.0005,
            "batch_size": 16,
            "framework": "pytorch",
        }
        res = client.post("/api/training/start", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "started"
        mock_start.assert_called_once_with(
            dataset_name="AvesChilenas",
            architecture="EfficientNet-B0",
            epochs=12,
            learning_rate=0.0005,
            weight_decay=0.01,
            batch_size=16,
            framework="pytorch",
            is_tri_model=False,
            early_stopping=True,
            models=[
                {"architecture": "ConvNeXt-Nano", "weight": 0.6, "epochs": None, "learning_rate": None, "batch_size": None},
                {"architecture": "EfficientNet-B0", "weight": 0.4, "epochs": None, "learning_rate": None, "batch_size": None},
            ],
        )


def test_start_training_api_passes_multi_domain_configs(client):
    """Verifica que POST /api/training/start pase audio_config, windowing_config y regularization_config al servicio."""
    with patch("app.services.training.training_service.start_training") as mock_start:
        mock_start.return_value = {
            "status": "started",
            "job_id": "fama_multidomain_123",
            "message": "Pipeline Multi-Dominio iniciado.",
        }
        payload = {
            "dataset_name": "engine_diagnostics",
            "architecture": "ResNet-34d",
            "epochs": 15,
            "learning_rate": 0.0003,
            "batch_size": 8,
            "audio_config": {
                "target_sr": 16000,
                "duration_seconds": 2.0,
                "f_min": 50.0,
                "f_max": 4000.0,
                "n_mels": 128,
                "n_fft": 1024,
                "hop_length": 256,
            },
            "windowing_config": {
                "hop_seconds": 0.5,
                "aggregation_mode": "max",
                "gem_p": 3.0,
                "vad_threshold": 0.05,
            },
            "regularization_config": {
                "loss_type": "focal",
                "focal_gamma": 2.5,
                "mixup_enabled": True,
                "mixup_alpha": 0.3,
                "pitch_shift_enabled": False,
            },
        }
        res = client.post("/api/training/start", json=payload)
        assert res.status_code == 200
        assert res.json()["status"] == "started"
        mock_start.assert_called_once()
        call_kwargs = mock_start.call_args.kwargs
        assert call_kwargs["dataset_name"] == "engine_diagnostics"
        assert call_kwargs["audio_config"]["target_sr"] == 16000
        assert call_kwargs["audio_config"]["f_max"] == 4000.0
        assert call_kwargs["windowing_config"]["hop_seconds"] == 0.5
        assert call_kwargs["regularization_config"]["loss_type"] == "focal"
        assert call_kwargs["regularization_config"]["focal_gamma"] == 2.5


def test_start_training_api_passes_weight_decay(client):
    """Verifica que POST /api/training/start propague weight_decay al servicio training_service."""
    with patch("app.services.training.training_service.start_training") as mock_start:
        mock_start.return_value = {
            "status": "started",
            "job_id": "fama_adamw_123",
            "message": "Entrenamiento iniciado con AdamW parametrizado.",
        }
        payload = {
            "dataset_name": "AvesChilenas",
            "architecture": "EfficientNet-B0",
            "epochs": 5,
            "learning_rate": 0.001,
            "weight_decay": 0.05,
            "batch_size": 16,
        }
        res = client.post("/api/training/start", json=payload)
        assert res.status_code == 200
        assert res.json()["status"] == "started"
        mock_start.assert_called_once()
        call_kwargs = mock_start.call_args.kwargs
        assert "weight_decay" in call_kwargs
        assert call_kwargs["weight_decay"] == 0.05


def test_start_training_api_passes_model_epochs(client):
    """Verifica que POST /api/training/start propague epochs individuales de cada modelo."""
    with patch("app.services.training.training_service.start_training") as mock_start:
        mock_start.return_value = {
            "status": "started",
            "job_id": "fama_ensemble_epochs_123",
            "message": "Ensamble iniciado con épocas por modelo.",
        }
        payload = {
            "dataset_name": "AvesChilenas",
            "models": [
                {"architecture": "ResNet-34d", "weight": 0.6, "epochs": 35},
                {"architecture": "EfficientNet-B0", "weight": 0.4, "epochs": 10},
            ],
            "epochs": 15,
        }
        res = client.post("/api/training/start", json=payload)
        assert res.status_code == 200
        call_kwargs = mock_start.call_args.kwargs
        assert "models" in call_kwargs
        assert call_kwargs["models"][0]["epochs"] == 35
        assert call_kwargs["models"][1]["epochs"] == 10




