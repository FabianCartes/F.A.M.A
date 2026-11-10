import asyncio, hashlib, json
from types import SimpleNamespace
from tests.test_dataset_import_layout import layout_api
from tests.s12_probe_support import *

def test_automatic_receipt_release_and_duplicate_replay(layout_api, tmp_path):
    from fastapi import FastAPI
    from app.database import get_db
    from app.routes.dataset_imports import router, get_import_service, get_import_user
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    request, worker, engine = layout_api
    migrate_receipts(engine, writers_stopped=True)
    migrate_chunks(engine, writers_stopped=True)
    app = FastAPI()
    app.include_router(router)
    def db():
        with worker.queue.sessions() as session: yield session
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_import_service] = lambda: worker.service
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    audio = wav_bytes()
    data = archive(tmp_path / "receipt.zip", [("bird/a.wav", audio), ("bird/copy.wav", audio)]).read_bytes()
    datasets = []
    for index in range(2):
        creation = {"request_key": f"receipt-{index}", "name": f"Dataset-{index}", "layout": "class_folders", "auto_import": True}
        created = request("POST", B, body=creation)
        assert created.status_code == 200
        source = created.json()["id"]
        response = request("POST", f"{B}/{source}/receipt", body={"name": "receipt.zip", "size_bytes": len(data)})
        assert response.status_code == 200 and response.json()["reserved_bytes"] > len(data)
        messages = []
        async def receive(): return {"type": "http.request", "body": data, "more_body": False}
        async def send(message): messages.append(message)
        path = f"{B}/{source}/receipt/chunks/0"
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1", "method": "PUT", "path": path, "raw_path": path.encode(), "query_string": b"", "scheme": "http", "server": ("synthetic.test", 80), "client": ("127.0.0.1", 1), "headers": [(b"content-type", b"application/octet-stream"), (b"x-chunk-offset", b"0"), (b"x-chunk-sha256", hashlib.sha256(data).hexdigest().encode())]}
        asyncio.run(app(scope, receive, send))
        assert messages[0]["status"] == 200
        assert request("POST", f"{B}/{source}/receipt/finalize").status_code == 200
        job, operation = admit(request, source)
        assert worker.run_once()
        result = state(request, source)
        assert result["status"] == "imported" and result["sync_status"] == "pending"
        assert result["added_count"] == (1 if index == 0 else 0)
        datasets.append(result["dataset_id"])
        assert request("GET", job["status_url"]).json()["kind"] == "preview"
        assert request("GET", job["status_url"]).json()["status"] == "succeeded"
        assert request("GET", f"{B}/{source}/receipt").json()["reserved_bytes"] == 0
        assert request("POST", B, body=creation).json() == result
        assert request("POST", f"{B}/{source}/preview", body=operation).json()["id"] == job["id"]
        assert not worker.run_once()
    assert datasets[0] == datasets[1]
    catalog = request("GET", B + "/datasets").json()["datasets"]
    assert [(d["revision"], d["file_count"], d["total_size_bytes"]) for d in catalog] == [(1, 1, len(audio))]
    files = request("GET", f"{B}/datasets/{datasets[0]}/files").json()["files"]
    assert len(files) == 1
    assert request("GET", f"{B}/datasets/{datasets[0]}/files/{files[0]["sha256"]}").content == audio
    assert worker.storage is None
    assert worker.queue.active_counts(1) == {"global": 0, "owner": 0}
