import sys
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import get_dashboard_stats
from app.database import get_db
from app.models.prediction import Prediccion
from app.services.dashboard import DashboardService
from tests.test_dashboard_truthful_stats import dashboard_environment


@pytest.fixture
def client(dashboard_environment):
    _, db = dashboard_environment
    app = FastAPI()
    app.add_api_route("/api/dashboard/stats", get_dashboard_stats, methods=["GET"])
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


def test_get_dashboard_stats_endpoint(client):
    """GET /api/dashboard/stats retorna estructura completa de métricas MLOps."""
    res = client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.json()

    # Estructura principal
    assert "kpis" in data
    assert "training_curves" in data
    assert "recent_activity" in data
    assert "super_ensemble" in data
    assert "system_health" in data

    # KPIs esperados
    kpis = data["kpis"]
    assert "accuracy" in kpis
    assert "loss" in kpis
    assert "total_datasets" in kpis
    assert "total_audios" in kpis
    assert "total_predictions" in kpis
    assert "avg_confidence" in kpis
    assert "active_model_name" in kpis

    # Curvas de entrenamiento
    assert isinstance(data["training_curves"], list)
    if len(data["training_curves"]) > 0:
        c0 = data["training_curves"][0]
        assert "epoch" in c0
        assert "accuracy" in c0
        assert "loss" in c0

    # Actividad reciente
    assert isinstance(data["recent_activity"], list)

    # Super ensamble
    ens = data["super_ensemble"]
    assert "ready" in ens
    assert "active_mode" in ens
    assert "models" in ens
    assert isinstance(ens["models"], list)

    # Salud del sistema
    health = data["system_health"]
    assert "database" in health
    assert "storage" in health
    assert "inference_engine" in health


def test_dashboard_service_aggregation(dashboard_environment):
    """Valida la agregación de KPIs y cálculo de confianza promedio en DashboardService."""
    service = DashboardService()
    _, db = dashboard_environment

    # Simular Predicciones
    db.add_all([
        Prediccion(etiqueta_predicha="Chucao", confianza=0.95, ruta_audio_prueba="chucao.wav"),
        Prediccion(etiqueta_predicha="Chercán", confianza=0.85, ruta_audio_prueba="chercan.wav"),
    ])
    db.commit()

    # Invocar get_stats
    stats = service.get_stats(db=db)

    assert "kpis" in stats
    assert stats["kpis"]["total_predictions"] >= 0
    assert stats["system_health"]["database"] in ["connected", "operational", "degraded"]
    assert stats["kpis"]["total_predictions"] == 2
    assert stats["kpis"]["avg_confidence"] == 90.0
