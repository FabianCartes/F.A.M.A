"""Assignment and functional HTTP contracts, no deployed services or assets."""
from unittest.mock import patch
from types import SimpleNamespace
import os
from datetime import datetime, timezone

import pytest

from app.models.dataset import ConjuntoDatos
from app.routes.access import router as access_router
from app.routes.access import catalogue_router
from app.routes.security import router as security_router
from app.models.training import Modelo
from app.models.prediction import Prediccion
from app.models.prediction_access import AccesoPrediccion
from app.models.feedback import Retroalimentacion
from app.models.feedback_sync import FeedbackSync
from app.models.user import Usuario
from app.services.registry import ModelRegistry, get_model_registry
from tests.test_web_sessions import web, login, ORIGIN, PASSWORD
from tests.test_ingestion_upload_integrity import upload_environment

with patch.dict(os.environ, {"DATABASE_URL": "sqlite://", "PYTHON_DOTENV_DISABLED": "1"}), \
        patch("dotenv.load_dotenv", return_value=False), patch("sqlalchemy.MetaData.create_all"):
    from tests.training_admission import DeferredTrainingProcess
from app import main


@pytest.fixture
def access(web):
    client, sessions = web
    client.app.include_router(access_router)
    client.app.include_router(catalogue_router)
    client.app.include_router(security_router)
    with sessions() as db:
        db.add_all([ConjuntoDatos(id_conjunto_datos=10, nombre="AvesChilenas", ruta_gcp="datasets/AvesChilenas"),
                    ConjuntoDatos(id_conjunto_datos=20, nombre="engine_diagnostics", ruta_gcp="datasets/engine_diagnostics")])
        db.commit()
    return client, sessions


@pytest.fixture
def functional(access, monkeypatch, tmp_path):
    from app.services import training, dashboard
    from app.services.feedback import FeedbackService
    from app.services.ingestion import IngestionService
    client, sessions = access
    monkeypatch.setattr(main, "feedback_service", FeedbackService(raw_data_dir=tmp_path / "raw"))
    monkeypatch.setattr(main, "ingestion_service", IngestionService(
        bucket_name="fixture-bucket", local_base_dir=tmp_path / "raw", local_processed_dir=tmp_path / "processed"))

    class OfflineCloud:
        def __init__(self):
            raise OSError("Synthetic cloud offline")

    monkeypatch.setattr("google.cloud.storage.Client", OfflineCloud)
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: tmp_path / "raw" / (name or ""))
    monkeypatch.setattr(main, "training_service", training.TrainingService(checkpoints_dir=tmp_path / "weights", process_factory=DeferredTrainingProcess))
    monkeypatch.setattr(dashboard, "training_service", SimpleNamespace(get_hardware_status=lambda: {}))
    client.app.dependency_overrides[get_model_registry] = lambda: ModelRegistry()
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/") and not path.startswith(("/api/auth/", "/api/access/")):
            client.app.add_api_route(path, route.endpoint, methods=list(route.methods),
                                     dependencies=route.dependencies, response_model=route.response_model,
                                     status_code=route.status_code)
    return client, sessions


def test_assignment_requires_administrator_and_can_be_revoked(access):
    client, _ = access
    path = "/api/access/users/2/datasets/10"
    assert client.put(path, headers={"Origin": ORIGIN}).status_code == 401
    assert login(client).status_code == 200
    assert client.put(path, headers={"Origin": ORIGIN}).status_code == 403
    assert login(client, "administrador").status_code == 200
    assert client.put(path, headers={"Origin": ORIGIN}).status_code == 200
    assert client.put(path, headers={"Origin": ORIGIN}).status_code == 200
    assert client.get(path).json() == {"user_id": 2, "dataset_id": 10, "assigned": True}
    assert client.delete(path, headers={"Origin": ORIGIN}).status_code == 204
    assert client.get(path).json()["assigned"] is False
    assert client.delete(path, headers={"Origin": ORIGIN}).status_code == 204


def test_functional_routes_require_session_before_work(functional, monkeypatch):
    client, _ = functional
    monkeypatch.setattr(main, "training_service", SimpleNamespace(get_hardware_status=lambda: {"sentinel": "private"}))
    assert client.get("/api/training/hardware").status_code == 401
    assert login(client).status_code == 200
    assert client.get("/api/training/hardware").status_code == 200


