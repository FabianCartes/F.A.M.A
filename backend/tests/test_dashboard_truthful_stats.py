"""Dashboard observations through public interfaces, with isolated data/hardware."""
from types import SimpleNamespace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.services.dashboard import DashboardService
from app.models.prediction import Prediccion
from app.models.training import Modelo, MetricaEntrenamiento


@pytest.fixture
def dashboard_environment(monkeypatch):
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    monkeypatch.setattr("psutil.cpu_percent", lambda **kwargs: 0.0)
    monkeypatch.setattr("psutil.cpu_count", lambda **kwargs: 2)
    monkeypatch.setattr("psutil.virtual_memory", lambda: SimpleNamespace(total=4 * 1024**3, used=1024**3, percent=25.0))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield DashboardService(), db
    finally:
        engine.dispose()


def test_empty_database_reports_zero_counts_without_inventing_metrics_or_activity(dashboard_environment):
    service, db = dashboard_environment

    stats = service.get_stats(db=db)

    assert stats["kpis"]["total_datasets"] == 0
    assert stats["kpis"]["total_audios"] == 0
    assert stats["kpis"]["total_predictions"] == 0
    assert stats["kpis"]["accuracy"] is None
    assert stats["kpis"]["loss"] is None
    assert stats["kpis"]["avg_confidence"] is None
    assert stats["training_curves"] == []
    assert stats["recent_activity"] == []


def test_missing_database_and_unprobed_services_are_unknown_not_healthy(dashboard_environment):
    service, _ = dashboard_environment

    stats = service.get_stats()

    assert stats["kpis"]["total_datasets"] is None
    assert stats["kpis"]["total_audios"] is None
    assert stats["kpis"]["total_predictions"] is None
    assert stats["system_health"]["database"] == "unknown"
    assert stats["system_health"]["storage"] == "unknown"
    assert stats["system_health"]["inference_engine"] == "unknown"
    assert stats["super_ensemble"]["ready"] is None
    assert stats["super_ensemble"]["models"] == []


def test_zero_metrics_and_single_recorded_epoch_are_preserved(dashboard_environment):
    service, db = dashboard_environment
    model = Modelo(arquitectura="Synthetic latest", epocas=1, tasa_aprendizaje=0.001, tamano_lote=2,
                   precision=0.0, perdida=0.0, ruta_binario_gcp="synthetic.pt", activo=False)
    db.add(model)
    db.flush()
    db.add(MetricaEntrenamiento(id_modelo=model.id_modelo, epoca=1, precision=0.0, perdida=0.0))
    db.add(Prediccion(ruta_audio_prueba="synthetic.wav", etiqueta_predicha="Chucao", confianza=0.0))
    db.commit()

    stats = service.get_stats(db=db)

    assert stats["kpis"]["accuracy"] == 0.0
    assert stats["kpis"]["loss"] == 0.0
    assert stats["kpis"]["avg_confidence"] == 0.0
    assert stats["kpis"]["total_predictions"] == 1
    assert stats["training_curves"] == [{"epoch": 1, "accuracy": 0.0, "loss": 0.0}]
    assert all(item["type"] != "ingesta" for item in stats["recent_activity"])


def test_metrics_remain_attributed_to_latest_record_not_inference_ensemble(dashboard_environment):
    service, db = dashboard_environment
    db.add(Modelo(arquitectura="Synthetic recorded model", epocas=1, tasa_aprendizaje=0.001, tamano_lote=2,
                  precision=12.0, perdida=0.5, ruta_binario_gcp="synthetic.pt", activo=False))
    db.commit()

    stats = service.get_stats(db=db, ensemble_status={"model_name": "Different inference ensemble", "ensemble_ready": False})

    assert stats["kpis"]["latest_model_name"] == "Synthetic recorded model"
    assert stats["kpis"]["metrics_source"] == "latest_registered_model"
    assert stats["kpis"]["active_model_name"] == "Synthetic recorded model"  # Legacy alias, not activation.
    assert stats["kpis"]["accuracy"] == 12.0


