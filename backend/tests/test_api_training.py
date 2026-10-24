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
from tests.test_training_persistence import persistence_env
from tests.http_security import administrator_http

app = main.app


@pytest.mark.parametrize("historical", [False, True])
def test_api_reports_stale_preparation_and_requires_deliberate_history(client, training_env, historical):
    import json
    service, sessions, root, thread = training_env
    register(sessions, "AvesChilenas")
    raw = partitions(root, "AvesChilenas")
    marker = root / "prepared/AvesChilenas/.complete"
    version = json.loads(marker.read_bytes())["version_id"]
    index = raw / "metadata.csv"
    index.write_bytes(index.read_bytes() + b"\n")
    before = {p.name: p.read_bytes() for p in marker.parent.iterdir()}
    response = client.post("/api/training/start", json={"dataset_name": "AvesChilenas",
                           "prepared_version": version, "allow_historical_preparation": historical})
    if historical:
        assert response.status_code == 200, response.text
        assert response.json()["preparation"]["version_id"] == version
        assert response.json()["preparation"]["historical"] is True
        config = thread.call_args.kwargs["args"][0]
        assert config["source"]["preparation"]["manifest"]["version_id"] == version
    else:
        assert response.status_code == 400
        assert "Stale prepared dataset" in response.json()["detail"]
        thread.assert_not_called()
        with sessions() as db:
            assert service.get_history(db) == []
    assert {p.name: p.read_bytes() for p in marker.parent.iterdir()} == before


@pytest.mark.parametrize("body", [
    {"prepared_version": "../escape"}, {"prepared_version": "a" * 63},
    {"allow_historical_preparation": True}, {"allow_historical_preparation": "true"},
])
def test_api_rejects_invalid_preparation_selection_before_admission(client, training_env, body):
    service, _, _, thread = training_env
    before = service.get_progress()
    response = client.post("/api/training/start", json=body)
    assert response.status_code == 422
    assert service.get_progress() == before
    thread.assert_not_called()


def test_api_selects_immutable_child_without_adopting_legacy_root(client, training_env):
    import json
    _, sessions, root, thread = training_env
    register(sessions, "AvesChilenas")
    partitions(root, "AvesChilenas")
    store = root / "prepared/AvesChilenas"
    manifest = json.loads((store / ".complete").read_bytes())
    child = store / manifest["version_id"]
    child.mkdir()
    for file in list(store.iterdir()):
        if file.is_file():
            file.rename(child / file.name)
    (store / ".complete").write_text("legacy root marker")
    response = client.post("/api/training/start", json={"prepared_version": manifest["version_id"]})
    assert response.status_code == 200, response.text
    assert thread.call_args.kwargs["args"][0]["source"]["preparation"]["manifest"] == manifest


def test_api_admits_curated_derivatives_with_their_original_groups(client, training_env):
    import pandas as pd
    from training.prepare_data import prepare_dataset
    from training import paths

    _, sessions, root, thread = training_env
    register(sessions, "AvesChilenas")
    raw = partitions(root, "AvesChilenas")
    index = raw / "metadata.csv"
    originals = pd.read_csv(index, dtype=str, keep_default_na=False)
    originals["curation_source_id"] = ""
    curated = originals.copy()
    curated["curation_source_id"] = originals.xc_id
    curated["xc_id"] = "feedback_" + originals.xc_id
    curated["recordist"] = "human_feedback"
    curated["file_path"] = originals.file_path.str.replace(".wav", "_feedback.wav", regex=False)
    for old, new in zip(originals.file_path, curated.file_path):
        (raw / new).write_bytes((raw / old).read_bytes())
    pd.concat([originals, curated]).to_csv(index, index=False)
    result = prepare_dataset(index, roots=paths.get_dataset_roots("AvesChilenas"),
                              dataset_name="AvesChilenas", output_dir=root / "prepared/AvesChilenas",
                              versioned=True)
    response = client.post("/api/training/start", json={"prepared_version": result["version_id"]})
    assert response.status_code == 200, response.text
    source = thread.call_args.kwargs["args"][0]["source"]
    for recordings in source["recordings"].values():
        assert len(recordings) == 2
        assert recordings[0].group == recordings[1].group
        assert recordings[0].group != "human_feedback"


@pytest.mark.parametrize('seed', [0, 314, 4_294_967_295])
def test_api_propagates_selected_seed(client, training_env, seed):
    _, sessions, root, thread = training_env
    register(sessions, 'engine_diagnostics')
    partitions(root, 'engine_diagnostics')
    response = client.post('/api/training/start', json={'dataset_name': 'engine_diagnostics', 'seed': seed})
    assert response.status_code == 200
    config = thread.call_args.kwargs['args'][0]
    assert config['seed'] == seed


