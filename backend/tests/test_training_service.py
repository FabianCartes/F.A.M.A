import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.training import TrainingService


@pytest.fixture
def training_service(tmp_path):
    svc = TrainingService(checkpoints_dir=tmp_path)
    yield svc


def test_start_training_dynamic_duo_models_initialization(training_service):
    """
    Verifica que al solicitar un Dúo Ensamble (2 modelos), TrainingService
    planifique total_models = 2, current_model_index = 1 y la primera arquitectura.
    """
    with patch.object(training_service, "_run_training_worker"):
        res = training_service.start_training(
            dataset_name="AvesChilenas",
            models=[
                {"architecture": "ConvNeXt-Nano", "weight": 0.6},
                {"architecture": "EfficientNet-B0", "weight": 0.4},
            ],
        )

        assert res["status"] == "started"
        assert training_service.status == "training"
        assert training_service.total_models == 2
        assert training_service.current_model_index == 1
        assert training_service.current_architecture == "ConvNeXt-Nano"

        progress = training_service.get_progress()
        assert progress["total_models"] == 2
        assert progress["current_model_index"] == 1
        assert progress["current_architecture"] == "ConvNeXt-Nano"


def test_start_training_dynamic_trio_custom_models(training_service):
    """
    Verifica ensamble personalizado de 3 modelos arbitrarios con ponderaciones.
    """
    with patch.object(training_service, "_run_training_worker"):
        res = training_service.start_training(
            dataset_name="AvesChilenas",
            models=[
                {"architecture": "PANNs-CNN14", "weight": 0.5},
                {"architecture": "ResNet-34d", "weight": 0.3},
                {"architecture": "AudioCNN", "weight": 0.2},
            ],
        )

        assert res["status"] == "started"
        assert training_service.total_models == 3
        assert training_service.current_architecture == "PANNs-CNN14"


def test_start_training_worker_executes_dynamic_models_sequentially(training_service):
    """
    Verifica que _run_training_worker itere y entrene exactamente la lista dinámica
    de modelos configurados (ej: ConvNeXt-Nano y EfficientNet-B0).
    """
    executed_models = []

    def mock_build_model(arch, num_classes, device):
        import torch
        executed_models.append(arch)
        mock = MagicMock()
        mock.parameters.return_value = [torch.nn.Parameter(torch.zeros(1))]
        mock.state_dict.return_value = {}
        return mock


    config = {
        "job_id": "test_duo_job",
        "dataset_name": "AvesChilenas",
        "architecture": "EfficientNet-B0",
        "epochs": 1,
        "learning_rate": 0.001,
        "batch_size": 16,
        "framework": "pytorch",
        "is_tri_model": False,
        "models": [
            {"architecture": "ConvNeXt-Nano", "weight": 0.7},
            {"architecture": "EfficientNet-B0", "weight": 0.3},
        ],
    }

    with patch.object(training_service, "_build_model_instance", side_effect=mock_build_model), \
         patch("app.services.training.DataLoader", return_value=[]), \
         patch("app.services.training.torch.save"), \
         patch("app.services.training.SessionLocal") as mock_session_local:
        
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        training_service._run_training_worker(config)

        assert executed_models == ["ConvNeXt-Nano", "EfficientNet-B0"]
        assert training_service.status == "completed"
        assert training_service.total_models == 2
        assert training_service.current_model_index == 2
