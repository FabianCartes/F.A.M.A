"""Legacy public ingestion must not traverse into the new private import store."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    from app import main
    from app.services.ingestion import IngestionService
    raw = tmp_path / "raw"
    raw.mkdir()
    private = tmp_path / "dataset-imports" / "objects" / "private-job" / "birds"
    private.mkdir(parents=True)
    from tests.test_dataset_zip_validation import wav_bytes
    (private / "private.wav").write_bytes(wav_bytes())
    public = raw / "Public" / "birds"
    public.mkdir(parents=True)
    (public / "public.wav").write_bytes(wav_bytes(2))
    service = IngestionService(local_base_dir=raw, local_processed_dir=tmp_path / "processed")
    def offline():
        raise RuntimeError("Synthetic offline storage")
    monkeypatch.setattr(service, "_get_client", offline)
    monkeypatch.setattr(main, "ingestion_service", service)
    with_db = main.app.dependency_overrides.copy()
    from app.database import get_db
    main.app.dependency_overrides[get_db] = lambda: None
    client = TestClient(main.app, raise_server_exceptions=False)
    from tests.http_security import administrator_http
    with administrator_http(main.app):
        yield client
    client.close()
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides.update(with_db)


def test_legacy_file_listing_cannot_discover_private_imports_through_parent_reference(legacy):
    response = legacy.get("/api/ingestion/datasets/%2e%2e/files")
    assert response.status_code in (400, 422)
    assert "private" not in response.text
    assert legacy.get("/api/ingestion/datasets/Public/files").json()["files"][0]["name"] == "public.wav"


@pytest.mark.parametrize("name", ["..", "../dataset-imports", "/absolute", "birds\\session", "", "."])
def test_legacy_sync_rejects_invalid_destinations_before_side_effects(legacy, name):
    response = legacy.post("/api/ingestion/sync", json={"datasets": ["Public", name], "preprocess": True})
    assert response.status_code == 422