def assign(client, user_id=2, dataset_id=10):
    assert login(client, "administrador").status_code == 200
    assert client.put(f"/api/access/users/{user_id}/datasets/{dataset_id}", headers={"Origin": ORIGIN}).status_code == 200
    assert login(client).status_code == 200


def test_researcher_inventory_observes_only_assigned_local_and_cloud_resources(functional, monkeypatch, tmp_path):
    from app.services.ingestion import IngestionService
    from tests.test_ingestion_upload_integrity import synthetic_wav
    client, _ = functional
    raw = tmp_path / "raw"
    audio = raw / "AvesChilenas" / "Chucao" / "local.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(synthetic_wav())
    private = raw / "engine_diagnostics" / "private"
    private.mkdir(parents=True)
    (private / "secret.wav").write_bytes(synthetic_wav())

    class Cloud:
        def list_blobs(self, bucket, prefix):
            assert prefix == "datasets/AvesChilenas/", "Unassigned inventory must not be enumerated"
            return []

    monkeypatch.setattr("google.cloud.storage.Client", Cloud)
    monkeypatch.setattr(main, "ingestion_service", IngestionService(
        bucket_name="fixture-bucket", local_base_dir=raw, local_processed_dir=tmp_path / "processed"))
    assign(client)

    response = client.get("/api/ingestion/datasets")

    assert response.status_code == 200
    dataset, = response.json()["datasets"]
    assert dataset["name"] == "AvesChilenas"
    assert dataset.get("local_file_count") == 1
    assert dataset["gcs_file_count"] == 0
    assert dataset["sync_state"] == "local_only"
    assert response.json()["can_create_dataset"] is False
    assert "engine_diagnostics" not in response.text


def test_dataset_files_and_whole_sync_batch_are_authorized_before_io(functional, monkeypatch):
    client, _ = functional
    calls = []
    service = SimpleNamespace(
        list_dataset_files=lambda name, **kwargs: calls.append(name) or [],
        validate_dataset_names=lambda names: None,
        sync_dataset_to_local=lambda name, **kwargs: calls.append(name) or {"downloaded": 1},
    )
    monkeypatch.setattr(main, "ingestion_service", service)
    assign(client)
    assert client.get("/api/ingestion/datasets/engine_diagnostics/files").status_code == 404
    response = client.post("/api/ingestion/sync", headers={"Origin": ORIGIN},
                           json={"datasets": ["AvesChilenas", "engine_diagnostics"]})
    assert response.status_code == 404
    assert calls == []
    assert client.get("/api/ingestion/datasets/AvesChilenas/files").status_code == 200
    assert calls == ["AvesChilenas"]
    assert login(client, "administrador").status_code == 200
    assert client.delete("/api/access/users/2/datasets/10", headers={"Origin": ORIGIN}).status_code == 204
    assert login(client).status_code == 200
    assert client.get("/api/ingestion/datasets/AvesChilenas/files").status_code == 404


def test_unassigned_upload_does_not_transfer_or_decode(functional, monkeypatch):
    client, _ = functional
    monkeypatch.setattr(main, "ingestion_service", SimpleNamespace())
    assert login(client).status_code == 200
    response = client.post("/api/ingestion/upload", headers={"Origin": ORIGIN},
                           data={"dataset_name": "engine_diagnostics"},
                           files={"files": ("sample.wav", b"synthetic", "audio/wav")})
    assert response.status_code == 404


def test_assigned_researcher_upload_is_attributed_and_revocation_blocks_further_transfers(functional, upload_environment, monkeypatch):
    from tests.test_ingestion_upload_integrity import synthetic_wav
    client, sessions = functional
    service, _, objects = upload_environment
    monkeypatch.setattr(main, 'ingestion_service', service)
    assign(client)
    payload = synthetic_wav()
    result = client.post('/api/ingestion/upload', headers={'Origin': ORIGIN},
                         data={'dataset_name': 'AvesChilenas', 'class_label': 'Chucao'},
                         files={'files': ('synthetic.wav', payload, 'audio/wav')})
    assert result.status_code == 200, result.text
    assert result.json()['db_persisted'] is True
    dataset, = client.get('/api/training/datasets').json()['datasets']
    assert dataset['audio_count'] == 1
    assert len(objects) == 1
    assert login(client, 'administrador').status_code == 200
    audit_response = client.get('/api/security/audit')
    assert audit_response.status_code == 200, audit_response.text
    audit, = [item for item in audit_response.json()['events']
              if item['action'] == 'dataset.audio_uploaded']
    assert audit['actor_id'] == 2
    assert audit['dataset_id'] == 10
    assert client.delete('/api/access/users/2/datasets/10', headers={'Origin': ORIGIN}).status_code == 204
    assert login(client).status_code == 200
    assert client.post('/api/ingestion/upload', headers={'Origin': ORIGIN},
                       data={'dataset_name': 'AvesChilenas'},
                       files={'files': ('next.wav', payload, 'audio/wav')}).status_code == 404
    assert len(objects) == 1