def test_model_with_unknown_metrics_does_not_break_database_health(dashboard_environment):
    service, db = dashboard_environment
    db.add(Modelo(arquitectura="Synthetic unknown metrics", epocas=1, tasa_aprendizaje=0.001, tamano_lote=2,
                  precision=None, perdida=None, ruta_binario_gcp="synthetic.pt"))
    db.commit()

    stats = service.get_stats(db=db)

    assert stats["system_health"]["database"] == "operational"
    assert stats["kpis"]["accuracy"] is None
    assert stats["kpis"]["loss"] is None
    assert "No disponible" in stats["recent_activity"][0]["description"]


def test_domain_records_are_marked_as_historical_not_live_telemetry(dashboard_environment):
    service, db = dashboard_environment

    stats = service.get_stats(db=db)

    assert stats["domain_champions"]["bioacoustic"]["source"] == "historical_reference"
    assert stats["domain_champions"]["industrial"]["source"] == "historical_reference"


def test_http_dashboard_does_not_load_or_probe_checkpoint_files(dashboard_environment, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    service, db = dashboard_environment
    probes = []
    original_exists = Path.exists

    def isolated_exists(path):
        if path.suffix == ".pt":
            probes.append(path.name)
            return False  # Never touch deployed weights, even on the old route.
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", isolated_exists)
    from app import main

    monkeypatch.setattr(main, "dashboard_service", service)
    app = FastAPI()
    app.add_api_route("/api/dashboard/stats", main.get_dashboard_stats, methods=["GET"])
    app.dependency_overrides[main.get_db] = lambda: db
    probes.clear()
    from tests.http_security import administrator_http
    with administrator_http(app), TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/dashboard/stats")

    assert response.status_code == 200
    assert probes == []
    assert response.json()["super_ensemble"]["ready"] is None


def test_prediction_activity_does_not_guess_domain_or_certainty(dashboard_environment):
    service, db = dashboard_environment
    db.add(Prediccion(ruta_audio_prueba="synthetic.wav", etiqueta_predicha="Unknown label", confianza=0.25,
                      modelo_id="unclassified-recorded-model", dataset_name=None))
    db.commit()

    stats = service.get_stats(db=db)

    prediction, = stats["recent_activity"]
    assert prediction["domain"] is None
    assert prediction["badge"] == "Inferencia"
    assert prediction["model_id"] == "unclassified-recorded-model"
    assert "25.0% de confianza" in prediction["description"]
    assert "certeza" not in prediction["description"]


def test_missing_hardware_telemetry_does_not_discard_valid_database_observations(dashboard_environment, monkeypatch):
    service, db = dashboard_environment

    def unavailable_memory():
        raise OSError("Synthetic hardware unavailable")

    monkeypatch.setattr("psutil.virtual_memory", unavailable_memory)

    stats = service.get_stats(db=db)

    assert stats["kpis"]["total_predictions"] == 0
    assert stats["system_health"]["database"] == "operational"
    assert stats["system_health"]["device"] == "unknown"


def test_database_failure_is_degraded_without_fabricated_data_and_can_retry(dashboard_environment):
    service, db = dashboard_environment
    engine = db.get_bind()

    def fail_database(conn, cursor, statement, parameters, context, executemany):
        raise OperationalError(statement, parameters, RuntimeError("synthetic-secret /private/database"))

    event.listen(engine, "before_cursor_execute", fail_database)
    try:
        stats = service.get_stats(db=db)
    finally:
        event.remove(engine, "before_cursor_execute", fail_database)

    assert stats["system_health"]["database"] == "degraded"
    assert stats["kpis"]["total_audios"] is None
    assert stats["training_curves"] == []
    assert stats["recent_activity"] == []
    assert "synthetic-secret" not in str(stats)
    retried = service.get_stats(db=db)
    assert retried["system_health"]["database"] == "operational"
    assert retried["kpis"]["total_audios"] == 0


def test_model_registration_event_does_not_claim_successful_training(dashboard_environment):
    service, db = dashboard_environment
    db.add(Modelo(arquitectura="Synthetic failed record", epocas=1, tasa_aprendizaje=0.001, tamano_lote=2,
                  precision=None, perdida=None, ruta_binario_gcp="synthetic.pt", estado="fallido"))
    db.commit()

    stats = service.get_stats(db=db)

    assert stats["recent_activity"][0]["title"] == "Modelo Synthetic failed record registrado"
