import sys
import io
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
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
