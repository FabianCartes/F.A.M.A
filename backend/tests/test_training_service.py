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


def test_checkpoint_incremental_nomenclature_versioning(training_service, tmp_path):
    """
    Verifica que el nombre físico del checkpoint siga la convención {dataset_clean}_{arch_clean}_v{version}.pt
    sin timestamps Unix ni la palabra _best, derivando la versión de count + 1 en PostgreSQL.
    """
    import torch
    from app.models.training import Modelo

    mock_model = MagicMock()
    mock_model.parameters.return_value = [torch.nn.Parameter(torch.zeros(1))]
    mock_model.state_dict.return_value = {}

    config = {
        "job_id": "test_job_nomenclatura",
        "dataset_name": "AvesChilenas",
        "architecture": "ConvNeXt-Nano",
        "epochs": 1,
        "learning_rate": 0.0005,
        "batch_size": 16,
        "framework": "pytorch",
        "is_tri_model": False,
        "models": [{"architecture": "ConvNeXt-Nano", "weight": 1.0}],
    }

    saved_files = []

    def mock_torch_save(obj, path):
        saved_files.append(Path(path).name)

    mock_db = MagicMock()
    # Simular que no existen modelos previos: count() = 0 -> version = 1
    mock_query = mock_db.query.return_value
    mock_filter = mock_query.filter.return_value
    mock_filter.count.return_value = 0

    with patch.object(training_service, "_build_model_instance", return_value=mock_model), \
         patch("app.services.training.DataLoader", return_value=[]), \
         patch("app.services.training.torch.save", side_effect=mock_torch_save), \
         patch("app.services.training.SessionLocal", return_value=mock_db):

        training_service._run_training_worker(config)

        assert len(saved_files) == 1
        expected_filename = "AvesChilenas_ConvNeXt_Nano_v1.pt"
        assert saved_files[0] == expected_filename
        assert "_best" not in saved_files[0]
        assert "test_job" not in saved_files[0]

        # Verificar qué se persistió en el modelo
        added_objects = [call[0][0] for call in mock_db.add.call_args_list if isinstance(call[0][0], Modelo)]
        assert len(added_objects) >= 1
        persisted_model = added_objects[0]
        assert persisted_model.ruta_binario_gcp == f"models/{expected_filename}"


def test_get_history_enriches_model_technical_sheet(training_service):
    """
    Verifica que get_history() enriquezca cada registro con la Ficha Técnica completa:
    name, version, filename, hyperparameters, audio_specs, classes, classes_count, file_size_bytes.
    También valida que los modelos históricos iniciales (#1 de Motores y #6 de Aves Chilenas)
    resuelvan con version = 1 (v1) ya que son los primeros de su respectivo par (Dataset, Arquitectura).
    """
    from datetime import datetime, timezone
    from app.models.training import Modelo

    mock_m1 = Modelo(
        id_modelo=1,
        clase_objetivo="13 Clases (engine_diagnostics)",
        arquitectura="EfficientNet-B0",
        epocas=10,
        tasa_aprendizaje=0.001,
        tamano_lote=16,
        precision=68.12,
        perdida=1.0297,
        ruta_binario_gcp="models/fama_efficientnet_b0_1790642923_efficientnet_b0_best.pt",
        tamano_bytes=48822960,
        activo=False,
        estado="entrenado",
        fecha_entrenamiento=datetime(2026, 9, 29, 0, 52, 14, tzinfo=timezone.utc),
    )

    mock_m6 = Modelo(
        id_modelo=6,
        clase_objetivo="15 Clases (AvesChilenas)",
        arquitectura="EfficientNet-B0",
        epocas=10,
        tasa_aprendizaje=0.001,
        tamano_lote=32,
        precision=77.78,
        perdida=0.35,
        ruta_binario_gcp="models/fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt",
        tamano_bytes=48822960,
        activo=True,
        estado="entrenado",
        fecha_entrenamiento=datetime(2026, 9, 29, 0, 6, 31, tzinfo=timezone.utc),
    )

    mock_db = MagicMock()
    mock_db.query.return_value.order_by.return_value.all.return_value = [mock_m1, mock_m6]

    history = training_service.get_history(db=mock_db)

    assert len(history) == 2

    # Modelo #1 (Motores Vehiculares · EfficientNet-B0) -> v1
    item_1 = next(h for h in history if h["id"] == 1)
    assert item_1["version"] == 1
    assert "v1" in item_1["name"]
    assert "Motores" in item_1["name"]
    assert item_1["filename"] == "fama_efficientnet_b0_1790642923_efficientnet_b0_best.pt"
    assert item_1["hyperparameters"]["learning_rate"] == 0.001
    assert item_1["hyperparameters"]["batch_size"] == 16
    assert item_1["hyperparameters"]["optimizer"] == "AdamW"
    assert item_1["hyperparameters"]["loss_type"] in ["Focal Loss", "CrossEntropy"]
    assert item_1["audio_specs"]["target_sr"] == 32000
    assert item_1["audio_specs"]["duration_seconds"] == 1.5
    assert item_1["audio_specs"]["fmax"] == 16000
    assert item_1["classes_count"] == 13
    assert item_1["file_size_bytes"] == 48822960

    # Modelo #6 (Aves Chilenas · EfficientNet-B0) -> v1 (primer modelo de Aves Chilenas + EfficientNet-B0)
    item_6 = next(h for h in history if h["id"] == 6)
    assert item_6["version"] == 1
    assert "v1" in item_6["name"]
    assert "Aves Chilenas" in item_6["name"]
    assert item_6["filename"] == "fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt"
    assert item_6["hyperparameters"]["learning_rate"] == 0.001
    assert item_6["hyperparameters"]["batch_size"] == 32
    assert item_6["audio_specs"]["target_sr"] == 22050
    assert item_6["audio_specs"]["duration_seconds"] == 5.0
    assert item_6["audio_specs"]["fmax"] == 11025
    assert item_6["classes_count"] == 15
    assert item_6["file_size_bytes"] == 48822960