def test_assigned_researcher_incorporates_own_correction_and_registers_audio_once(functional, monkeypatch, tmp_path):
    from tests.test_ingestion_upload_integrity import synthetic_wav
    from app.services import storage
    client, sessions = functional
    audio = synthetic_wav()
    monkeypatch.setattr(storage, "download_prediction_audio", lambda source: audio)
    (tmp_path / "raw" / "AvesChilenas" / "Chucao").mkdir(parents=True)
    with sessions() as db:
        db.add(Prediccion(id_prediccion=501, ruta_audio_prueba="raw_audios/synthetic.wav",
                          etiqueta_predicha="Chucao", dataset_name="AvesChilenas", confianza=.8))
        db.flush()
        db.add(AccesoPrediccion(id_prediccion=501, id_conjunto_datos=10, id_usuario=2))
        db.commit()
    assign(client)
    saved = client.post("/api/feedback", headers={"Origin": ORIGIN},
                        json={"id_prediccion": 501, "fue_correcta": True})
    assert saved.status_code == 201
    feedback_id = saved.json()["id_retroalimentacion"]
    for _ in range(2):
        accepted = client.post(f"/api/feedback/{feedback_id}/approve", headers={"Origin": ORIGIN})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json().get("db_persisted") is True
        assert accepted.json()["sync_status"] == "pending"
    registered, = client.get("/api/training/datasets").json()["datasets"]
    assert registered["audio_count"] == 1
    stored, = client.get('/api/ingestion/datasets/AvesChilenas/files').json()['files']
    assert stored['recorded_metadata'] == {'sample_rate_hz': 8000, 'duration_seconds': 1.0, 'source': 'database'}
    milestone, = client.get("/api/feedback/sync").json()
    assert milestone["proposed_by"] == 2
    assert milestone["incorporated_by"] == 2
    assert milestone["incorporated_at"]
    assert milestone["db_persisted"] is True
    assert login(client, "administrador").status_code == 200
    assert client.delete("/api/access/users/2/datasets/10", headers={"Origin": ORIGIN}).status_code == 204
    assert login(client).status_code == 200
    assert client.post(f"/api/feedback/{feedback_id}/approve", headers={"Origin": ORIGIN}).status_code == 404


def test_researcher_inventory_is_registered_and_scoped_not_global_cloud(functional, monkeypatch):
    client, _ = functional
    assign(client)
    response = client.get("/api/ingestion/datasets")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["datasets"]] == ["AvesChilenas"]
    assert client.get("/api/ingestion/status").status_code == 403
    assert client.get("/api/model-info?dataset_name=engine_diagnostics").status_code == 404


def test_dashboard_and_training_history_filter_before_checkpoint_reads(functional, monkeypatch, tmp_path):
    from app.services import dashboard, training
    client, sessions = functional
    with sessions() as db:
        for identifier, dataset, precision in [(100, 10, 11), (200, 20, 99), (300, None, 100)]:
            db.add(Modelo(id_modelo=identifier, id_conjunto_datos=dataset, arquitectura="fixture", epocas=1,
                          tasa_aprendizaje=0.01, tamano_lote=2, precision=precision, perdida=1,
                          ruta_binario_gcp=f"models/{identifier}.pt"))
        db.commit()
    service = training.TrainingService(checkpoints_dir=tmp_path / "checkpoints")
    monkeypatch.setattr(main, "training_service", service)
    monkeypatch.setattr(dashboard, "training_service", SimpleNamespace(get_hardware_status=lambda: {}))
    assign(client)
    response = client.get("/api/dashboard/stats")
    assert response.status_code == 200
    assert response.json()["kpis"]["total_datasets"] == 1
    assert response.json()["kpis"]["accuracy"] == 11
    assert response.json()["kpis"]["total_predictions"] == 0
    history = client.get("/api/training/history")
    assert history.status_code == 200
    assert [row["id"] for row in history.json()["history"]] == [100]


