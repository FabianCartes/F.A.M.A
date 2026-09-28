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

        # Verificar que cada entrada en metrics_history incluya architecture y model_index
        assert len(training_service.metrics_history) == 22
        for entry in training_service.metrics_history[:12]:
            assert entry.get("architecture") == "ConvNeXt-Nano"
            assert entry.get("model_index") == 1
        for entry in training_service.metrics_history[12:]:
            assert entry.get("architecture") == "EfficientNet-B0"
            assert entry.get("model_index") == 2

        progress = training_service.get_progress()
        assert progress["metrics_history"][0].get("architecture") == "ConvNeXt-Nano"
        assert progress["metrics_history"][0].get("model_index") == 1


def test_start_training_worker_with_custom_audio_physics(training_service):
    """
    Verifica que al proveer un audio_config personalizado (ej: 16000 Hz, 2.0 s, f_min=50, f_max=4000),
    el worker utilice GenericAudioDataset y GPUAudioFrontEnd con dichos parámetros en lugar de los cableados.
    """
    config = {
        "job_id": "test_custom_physics_job",
        "dataset_name": "AvesChilenas",
        "architecture": "EfficientNet-B0",
        "epochs": 1,
        "learning_rate": 0.001,
        "batch_size": 16,
        "framework": "pytorch",
        "is_tri_model": False,
        "models": [{"architecture": "EfficientNet-B0", "weight": 1.0}],
        "audio_config": {
            "target_sr": 16000,
            "duration_seconds": 2.0,
            "f_min": 50.0,
            "f_max": 4000.0,
            "n_mels": 128,
            "n_fft": 1024,
            "hop_length": 256,
        },
    }

    mock_model = MagicMock()
    mock_model.parameters.return_value = []
    mock_model.state_dict.return_value = {}

    with patch.object(training_service, "_build_model_instance", return_value=mock_model), \
         patch("app.services.training.GenericAudioDataset") as mock_generic_ds, \
         patch("app.services.training.GPUAudioFrontEnd") as mock_frontend, \
         patch("app.services.training.DataLoader", return_value=[]), \
         patch("app.services.training.torch.save"), \
         patch("app.services.training.SessionLocal"):

        training_service._run_training_worker(config)

        # Verificar que GenericAudioDataset fue llamado con AudioConfig personalizado
        assert mock_generic_ds.called
        created_audio_cfg = mock_generic_ds.call_args_list[0].kwargs.get("audio_config")
        assert created_audio_cfg is not None
        assert created_audio_cfg.target_sr == 16000
        assert created_audio_cfg.duration_seconds == 2.0
        assert created_audio_cfg.f_min == 50.0
        assert created_audio_cfg.f_max == 4000.0
        assert created_audio_cfg.n_fft == 1024
        assert created_audio_cfg.hop_length == 256

        # Verificar que GPUAudioFrontEnd fue configurado con los mismos parámetros
        assert mock_frontend.called
        frontend_kwargs = mock_frontend.call_args.kwargs
        assert frontend_kwargs.get("sample_rate") == 16000
        assert frontend_kwargs.get("f_min") == 50.0
        assert frontend_kwargs.get("f_max") == 4000.0
        assert frontend_kwargs.get("n_fft") == 1024
        assert frontend_kwargs.get("hop_length") == 256


def test_start_training_worker_with_regularization_loss_config(training_service):
    """
    Verifica que el worker configure FocalLoss con el gamma especificado o CrossEntropyLoss
    según regularization_config.
    """
    mock_model = MagicMock()
    mock_model.parameters.return_value = []
    mock_model.state_dict.return_value = {}

    # Caso 1: CrossEntropyLoss
    ce_config = {
        "job_id": "test_ce_job",
        "dataset_name": "AvesChilenas",
        "architecture": "EfficientNet-B0",
        "epochs": 1,
        "learning_rate": 0.001,
        "batch_size": 16,
        "framework": "pytorch",
        "is_tri_model": False,
        "models": [{"architecture": "EfficientNet-B0", "weight": 1.0}],
        "regularization_config": {
            "loss_type": "cross_entropy",
        },
    }

    with patch.object(training_service, "_build_model_instance", return_value=mock_model), \
         patch("app.services.training.DataLoader", return_value=[]), \
         patch("app.services.training.torch.save"), \
         patch("app.services.training.SessionLocal"), \
         patch("app.services.training.torch.nn.CrossEntropyLoss") as mock_ce:

        training_service._run_training_worker(ce_config)
        assert mock_ce.called

    # Caso 2: FocalLoss con gamma=3.5
    focal_config = {
        "job_id": "test_focal_job",
        "dataset_name": "AvesChilenas",
        "architecture": "EfficientNet-B0",
        "epochs": 1,
        "learning_rate": 0.001,
        "batch_size": 16,
        "framework": "pytorch",
        "is_tri_model": False,
        "models": [{"architecture": "EfficientNet-B0", "weight": 1.0}],
        "regularization_config": {
            "loss_type": "focal",
            "focal_gamma": 3.5,
        },
    }

    with patch.object(training_service, "_build_model_instance", return_value=mock_model), \
         patch("app.services.training.DataLoader", return_value=[]), \
         patch("app.services.training.torch.save"), \
         patch("app.services.training.SessionLocal"), \
         patch("app.services.training.FocalLoss") as mock_focal:

        training_service._run_training_worker(focal_config)
        assert mock_focal.called
        assert mock_focal.call_args.kwargs.get("gamma") == 3.5

