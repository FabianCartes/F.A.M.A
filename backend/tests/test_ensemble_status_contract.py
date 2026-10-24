"""Passive ensemble observations, never deployed assets or production lifespan."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import torch
import timm
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

with patch.dict(os.environ, {"DATABASE_URL": "sqlite://", "PYTHON_DOTENV_DISABLED": "1"}), \
        patch("dotenv.load_dotenv", return_value=False), patch("sqlalchemy.MetaData.create_all"):
    from app import main
from app.database import Base
from app.services import training
from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo
from poc.train import BioacousticModel
from tests.test_checkpoint_pooling_contract import PooledClassifier
from tests.test_api_predict import client, controlled_registry, mock_db_session, create_dummy_wav_bytes, ContractPredictor
from unittest.mock import AsyncMock


@pytest.fixture
def status_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(main, "_BACKEND_ROOT", tmp_path / "backend")
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: tmp_path / "raw" / (name or ""))
    checkpoints = tmp_path / "weights"
    checkpoints.mkdir()
    service = main.SuperEnsembleService(checkpoints_dir=checkpoints)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield service, db, checkpoints
    finally:
        engine.dispose()


def test_status_observes_present_file_without_deserializing_or_loading_it(status_environment, monkeypatch):
    service, db, checkpoints = status_environment
    (checkpoints / "efficientnet_gpu_pipeline_35e_best.pt").write_bytes(b"synthetic content not deserialized")

    def no_checkpoint_load(*args, **kwargs):
        raise AssertionError("A status read must never deserialize checkpoints")

    monkeypatch.setattr(torch, "load", no_checkpoint_load)

    result = service.get_status(db=db)

    row = next(item for item in result["triad_status"] if item["name"] == "EfficientNet-B0")
    assert row["weights_available"] is True
    assert row["is_loaded"] is False
    assert row["is_ready"] is False
    assert result["ensemble_ready"] is False
    assert result["active_mode"] == "unavailable"
    assert result["is_fallback"] is False
    assert result["active_models"] == []


def test_three_database_records_do_not_mean_a_loaded_ensemble(status_environment):
    service, db, _ = status_environment
    dataset = ConjuntoDatos(nombre="AvesChilenas", ruta_gcp="gs://fixture/datasets/AvesChilenas/")
    db.add(dataset)
    db.flush()
    for architecture in ("EfficientNet-B0", "ConvNeXt-Nano", "ResNet-34d"):
        db.add(Modelo(id_conjunto_datos=dataset.id_conjunto_datos, arquitectura=architecture, epocas=1,
                      tasa_aprendizaje=0.001, tamano_lote=2, precision=0.0, perdida=0.0,
                      ruta_binario_gcp=f"models/{architecture}.pt"))
    db.commit()

    result = service.get_status(db=db)

    assert result["ensemble_ready"] is False
    assert result["active_mode"] == "unavailable"
    for row in result["triad_status"]:
        assert row["is_registered"] is True
        assert row["is_loaded"] is False
        assert row["is_ready"] is False
        assert row["accuracy"] == 0.0
        assert row["loss"] == 0.0


def test_explicitly_loaded_model_reports_memory_state_not_invented_metrics(status_environment, monkeypatch):
    service, db, checkpoints = status_environment
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False, pool_type="avg")
    torch.save({"model_type": "fixture", "classes": ["Positive", "Negative"], "pool_type": "avg",
                "model_state_dict": model.state_dict()}, checkpoints / "efficientnet_gpu_pipeline_35e_best.pt")
    service.load_models()  # Explicit public operation, synthetic artifact only.

    result = service.get_status(db=db)

    row = next(item for item in result["triad_status"] if item["name"] == "EfficientNet-B0")
    assert row["is_loaded"] is True
    assert row["is_ready"] is True  # Legacy alias for observed load, not inference proof.
    assert row["is_registered"] is False
    assert row["accuracy"] is None
    assert row["loss"] is None
    assert row["weight"] == 1.0
    assert result["active_mode"] == "individual"
    assert result["active_models"][0]["weight"] == 1.0


@pytest.mark.parametrize("route,present,expected", [("models/custom.pt", True, True),
                                                  ("models/missing.pt", False, False),
                                                  ("gs://fixture/models/remote.pt", False, None)])
def test_registered_artifact_availability_is_local_observation_not_registration(status_environment, route, present, expected):
    service, db, checkpoints = status_environment
    dataset = ConjuntoDatos(nombre="AvesChilenas", ruta_gcp="gs://fixture/datasets/AvesChilenas/")
    db.add(dataset)
    db.flush()
    db.add(Modelo(id_conjunto_datos=dataset.id_conjunto_datos, arquitectura="EfficientNet-B0", epocas=1,
                  tasa_aprendizaje=0.001, tamano_lote=2, precision=12.0, perdida=0.5, ruta_binario_gcp=route))
    db.commit()
    if present:
        (checkpoints / "custom.pt").write_bytes(b"nonempty synthetic artifact not deserialized")

    result = service.get_status(db=db)

    row = next(item for item in result["triad_status"] if item["name"] == "EfficientNet-B0")
    assert row["is_registered"] is True
    assert row["weights_available"] is expected
    assert row["is_loaded"] is False


def test_loaded_bioacoustic_service_does_not_claim_foreign_domain_models(status_environment, monkeypatch):
    service, db, checkpoints = status_environment
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False, pool_type="avg")
    torch.save({"model_type": "fixture", "classes": ["Positive", "Negative"], "pool_type": "avg",
                "model_state_dict": model.state_dict()}, checkpoints / "efficientnet_gpu_pipeline_35e_best.pt")
    service.load_models()

    result = service.get_status(dataset_name="engine_diagnostics", db=db)

    assert result["domain_supported"] is False
    assert result["state_scope"] == "legacy_bioacoustic_service"
    assert result["active_models"] == []
    assert result["triad_status"] == []
    assert result["classes"] == []


def test_bird_status_does_not_borrow_unrelated_dataset_record(status_environment):
    service, db, _ = status_environment
    engine_dataset = ConjuntoDatos(nombre="engine_diagnostics", ruta_gcp="gs://fixture/datasets/engine_diagnostics/")
    db.add(engine_dataset)
    db.flush()
    db.add(Modelo(id_conjunto_datos=engine_dataset.id_conjunto_datos, arquitectura="EfficientNet-B0", epocas=1,
                  tasa_aprendizaje=0.001, tamano_lote=2, precision=80.0, perdida=0.5,
                  clase_objetivo="AvesChilenas text is not a dataset association", ruta_binario_gcp="models/engine.pt"))
    db.commit()

    result = service.get_status(dataset_name="AvesChilenas", db=db)

    row = next(item for item in result["triad_status"] if item["name"] == "EfficientNet-B0")
    assert row["is_registered"] is False
    assert row["accuracy"] is None
    assert row["checkpoint"] is None


def test_loaded_and_registered_checkpoint_origins_are_not_silently_merged(status_environment, monkeypatch):
    service, db, checkpoints = status_environment
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False, pool_type="avg")
    torch.save({"model_type": "fixture", "classes": ["Positive", "Negative"], "pool_type": "avg",
                "model_state_dict": model.state_dict()}, checkpoints / "efficientnet_gpu_pipeline_35e_best.pt")
    service.load_models()
    dataset = ConjuntoDatos(nombre="AvesChilenas", ruta_gcp="gs://fixture/datasets/AvesChilenas/")
    db.add(dataset)
    db.flush()
    db.add(Modelo(id_conjunto_datos=dataset.id_conjunto_datos, arquitectura="EfficientNet-B0", epocas=1,
                  tasa_aprendizaje=0.001, tamano_lote=2, precision=12.0, perdida=0.5,
                  ruta_binario_gcp="models/different-recorded.pt"))
    db.commit()

    result = service.get_status(db=db)

    row = next(item for item in result["triad_status"] if item["name"] == "EfficientNet-B0")
    assert row["recorded_checkpoint"] == "different-recorded.pt"
    assert row["loaded_checkpoint"] == "efficientnet_gpu_pipeline_35e_best.pt"
    assert row["metrics_source"] == "database_record"
    assert row["accuracy"] == 12.0


def test_prediction_response_attributes_execution_to_predictor_not_legacy_ensemble(client, status_environment, monkeypatch):
    service, _, checkpoints = status_environment
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False, pool_type="avg")
    torch.save({"model_type": "fixture", "classes": ["Positive", "Negative"], "pool_type": "avg",
                "model_state_dict": model.state_dict()}, checkpoints / "efficientnet_gpu_pipeline_35e_best.pt")
    service.load_models()
    monkeypatch.setattr(main, "ensemble_service", service)
    monkeypatch.setattr(main, "upload_audio_to_gcp", AsyncMock(return_value=True))

    response = client.post("/api/predict", files={"file": ("synthetic.wav", create_dummy_wav_bytes(), "audio/wav")})

    assert response.status_code == 200
    assert response.json()["modelo_id"] == "contract-birds"
    assert response.json()["modelos_activos"] is None
    assert response.json()["modelos_ejecutados"] == ["HTTP contract fixture"]


def test_reported_fallback_role_is_not_erased_by_nonmock_annotation(client, controlled_registry, monkeypatch):
    class ReportedFallback(ContractPredictor):
        def __init__(self):
            super().__init__("reported-fallback")
            self.is_fallback = True

        def predict(self, path):
            result = super().predict(path)
            result.detalles["is_mock"] = False  # Contract observation, not a real benchmark.
            return result

    controlled_registry.register(ReportedFallback(), is_default=True)
    monkeypatch.setattr(main, "upload_audio_to_gcp", AsyncMock(return_value=True))

    response = client.post("/api/predict", files={"file": ("synthetic.wav", create_dummy_wav_bytes(), "audio/wav")})

    assert response.status_code == 200
    assert response.json()["modelo_id"] == "reported-fallback"
    assert response.json()["is_fallback"] is True


@pytest.mark.parametrize("count", [2, 3])
def test_observed_ensemble_count_and_normalized_weights_come_from_loaded_modules(status_environment, monkeypatch, count):
    service, db, checkpoints = status_environment
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False, pool_type="avg")
    for filename in ["efficientnet_gpu_pipeline_35e_best.pt", "convnext_nano_35e_best.pt", "resnet34d_35e_best.pt"][:count]:
        torch.save({"model_type": "fixture", "classes": ["Positive", "Negative"], "pool_type": "avg",
                    "model_state_dict": model.state_dict()}, checkpoints / filename)
    service.load_models()

    result = service.get_status(db=db)

    assert sum(row["is_loaded"] for row in result["triad_status"]) == count
    assert result["ensemble_ready"] is (count == 3)
    assert result["active_mode"] == ("ensemble" if count == 3 else "partial_ensemble")
    assert len(result["active_models"]) == count
    assert sum(row["weight"] for row in result["active_models"]) == pytest.approx(1.0)
    assert all(row["accuracy"] is None for row in result["triad_status"])


def test_model_info_http_is_passive_and_does_not_claim_a_default_fallback(status_environment, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    service, db, checkpoints = status_environment
    (checkpoints / "efficientnet_gpu_pipeline_35e_best.pt").write_bytes(b"present but not validated")
    monkeypatch.setattr(main, "ensemble_service", service)

    def forbid_load(*args, **kwargs):
        raise AssertionError("GET model-info must not load a model")

    monkeypatch.setattr(torch, "load", forbid_load)
    app = FastAPI()
    app.add_api_route("/api/model-info", main.get_model_info, methods=["GET"])
    app.dependency_overrides[main.get_db] = lambda: db
    from tests.http_security import administrator_http
    with administrator_http(app), TestClient(app) as http:
        response = http.get("/api/model-info")

    assert response.status_code == 200
    result = response.json()
    assert result["state_scope"] == "legacy_bioacoustic_service"
    assert result["active_mode"] == "unavailable"
    assert result["is_fallback"] is False
    assert result["model_name"] is None
    assert result["active_models"] == []


def test_untrusted_absolute_artifact_is_not_resolved_outside_configured_roots(status_environment, monkeypatch):
    service, db, checkpoints = status_environment
    outside = checkpoints.parent / "outside.pt"
    outside.write_bytes(b"not an authorized checkpoint location")
    dataset = ConjuntoDatos(nombre="AvesChilenas", ruta_gcp="gs://fixture/datasets/AvesChilenas/")
    db.add(dataset)
    db.flush()
    db.add(Modelo(id_conjunto_datos=dataset.id_conjunto_datos, arquitectura="EfficientNet-B0", epocas=1,
                  tasa_aprendizaje=0.001, tamano_lote=2, ruta_binario_gcp=str(outside)))
    db.commit()
    original_resolve = Path.resolve

    def no_outside_resolution(path, *args, **kwargs):
        if path == outside:
            raise AssertionError("Do not inspect an absolute path outside configured roots")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", no_outside_resolution)

    result = service.get_status(db=db)

    row = next(item for item in result["triad_status"] if item["name"] == "EfficientNet-B0")
    assert row["is_registered"] is True
    assert row["weights_available"] is None


@pytest.mark.parametrize("with_checkpoint", [False, True])
def test_fallback_requires_an_observed_model_not_only_a_flag(status_environment, with_checkpoint):
    from poc.train import AudioCNN

    service, db, checkpoints = status_environment
    if with_checkpoint:
        torch.save({"classes": ["Positive", "Negative"], "model_state_dict": AudioCNN(num_classes=2).state_dict()},
                   checkpoints / "augmented_best.pt")
    service.load_models()

    result = service.get_status(db=db)

    assert result["is_fallback"] is with_checkpoint
    assert result["active_mode"] == ("fallback" if with_checkpoint else "unavailable")
    assert bool(result["active_models"]) is with_checkpoint
    assert result["ensemble_ready"] is False


def test_removed_backing_file_does_not_erase_observed_loaded_memory(status_environment, monkeypatch):
    service, db, checkpoints = status_environment
    monkeypatch.setattr(timm, "create_model", lambda *args, **kwargs: PooledClassifier())
    model = BioacousticModel("fixture", num_classes=2, pretrained=False, pool_type="avg")
    path = checkpoints / "efficientnet_gpu_pipeline_35e_best.pt"
    torch.save({"model_type": "fixture", "classes": ["Positive", "Negative"], "pool_type": "avg",
                "model_state_dict": model.state_dict()}, path)
    service.load_models()
    path.unlink()  # Only the synthetic test artifact.

    result = service.get_status(db=db)

    row = next(item for item in result["triad_status"] if item["name"] == "EfficientNet-B0")
    assert row["is_loaded"] is True
    assert row["weights_available"] is False
    assert row["loaded_checkpoint"] == path.name


def test_database_failure_does_not_turn_unknown_registration_into_absence(status_environment):
    service, db, checkpoints = status_environment
    (checkpoints / "efficientnet_gpu_pipeline_35e_best.pt").write_bytes(b"present candidate")
    engine = db.get_bind()

    def fail_database(conn, cursor, statement, parameters, context, executemany):
        raise OperationalError(statement, parameters, RuntimeError("synthetic-secret /private/database"))

    event.listen(engine, "before_cursor_execute", fail_database)
    try:
        result = service.get_status(db=db)
    finally:
        event.remove(engine, "before_cursor_execute", fail_database)

    row = next(item for item in result["triad_status"] if item["name"] == "EfficientNet-B0")
    assert row["is_registered"] is None
    assert row["weights_available"] is True
    assert row["is_loaded"] is False
    assert "synthetic-secret" not in str(result)
    retry = service.get_status(db=db)
    assert retry["triad_status"][0]["is_registered"] is False