def test_catalogue_hides_unassigned_default_and_predict_checks_resolved_model_before_io(functional, monkeypatch):
    from tests.test_api_predict import ContractPredictor
    client, _ = functional
    registry = ModelRegistry()
    birds = ContractPredictor("assigned-model")
    birds._metadata.dataset_name = "AvesChilenas"
    engine = ContractPredictor("secret-model")
    engine._metadata.dataset_name = "engine_diagnostics"
    registry.register(engine, is_default=True)
    registry.register(birds)
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    assign(client)
    response = client.get("/api/models")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["models"]] == ["assigned-model"]
    assert response.json()["default_model_id"] == ""
    for query in ("", "?model_id=secret-model"):
        response = client.post("/api/predict" + query, headers={"Origin": ORIGIN},
                               data={"dataset_name": "AvesChilenas"},
                               files={"file": ("fixture.wav", b"never uploaded", "audio/wav")})
        assert response.status_code == 404


def test_training_datasets_are_scoped_and_activation_is_administrator_only(functional, monkeypatch, tmp_path):
    from app.services.training import TrainingService
    client, _ = functional
    monkeypatch.setattr(main, "training_service", TrainingService(checkpoints_dir=tmp_path / "weights"))
    assign(client)
    response = client.get("/api/training/datasets")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["datasets"]] == ["AvesChilenas"]
    assert client.post("/api/training/models/100/activate", headers={"Origin": ORIGIN}).status_code == 403


def seed_predictions(sessions):
    with sessions() as db:
        for identifier, dataset in [(1, "AvesChilenas"), (2, "engine_diagnostics"), (3, "AvesChilenas")]:
            db.add(Prediccion(id_prediccion=identifier, ruta_audio_prueba=f"raw_audios/{identifier}.wav",
                              etiqueta_predicha="fixture", confianza=0.8, dataset_name=dataset))
        db.flush()
        db.add_all([AccesoPrediccion(id_prediccion=1, id_conjunto_datos=10, id_usuario=2),
                    AccesoPrediccion(id_prediccion=2, id_conjunto_datos=20, id_usuario=1)])
        db.commit()


def test_feedback_uses_session_actor_and_legacy_names_do_not_grant_access(functional):
    client, sessions = functional
    seed_predictions(sessions)
    assign(client)
    for identifier in (2, 3):
        response = client.post("/api/feedback", headers={"Origin": ORIGIN},
                               json={"id_prediccion": identifier, "fue_correcta": True, "id_usuario": 1})
        assert response.status_code == 404
    response = client.post("/api/feedback", headers={"Origin": ORIGIN},
                           json={"id_prediccion": 1, "fue_correcta": True, "id_usuario": 1})
    assert response.status_code == 201
    assert response.json()["id_usuario"] == 2
    assert client.get("/api/dashboard/stats").json()["kpis"]["total_predictions"] == 1


def test_pending_stats_and_curation_are_dataset_scoped_before_limit(functional):
    client, sessions = functional
    seed_predictions(sessions)
    with sessions() as db:
        for identifier in (1, 2, 3):
            db.add(Retroalimentacion(id_retroalimentacion=identifier, id_prediccion=identifier,
                                     id_usuario=2, fue_correcta=True, procesado=False,
                                     fecha_retroalimentacion=datetime(2026, 10, 18, 12, identifier, tzinfo=timezone.utc)))
        db.commit()
    assign(client)
    response = client.get("/api/feedback/pending?limit=1")
    assert response.status_code == 200
    assert [item["id_prediccion"] for item in response.json()] == [1]
    assert client.get("/api/feedback/stats").json()["total_validated"] == 1
    for operation in ("approve", "reject"):
        for identifier in (2, 3):
            assert client.post(f"/api/feedback/{identifier}/{operation}", headers={"Origin": ORIGIN}).status_code == 404
    assert client.post("/api/feedback/1/reject", headers={"Origin": ORIGIN}).status_code == 200


def test_researcher_cannot_overwrite_another_authors_feedback(functional):
    client, sessions = functional
    seed_predictions(sessions)
    with sessions() as db:
        db.add(Retroalimentacion(id_prediccion=1, id_usuario=1, fue_correcta=True, procesado=False))
        db.commit()
    assign(client)
    response = client.post("/api/feedback", headers={"Origin": ORIGIN},
                           json={"id_prediccion": 1, "fue_correcta": False, "etiqueta_corregida": "other"})
    assert response.status_code == 403


