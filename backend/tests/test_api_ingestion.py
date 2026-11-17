import sys
import io
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from tests.test_ingestion_upload_integrity import upload_environment
from tests.http_security import administrator_http
from app.database import get_db

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app


@pytest.fixture
def client(upload_environment):
    _, db, _ = upload_environment
    isolated = FastAPI()
    for route in app.routes:
        if getattr(route, 'path', '').startswith('/api/ingestion/'):
            isolated.add_api_route(route.path, route.endpoint, methods=list(route.methods))
    isolated.dependency_overrides[get_db] = lambda: db
    with administrator_http(isolated), TestClient(isolated) as test_client:
        yield test_client


def test_api_ingestion_status(client):
    """GET /api/ingestion/status retorna estado de GCS."""
    with patch("app.services.ingestion.ingestion_service.get_storage_status") as mock_status:
        mock_status.return_value = {
            "connected": True,
            "bucket": "fama-audio-records-2026",
            "total_objects": 10,
            "total_bytes": 102400,
            "error": None,
        }
        res = client.get("/api/ingestion/status")
        assert res.status_code == 200
        data = res.json()
        assert data["connected"] is True
        assert data["bucket"] == "fama-audio-records-2026"
        assert data["total_objects"] == 10


def test_api_ingestion_datasets(client):
    """GET /api/ingestion/datasets retorna lista de datasets disponibles."""
    with patch("app.services.ingestion.ingestion_service.list_datasets") as mock_list:
        mock_list.return_value = [
            {
                "id": "Chucao",
                "name": "Chucao",
                "file_count": 15,
                "total_size_bytes": 1500000,
                "last_modified": "2026-09-09T12:00:00Z",
                "local_file_count": 15,
                "is_synced": True,
            }
        ]
        res = client.get("/api/ingestion/datasets")
        assert res.status_code == 200
        data = res.json()
        assert "datasets" in data
        assert len(data["datasets"]) == 1
        assert data["datasets"][0]["name"] == "Chucao"


