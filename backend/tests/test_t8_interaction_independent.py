"""S8: independent receipt-prefix to manifest-only download interaction."""
import hashlib
import io
import shutil
import zipfile
from tests.test_dataset_import_api import imports, operation, confirm
from tests.test_dataset_import_manifests import ManifestObjects
from tests.test_dataset_zip_validation import archive, wav_bytes
from tests.test_t8_independent import state

BASE = "/api/ingestion/imports"

def test_resume_publish_sync_and_export_without_local_sources(imports, tmp_path, monkeypatch):
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    from app.routes.dataset_imports import get_import_storage
    from app.routes.dataset_exports import get_export_queue
    from app.services.dataset_exports import ExportQueue, ExportExecution
    client, service, app, sessions = imports
    for migrate in (migrate_receipts, migrate_chunks):
        migrate(sessions.kw["bind"], writers_stopped=True)
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", "4096")
    monkeypatch.setenv("FAMA_EXPORT_DOWNLOAD_ORIGIN", "https://downloads.example.test")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("FAMA_EXPORT_ROOT", str(root))
    expected = {f"birds/{i}.wav": wav_bytes(i + 1) for i in range(61)}
    path = archive(tmp_path / "input.zip", expected.items())
    data = path.read_bytes()
    job = client.post(BASE, json={"request_key": "own-integral", "name": "Independent"}).json()
    url = f"{BASE}/{job['id']}/receipt"
    assert client.post(url, json={"name": "input.zip", "size_bytes": len(data)}).status_code == 200
    def put(index, block):
        return client.put(f"{url}/chunks/{index}", content=block, headers={"Content-Type": "application/octet-stream",
            "X-Chunk-Offset": str(index * 4096), "X-Chunk-SHA256": hashlib.sha256(block).hexdigest()})
    assert put(0, data[:4096]).status_code == 200
    before = state(sessions)
    assert put(0, b"x" * 4096).status_code == 409
    assert state(sessions) == before
    prefix = client.get(url + "/chunks").json()["chunks"]
    assert len(prefix) == 1 and prefix[0]["sha256"] == hashlib.sha256(data[:4096]).hexdigest()
    for start in range(4096, len(data), 4096):
        assert put(start // 4096, data[start:start + 4096]).status_code == 200
    assert client.post(url + "/finalize").status_code == 200
    ready = operation(client, job["id"], "preview", {"root": ""}).json()
    assert client.get(BASE + "/datasets").json()["total"] == 0
    result = confirm(client, ready).json()
    assert result["added_count"] == 61 and result["sync_status"] == "pending"
    storage = ManifestObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    assert operation(client, job["id"], "sync").json()["sync_status"] == "synced"
    revision = f"{BASE}/datasets/{result['dataset_id']}/revisions/1"
    reference = client.get(revision).json()
    assert reference["status"] == "complete" and reference["file_count"] == 61
    shutil.rmtree(service.root / "objects" / job["id"])
    shutil.rmtree(service.root / "staging" / job["id"])
    path.unlink()
    queue = ExportQueue(sessions, service)
    app.dependency_overrides[get_export_queue] = lambda: queue
    admitted = client.post(revision + "/exports", json={"request_key": "own-export"})
    assert admitted.status_code == 202
    assert ExportExecution(queue, root, storage=storage).run_once()
    status_url = admitted.json()["status_url"]
    assert client.get(status_url).json()["status"] == "succeeded"
    download = client.get(client.post(status_url + "/sessions").json()["url"])
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as z:
        assert set(z.namelist()) == {"Independent/" + name for name in expected}
        for name, value in expected.items():
            assert z.read("Independent/" + name) == value
    for start, end in ((0, 0), (1, 50), (51, 100)):
        response = client.get(str(download.url), headers={"Range": f"bytes={start}-{end}"})
        assert response.status_code == 206 and response.content == download.content[start:end + 1]
    assert client.get(revision).json() == reference
    print("S8_INTERACTION members=61 resumed_prefix=4096 native_ranges=3 original_bytes=identical")