def test_prediction_records_verified_dataset_and_actor_for_later_access(functional, monkeypatch):
    from unittest.mock import AsyncMock
    from tests.test_api_predict import ContractPredictor
    client, _ = functional
    registry = ModelRegistry()
    predictor = ContractPredictor("assigned-model")
    predictor._metadata.dataset_name = "AvesChilenas"
    registry.register(predictor, is_default=True)
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    monkeypatch.setattr(main, "upload_audio_to_gcp", AsyncMock(return_value=True))
    assign(client)
    response = client.post("/api/predict", headers={"Origin": ORIGIN},
                           data={"dataset_name": "engine_diagnostics"},
                           files={"file": ("fixture.wav", __import__("tests.test_api_predict", fromlist=["create_dummy_wav_bytes"]).create_dummy_wav_bytes(), "audio/wav")})
    assert response.status_code == 200
    assert response.json()["detalles"]["dataset_name"] == "AvesChilenas"
    response = client.post("/api/feedback", headers={"Origin": ORIGIN},
                           json={"id_prediccion": response.json()["db_id"], "fue_correcta": True})
    assert response.status_code == 201
    assert response.json()["id_usuario"] == 2


def test_only_job_owner_or_administrator_can_observe_and_stop_training(functional, monkeypatch, tmp_path):
    from app.services import training
    from training import paths
    from tests.test_training_flow import partitions
    client, sessions = functional
    monkeypatch.setattr(training, "SessionLocal", sessions)
    monkeypatch.setattr(paths, "get_raw_data_dir", lambda name=None: tmp_path / "raw" / (name or ""))
    monkeypatch.setattr(paths, "get_processed_data_dir", lambda name=None: tmp_path / "processed" / (name or ""))
    monkeypatch.setattr(paths, "get_prepared_data_dir", lambda name: tmp_path / "prepared" / name)
    partitions(tmp_path, "AvesChilenas")
    with sessions() as db:
        db.add(Usuario(id=3, email="peer@example.test", password_hash=db.get(Usuario, 2).password_hash,
                       nombre_completo="Peer", rol="investigador", activo=True))
        db.commit()
    assign(client)
    with patch("app.services.training.threading.Thread"):
        response = client.post("/api/training/start", headers={"Origin": ORIGIN},
                               json={"dataset_name": "AvesChilenas", "epochs": 1})
    assert response.status_code == 200
    job_id = client.get("/api/training/progress").json()["job_id"]
    assert job_id
    assert login(client, "administrador").status_code == 200
    assert client.put("/api/access/users/3/datasets/10", headers={"Origin": ORIGIN}).status_code == 200
    assert client.post("/api/auth/login", headers={"Origin": ORIGIN},
                       json={"email": "peer@example.test", "password": PASSWORD}).status_code == 200
    assert client.get("/api/training/progress").status_code == 403
    assert client.post("/api/training/stop", headers={"Origin": ORIGIN}).status_code == 403
    assert login(client).status_code == 200
    assert client.get("/api/training/progress").json()["job_id"] == job_id
    assert client.post("/api/training/stop", headers={"Origin": ORIGIN}).status_code == 200
    assert login(client, "administrador").status_code == 200
    assert client.get("/api/training/progress").json()["job_id"] == job_id


def test_every_functional_operation_rejects_anonymous_requests(functional):
    client, _ = functional
    operations = []
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path.startswith(("/api/auth/", "/api/access/", "/api/users", "/api/security/")):
            continue
        path = path.replace("{dataset_name}", "AvesChilenas").replace("{model_id}", "1").replace("{id_retroalimentacion}", "1")
        for method in route.methods:
            response = client.request(method, path, headers={"Origin": ORIGIN})
            assert response.status_code == 401, (method, path, response.text)
            operations.append((method, path))
    assert len(operations) == 23


def test_sync_states_are_filtered_before_limit_and_ignore_unverified_legacy(functional):
    client, sessions = functional
    seed_predictions(sessions)
    with sessions() as db:
        for identifier, name in [(1, "AvesChilenas"), (2, "engine_diagnostics"), (3, "AvesChilenas")]:
            db.add(Retroalimentacion(id_retroalimentacion=identifier, id_prediccion=identifier,
                                     id_usuario=2, fue_correcta=True, procesado=True))
            db.flush()
            db.add(FeedbackSync(id_retroalimentacion=identifier, dataset_name=name, storage_class="fixture",
                               class_label="fixture", object_key=f"datasets/{name}/fixture/{identifier}.wav",
                               local_relative_path=f"{name}/fixture/{identifier}.wav", sha256="a" * 64))
        db.commit()
    assign(client)
    response = client.get("/api/feedback/sync?limit=1")
    assert response.status_code == 200
    assert [item["id_prediccion"] for item in response.json()] == [1]