def test_api_ingestion_sync(client):
    """POST /api/ingestion/sync ejecuta la sincronización masiva de datasets."""
    with patch("app.services.ingestion.ingestion_service.sync_dataset_to_local") as mock_sync:
        mock_sync.return_value = {
            "dataset": "Chucao",
            "downloaded": 5,
            "skipped": 10,
            "failed": 0,
            "local_dir": "/tmp/Chucao",
            "files": [],
            "preprocessed": 0,
        }
        payload = {"datasets": ["Chucao"]}
        res = client.post("/api/ingestion/sync", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["total_downloaded"] == 5
        assert data["total_skipped"] == 10
        assert data["total_preprocessed"] == 0
        assert len(data["results"]) == 1


def test_api_ingestion_sync_with_preprocess(client):
    """POST /api/ingestion/sync con preprocess=True ejecuta la extracción tensorial (RF_03)."""
    with patch("app.services.ingestion.ingestion_service.sync_dataset_to_local") as mock_sync:
        mock_sync.return_value = {
            "dataset": "AvesChilenas",
            "downloaded": 8,
            "skipped": 2,
            "failed": 0,
            "local_dir": "/tmp/AvesChilenas",
            "files": [],
            "preprocessed": 8,
        }
        payload = {"datasets": ["AvesChilenas"], "preprocess": True}
        res = client.post("/api/ingestion/sync", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["total_downloaded"] == 8
        assert data["total_preprocessed"] == 8



def test_api_ingestion_upload(client):
    """POST /api/ingestion/upload permite subir archivos de audio a un dataset en GCS."""
    with patch("app.services.ingestion.ingestion_service.upload_files_to_gcs") as mock_upload:
        mock_upload.return_value = {
            "dataset": "Canastero",
            "uploaded": 1,
            "files": ["audio_prueba.wav"],
        }
        file_bytes = b"fake-wav-content"
        files = {"files": ("audio_prueba.wav", io.BytesIO(file_bytes), "audio/wav")}
        data = {"dataset_name": "Canastero"}
        res = client.post("/api/ingestion/upload", data=data, files=files)
        assert res.status_code == 200
        resp_data = res.json()
        assert resp_data["uploaded"] == 1
        assert resp_data["dataset"] == "Canastero"


# --- Background GCS -> local download (S7) ---------------------------------

import threading
import time
from types import SimpleNamespace

from app.services.access import ResourceAccess, resource_access
from app.services.dataset_download import DatasetDownloads


class GatedSync:
    def __init__(self):
        self.release = threading.Event()
        self.reported = threading.Event()
        self.calls = []

    def __call__(self, name, preprocess=False, db=None, progress=None):
        self.calls.append(name)
        progress({"total": 1220, "downloaded": 340, "skipped": 0, "failed": 0})
        self.reported.set()
        assert self.release.wait(5)
        return {"dataset": name, "downloaded": 1220, "skipped": 0, "failed": 0, "preprocessed": 0,
                "db_persisted": True, "db_error": None, "hash_conflicts": []}


@pytest.fixture
def downloads(monkeypatch):
    registry = DatasetDownloads()
    monkeypatch.setattr("app.main.dataset_downloads", registry)
    return registry


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_async_sync_start_reports_progress_then_the_terminal_summary(client, downloads):
    gate = GatedSync()
    with patch("app.services.ingestion.ingestion_service.sync_dataset_to_local", gate):
        started = client.post("/api/ingestion/sync/start", json={"datasets": ["AvesChilenas"]})
        # The isolated test app re-registers routes without their declared status code.
        assert next(r for r in app.routes if getattr(r, "path", "") == "/api/ingestion/sync/start").status_code == 202
        assert started.status_code in (200, 202)
        operation_id = started.json()["operation_id"]
        assert gate.reported.wait(5)

        running = client.get(f"/api/ingestion/sync/operations/{operation_id}").json()
        assert running["state"] == "running"
        assert (running["downloaded"], running["total"]) == (340, 1220)
        assert client.get("/api/ingestion/sync/active").json()["operations"][0]["operation_id"] == operation_id

        gate.release.set()
        assert wait_until(lambda: client.get(f"/api/ingestion/sync/operations/{operation_id}").json()["state"] != "running")
    done = client.get(f"/api/ingestion/sync/operations/{operation_id}").json()
    assert done["state"] == "completed"
    assert done["result"]["total_downloaded"] == 1220
    assert done["result"]["results"][0]["db_persisted"] is True
    assert client.get("/api/ingestion/sync/active").json() == {"operations": []}


def test_async_sync_start_rejects_a_dataset_already_downloading(client, downloads):
    gate = GatedSync()
    with patch("app.services.ingestion.ingestion_service.sync_dataset_to_local", gate):
        first = client.post("/api/ingestion/sync/start", json={"datasets": ["AvesChilenas"]})
        second = client.post("/api/ingestion/sync/start", json={"datasets": ["AvesChilenas"]})
        gate.release.set()
    assert second.status_code == 409
    assert second.json()["detail"]["operation_id"] == first.json()["operation_id"]
    assert wait_until(lambda: client.get("/api/ingestion/sync/active").json() == {"operations": []})


def test_async_sync_failure_ends_failed_not_running(client, downloads):
    from app.services.ingestion import IngestionDatasetUnavailable
    with patch("app.services.ingestion.ingestion_service.sync_dataset_to_local",
               side_effect=IngestionDatasetUnavailable("No downloadable cloud audio")):
        operation_id = client.post("/api/ingestion/sync/start", json={"datasets": ["Empty"]}).json()["operation_id"]
        assert wait_until(lambda: client.get(f"/api/ingestion/sync/operations/{operation_id}").json()["state"] == "failed")
    assert client.get(f"/api/ingestion/sync/operations/{operation_id}").json()["error"]


def test_async_sync_validates_names_and_requires_a_dataset(client, downloads):
    assert client.post("/api/ingestion/sync/start", json={"datasets": []}).status_code == 422
    assert client.post("/api/ingestion/sync/start", json={"datasets": ["../x"]}).status_code == 422
    assert client.get("/api/ingestion/sync/operations/missing").status_code == 404


def test_async_sync_is_only_visible_to_accounts_allowed_to_sync_the_dataset(client, downloads):
    gate = GatedSync()
    app_ = client.app
    with patch("app.services.ingestion.ingestion_service.sync_dataset_to_local", gate):
        operation_id = client.post("/api/ingestion/sync/start", json={"datasets": ["AvesChilenas"]}).json()["operation_id"]
        gate.release.set()
        researcher = object.__new__(ResourceAccess)
        researcher.administrator = False
        researcher.datasets = [SimpleNamespace(nombre="Chucao")]
        app_.dependency_overrides[resource_access] = lambda: researcher
        denied_start = client.post("/api/ingestion/sync/start", json={"datasets": ["AvesChilenas"]})
        denied_status = client.get(f"/api/ingestion/sync/operations/{operation_id}")
        active = client.get("/api/ingestion/sync/active")
        app_.dependency_overrides.pop(resource_access)
    assert denied_start.status_code == 404
    assert denied_status.status_code == 404
    assert active.json() == {"operations": []}


def test_synchronous_sync_endpoint_keeps_its_status_and_totals(client):
    results = iter([
        {"dataset": "A", "downloaded": 2, "skipped": 0, "failed": 1, "preprocessed": 0, "db_persisted": True},
    ])
    with patch("app.services.ingestion.ingestion_service.sync_dataset_to_local", lambda *a, **k: next(results)):
        data = client.post("/api/ingestion/sync", json={"datasets": ["A"]}).json()
    assert data["status"] == "partial"
    assert (data["total_downloaded"], data["total_failed"], data["total_skipped"], data["total_preprocessed"]) == (2, 1, 0, 0)