@pytest.mark.parametrize('seed', [-1, 4_294_967_296, 1.5, True, '42', None])
def test_api_rejects_invalid_seed_without_admission(client, training_env, seed):
    service, _, _, thread = training_env
    before = service.get_progress()
    response = client.post('/api/training/start', json={'seed': seed})
    assert response.status_code == 422
    assert service.get_progress() == before
    thread.assert_not_called()


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
        with administrator_http(app):
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


@pytest.mark.parametrize("name", ["AvesChilenas", "engine_diagnostics", "FAMA_Prueba_Aves"])
def test_api_accepts_registered_canonical_source(client, training_env, name):
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


@pytest.mark.parametrize("change_during_training", [False, True])
def test_versioned_partition_identity_is_preserved_in_checkpoint_and_history(client, persistence_env, monkeypatch, change_during_training):
    import hashlib
    import torch
    from app.models.dataset import Audio
    from app.routes.partitions import router
    service, sessions, root, dataset_id = persistence_env
    client.app.include_router(router)
    raw = root / "raw" / "engine_diagnostics"
    from tests.test_ingestion_upload_integrity import synthetic_wav
    for index, split in enumerate(("train", "val", "test"), 1):
        (raw / f"fixture/{split}.wav").write_bytes(synthetic_wav(frames=800)[:-2] + index.to_bytes(2,"little"))
    # No implicit common recording group in this synthetic 3-way partition fixture.
    (raw / "metadata.csv").unlink()
    with sessions() as db:
        for split in ("train", "val", "test"):
            path = raw / f"fixture/{split}.wav"
            db.add(Audio(id_conjunto_datos=dataset_id, nombre_archivo=path.name, clase="Fixture",
                         ruta_gcp=f"datasets/engine_diagnostics/fixture/{split}.wav",
                         hash_archivo=hashlib.sha256(path.read_bytes()).hexdigest()))
        db.commit()
    base = "/api/training/datasets/engine_diagnostics/partitions"
    preview = client.post(base + "/preview", json={}).json()
    assert client.post(base, json={"preview_version": preview["version"], "acknowledge_warnings": True}).status_code == 200
    if change_during_training:
        import timm
        build = timm.create_model
        def changed_recording(*args, **kwargs):
            (raw / "fixture/train.wav").write_bytes(b"changed after admission")
            return build(*args, **kwargs)
        monkeypatch.setattr(timm, "create_model", changed_recording)
    response = client.post("/api/training/start", json={
        "dataset_name": "engine_diagnostics", "partition_version": preview["version"], "epochs": 1,
        "audio_config": {"target_sr": 8000, "duration_seconds": 0.5, "n_mels": 32,
                         "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0},
        "regularization_config": {"loss_type": "cross_entropy"}, "early_stopping": False})

    assert response.status_code == 200
    if change_during_training:
        assert client.get("/api/training/progress").json()["status"] == "failed"
        assert client.get("/api/training/history").json()["history"] == []
        assert list(service.checkpoints_dir.iterdir()) == []
        return
    assert client.get("/api/training/progress").json()["status"] == "completed"
    entry, = client.get("/api/training/history").json()["history"]
    assert entry.get("partition_version") == preview["version"]
    artifact = torch.load(service.checkpoints_dir / entry["filename"], weights_only=True, map_location="cpu")
    assert artifact["partition_manifest"]["version"] == preview["version"]
    assert artifact["partition_manifest"]["counts"] == {"train": 1, "val": 1, "test": 1}


@pytest.mark.parametrize("commit_fails", [False, True])
def test_api_reports_checkpoint_registration_outcome(client, persistence_env, commit_fails):
    from sqlalchemy import event
    service, sessions, _, dataset_id = persistence_env
    if commit_fails:
        def reject_commit(db):
            raise RuntimeError("Synthetic API commit failure")
        event.listen(sessions, "before_commit", reject_commit)
    response = client.post("/api/training/start", json={
        "dataset_name": "engine_diagnostics", "architecture": "EfficientNet-B0", "epochs": 1,
        "audio_config": {"target_sr": 8000, "duration_seconds": 0.5, "n_mels": 32,
                         "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0},
        "regularization_config": {"loss_type": "cross_entropy"}, "early_stopping": False,
    })
    assert response.status_code == 200
    progress = client.get("/api/training/progress").json()
    entries = client.get("/api/training/history").json()["history"]
    if commit_fails:
        assert progress["status"] == "failed"
        assert "Synthetic API commit failure" in progress["error_message"]
        assert entries == []
        assert list(service.checkpoints_dir.iterdir()) == []
    else:
        assert progress["status"] == "completed"
        entry, = entries
        assert entry["dataset_id"] == dataset_id
        assert entry["active"] is False  # Activation requires a separate administrator action.
        assert entry["user_id"] == 1
        assert len(entry["metrics"]) == 1
        assert (service.checkpoints_dir / entry["filename"]).is_file()


def test_training_fixture_preserves_external_background_threads(training_env):
    import threading

    caller_id = threading.get_ident()
    worker_ids = []
    worker = threading.Thread(
        target=lambda: worker_ids.append(threading.get_ident()), args=(),
    )
    worker.start()
    worker.join(timeout=1)

    assert len(worker_ids) == 1, "External thread callback must execute exactly once"
    assert worker_ids[0] != caller_id
    assert not worker.is_alive()


def test_api_completes_training_with_saved_reports_and_available_model(
    client, persistence_env, monkeypatch,
):
    import hashlib
    import timm
    import torch
    from app.services.registry import ModelRegistry, get_model_registry

    service, _, root, dataset_id = persistence_env

    def small_classifier(*args, num_classes, **kwargs):
        # Genuine CPU weights meet catalogue admission without padding or bypasses.
        model = torch.nn.Sequential(
            torch.nn.AdaptiveAvgPool2d(1), torch.nn.Flatten(),
            torch.nn.Linear(1, 1024), torch.nn.ReLU(),
            torch.nn.Linear(1024, num_classes),
        )
        for parameter in model.parameters():
            torch.nn.init.zeros_(parameter)
        return model

    monkeypatch.setattr(timm, "create_model", small_classifier)
    registry = ModelRegistry(raw_data_root=root / "raw")
    monkeypatch.setitem(app.dependency_overrides, get_model_registry, lambda: registry)

    response = client.post("/api/training/start", json={
        "dataset_name": "engine_diagnostics", "architecture": "EfficientNet-B0",
        "epochs": 1, "batch_size": 1,

        "audio_config": {"target_sr": 8000, "duration_seconds": 0.5, "n_mels": 32,
                         "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0},
        "regularization_config": {"loss_type": "cross_entropy"}, "early_stopping": False,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert response.json()["job_id"]

    progress_response = client.get("/api/training/progress")
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["status"] == "completed", progress["error_message"]
    assert progress["job_id"] == response.json()["job_id"]
    assert not progress["error_message"]
    assert len(progress["metrics_history"]) == 1

    history_response = client.get("/api/training/history")
    assert history_response.status_code == 200
    entry, = history_response.json()["history"]
    assert entry["dataset_id"] == dataset_id
    assert entry["dataset_name"] == "engine_diagnostics"
    assert entry["status"] == "standard_eval_completed"
    assert len(entry["metrics"]) == 1
    assert entry["metrics"][0]["epoca"] == 1
    checkpoint = service.checkpoints_dir / entry["filename"]
    assert checkpoint.is_file()
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == entry["sha256"]

    catalogue_response = client.get("/api/models")
    assert catalogue_response.status_code == 200
    catalogue = catalogue_response.json()
    assert catalogue["publication_errors"] == []
    assert catalogue["evaluation_catalogue_status"] == "available"
    assert catalogue["total"] == 1
    model, = catalogue["models"]
    assert model["id"] == f"fama_trained_model_{entry['id']}"
    assert model["dataset_name"] == "engine_diagnostics"
    assert model["classes"] == ["Fixture"]
    assert model["has_weights"] is True

    attempts = []
    for split in ("val", "test"):
        summary = model["evaluations"][split]
        attempt, completed = summary["latest_attempt"], summary["latest_completed"]
        assert attempt["status"] == "completed"
        assert attempt["id_evaluation"] == completed["id_evaluation"]
        assert attempt["provenance"] == completed["provenance"]
        assert completed["provenance"]["split"] == split
        assert completed["provenance"]["dataset"] == "engine_diagnostics"
        assert completed["provenance"]["checkpoint_sha256"] == entry["sha256"]
        assert completed["provenance"]["sample_count"] == 1
        assert completed["report"]["schema_version"] == 2
        assert completed["report"]["classes"] == ["Fixture"]
        assert completed["report"]["sample_count"] == 1
        # The isolated source contains one silent recording per split.
        assert completed["report"]["confusion_matrix"] == [[0, 1]]
        assert completed["report"]["rejection"]["count"] == 1
        assert completed["report"]["metrics"]["accuracy"] == 0.0
        attempts.append(completed)
    assert attempts[0]["id_evaluation"] != attempts[1]["id_evaluation"]
    assert attempts[0]["provenance"]["manifest_sha256"] != attempts[1]["provenance"]["manifest_sha256"]
    # Reading the catalogue must not rewrite training history or publication state.
    assert client.get("/api/training/history").json() == history_response.json()



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


def test_catalog_includes_new_registered_dataset_for_training(client, training_env):
    _, sessions, root, _ = training_env
    register(sessions, "FAMA_Prueba_Aves")
    partitions(root, "FAMA_Prueba_Aves")
    register(sessions, "engine_diagnostics")
    partitions(root, "engine_diagnostics")
    response = client.get("/api/training/datasets")
    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()["datasets"]] == ["FAMA_Prueba_Aves", "engine_diagnostics"]


def test_new_empty_dataset_does_not_invent_training_classes(client, training_env):
    _, sessions, _, _ = training_env
    register(sessions, "FAMA_Nuevo")
    response = client.get("/api/training/datasets")
    assert response.status_code == 200
    dataset, = response.json()["datasets"]
    assert dataset["classes"] == []
    assert dataset["class_count"] == 0


@pytest.mark.parametrize("persistence_env", ["FAMA_Prueba_Aves"], indirect=True)
def test_new_dataset_completes_and_registers_a_model_through_HTTP(client, persistence_env):
    service, _, _, dataset_id = persistence_env
    response = client.post("/api/training/start", json={
        "dataset_name": "FAMA_Prueba_Aves", "architecture": "EfficientNet-B0", "epochs": 1,
        "audio_config": {"target_sr": 8000, "duration_seconds": 0.5, "n_mels": 32,
                         "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0},
        "regularization_config": {"loss_type": "cross_entropy"}, "early_stopping": False,
    })
    assert response.status_code == 200
    progress = client.get("/api/training/progress").json()
    assert progress["status"] == "completed", progress["error_message"]
    entry, = client.get("/api/training/history").json()["history"]
    assert entry["dataset_id"] == dataset_id
    assert entry["dataset"] == "FAMA_Prueba_Aves"
    assert entry["name"] == "FAMA_Prueba_Aves · EfficientNet-B0 (v1)"
    assert entry["user_id"] == 1
    assert entry["active"] is False
    assert len(entry["metrics"]) == 1
    assert (service.checkpoints_dir / entry["filename"]).is_file()


@pytest.mark.parametrize("name", ["../outside", "CON", "bad/name", "name."])
def test_catalog_does_not_expose_unsafe_registered_dataset_names(client, training_env, name):
    _, sessions, _, _ = training_env
    register(sessions, name)
    response = client.get("/api/training/datasets")
    assert response.status_code == 200
    assert response.json()["datasets"] == []


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
            user_id=1,
            dataset_name="AvesChilenas",
            architecture="EfficientNet-B0",
            epochs=10,
            learning_rate=0.001,
            weight_decay=0.01,
            batch_size=16,
            framework="pytorch",
            is_tri_model=True,
            seed=42,
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
            user_id=1,
            dataset_name="AvesChilenas",
            architecture="EfficientNet-B0",
            epochs=12,
            learning_rate=0.0005,
            weight_decay=0.01,
            batch_size=16,
            framework="pytorch",
            is_tri_model=False,
            seed=42,
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


def test_failed_new_job_does_not_expose_previous_execution_snapshot(client, persistence_env):
    response = client.post("/api/training/start", json={
        "dataset_name": "engine_diagnostics", "architecture": "EfficientNet-B0", "epochs": 1,
        "audio_config": {"target_sr": 8000, "duration_seconds": 0.5, "n_mels": 32,
                         "n_fft": 256, "hop_length": 64, "f_min": 0.0, "f_max": 4000.0},
        "regularization_config": {"loss_type": "cross_entropy"}, "early_stopping": False,
    })
    assert response.status_code == 200
    assert client.get("/api/training/progress").json()["status"] == "completed"
    assert client.post("/api/training/start", json={"dataset_name": "not-supported"}).status_code == 400
    progress = client.get("/api/training/progress").json()
    assert progress["status"] == "failed"
    assert progress["current_architecture"] == ""
    assert progress["models_config"] == []
    assert progress["train_acc"] == 0
    assert progress["val_acc"] == 0