def test_cached_model_cannot_borrow_access_from_stale_dataset_metadata(functional):
    from tests.test_api_predict import ContractPredictor
    client, sessions = functional
    with sessions() as db:
        db.add(Modelo(id_modelo=100, id_conjunto_datos=20, arquitectura="fixture", epocas=1,
                      tasa_aprendizaje=0.01, tamano_lote=2, ruta_binario_gcp="missing.pt"))
        db.commit()
    registry = ModelRegistry()
    predictor = ContractPredictor("fama_trained_model_100")
    predictor._metadata.dataset_name = "AvesChilenas"
    registry.register(predictor, is_default=True)
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    assign(client)
    assert client.get("/api/models").json()["models"] == []
    response = client.post("/api/predict", headers={"Origin": ORIGIN},
                           files={"file": ("fixture.wav", b"never executed", "audio/wav")})
    assert response.status_code == 404


def test_revocation_takes_effect_on_existing_cookie_without_relogin(functional, monkeypatch):
    from fastapi.testclient import TestClient
    client, _ = functional
    monkeypatch.setattr(main, "ingestion_service", SimpleNamespace(list_dataset_files=lambda *a, **k: []))
    assign(client)
    cookie = client.cookies.get("__Host-fama_session")
    assert client.get("/api/ingestion/datasets/AvesChilenas/files").status_code == 200
    with TestClient(client.app, base_url=ORIGIN) as administrator:
        assert login(administrator, "administrador").status_code == 200
        assert administrator.delete("/api/access/users/2/datasets/10", headers={"Origin": ORIGIN}).status_code == 204
    assert client.cookies.get("__Host-fama_session") == cookie
    assert client.get("/api/ingestion/datasets/AvesChilenas/files").status_code == 404


def test_unassigned_blocked_model_aliases_reveal_no_checkpoint_state(functional):
    client, sessions = functional
    with sessions() as db:
        db.add(Modelo(id_modelo=120, id_conjunto_datos=20, arquitectura="fixture", epocas=1,
                      tasa_aprendizaje=.01, tamano_lote=2, ruta_binario_gcp="models/private.pt", activo=True))
        db.commit()
        registry = ModelRegistry()
        registry.register_from_db(db)
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    assign(client)
    for alias in (None, "fama_trained_model_120", "120", "private.pt"):
        response = client.post("/api/predict", headers={"Origin":ORIGIN},
            params={} if alias is None else {"model_id":alias},
            files={"file":("fixture.wav",b"not executed","audio/wav")})
        assert response.status_code == 404
        assert response.json()["detail"] == "Modelo no encontrado o no asignado."


def test_incorporation_refuses_a_registered_dataset_in_another_bucket(functional, monkeypatch, tmp_path):
    from app.services import storage
    from tests.test_ingestion_upload_integrity import synthetic_wav
    client, sessions = functional
    monkeypatch.setattr(storage, "download_prediction_audio", lambda source: synthetic_wav())
    (tmp_path/"raw"/"AvesChilenas"/"Chucao").mkdir(parents=True)
    with sessions() as db:
        db.get(ConjuntoDatos,10).ruta_gcp = "gs://foreign-bucket/datasets/AvesChilenas/"
        db.add(Prediccion(id_prediccion=502, ruta_audio_prueba="raw_audios/synthetic.wav", etiqueta_predicha="Chucao", dataset_name="AvesChilenas", confianza=.8))
        db.flush()
        db.add(AccesoPrediccion(id_prediccion=502,id_conjunto_datos=10,id_usuario=2))
        db.commit()
    assign(client)
    created=client.post("/api/feedback",headers={"Origin":ORIGIN},json={"id_prediccion":502,"fue_correcta":True})
    identifier=created.json()["id_retroalimentacion"]
    response=client.post(f"/api/feedback/{identifier}/approve",headers={"Origin":ORIGIN})
    assert response.status_code == 422
    assert "almacenamiento" in response.json()["detail"]
    from app.models.dataset import Audio
    with sessions() as db:
        assert db.get(Retroalimentacion,identifier).procesado is False
        assert db.query(Audio).count() == 0