def test_get_history_semantic_versioning_per_dataset_and_architecture(training_service):
    """
    Verifica la invariante de dominio de versionado semántico estricto por par (Dataset, Arquitectura):
    - Modelo ID 1: Motores · EfficientNet-B0 -> v1
    - Modelo ID 6: Aves Chilenas · EfficientNet-B0 -> v1
    - Modelo ID 7: Aves Chilenas · EfficientNet-B0 -> v2 (mismo dataset y arquitectura)
    - Modelo ID 8: Aves Chilenas · ResNet-34d -> v1 (nueva arquitectura para Aves Chilenas)
    - Modelo ID 9: Motores · ResNet-34d -> v1
    """
    from datetime import datetime, timezone
    from app.models.training import Modelo

    models = [
        Modelo(
            id_modelo=1,
            clase_objetivo="13 Clases (engine_diagnostics)",
            arquitectura="EfficientNet-B0",
            fecha_entrenamiento=datetime(2026, 9, 29, 0, 52, 14, tzinfo=timezone.utc),
            ruta_binario_gcp="models/motores_eff_1.pt",
        ),
        Modelo(
            id_modelo=6,
            clase_objetivo="15 Clases (AvesChilenas)",
            arquitectura="EfficientNet-B0",
            fecha_entrenamiento=datetime(2026, 9, 29, 0, 6, 31, tzinfo=timezone.utc),
            ruta_binario_gcp="models/aves_eff_1.pt",
        ),
        Modelo(
            id_modelo=7,
            clase_objetivo="15 Clases (AvesChilenas)",
            arquitectura="EfficientNet-B0",
            fecha_entrenamiento=datetime(2026, 9, 29, 1, 0, 0, tzinfo=timezone.utc),
            ruta_binario_gcp="models/aves_eff_2.pt",
        ),
        Modelo(
            id_modelo=8,
            clase_objetivo="15 Clases (AvesChilenas)",
            arquitectura="ResNet-34d",
            fecha_entrenamiento=datetime(2026, 9, 29, 1, 15, 0, tzinfo=timezone.utc),
            ruta_binario_gcp="models/aves_res_1.pt",
        ),
        Modelo(
            id_modelo=9,
            clase_objetivo="13 Clases (engine_diagnostics)",
            arquitectura="ResNet-34d",
            fecha_entrenamiento=datetime(2026, 9, 29, 1, 30, 0, tzinfo=timezone.utc),
            ruta_binario_gcp="models/motores_res_1.pt",
        ),
    ]

    mock_db = MagicMock()
    mock_db.query.return_value.order_by.return_value.all.return_value = models

    history = training_service.get_history(db=mock_db)

    by_id = {h["id"]: h for h in history}

    assert by_id[1]["name"] == "Motores · EfficientNet-B0 (v1)"
    assert by_id[1]["version"] == 1

    assert by_id[6]["name"] == "Aves Chilenas · EfficientNet-B0 (v1)"
    assert by_id[6]["version"] == 1

    assert by_id[7]["name"] == "Aves Chilenas · EfficientNet-B0 (v2)"
    assert by_id[7]["version"] == 2

    assert by_id[8]["name"] == "Aves Chilenas · ResNet-34d (v1)"
    assert by_id[8]["version"] == 1

    assert by_id[9]["name"] == "Motores · ResNet-34d (v1)"
    assert by_id[9]["version"] == 1


def test_start_training_worker_receives_weight_decay(training_service):
    """
    Verifica que start_training capture y propague el parámetro weight_decay
    dentro del diccionario de configuración enviado a _run_training_worker.
    """
    with patch.object(training_service, "_run_training_worker") as mock_worker:
        res = training_service.start_training(
            dataset_name="AvesChilenas",
            architecture="ConvNeXt-Nano",
            epochs=5,
            learning_rate=0.0005,
            weight_decay=0.05,
        )

        assert res["status"] == "started"
        mock_worker.assert_called_once()
        passed_config = mock_worker.call_args[0][0]
        assert "weight_decay" in passed_config
        assert passed_config["weight_decay"] == 0.05


def test_start_training_dynamic_ensemble_preserves_custom_epochs(training_service):
    """
    Verifica que si los modelos del ensamble definen epochs individuales,
    se capturen y propaguen dentro de la configuración del worker.
    """
    with patch.object(training_service, "_run_training_worker") as mock_worker:
        res = training_service.start_training(
            dataset_name="AvesChilenas",
            models=[
                {"architecture": "ResNet-34d", "weight": 0.6, "epochs": 35},
                {"architecture": "EfficientNet-B0", "weight": 0.4, "epochs": 10},
            ],
        )

        assert res["status"] == "started"
        mock_worker.assert_called_once()
        passed_config = mock_worker.call_args[0][0]
        assert "models" in passed_config
        assert passed_config["models"][0]["epochs"] == 35
        assert passed_config["models"][1]["epochs"] == 10





