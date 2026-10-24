"""Public ASGI requests and worker operations without an HTTP-client dependency.

The guarded fixture uses SQLite memory and the direct synthetic validator, not
the production sandbox. Sandbox protocol and native containment are separate.
"""
import asyncio
import hashlib
import io
import json
import uuid
import zipfile
from types import SimpleNamespace

import pytest

from tests.test_dataset_zip_validation import archive, wav_bytes

BASE = "/api/ingestion/imports"


@pytest.fixture
def layout_api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.routes.dataset_imports import router, get_import_service, get_import_user
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_import_jobs import ImportJobQueue
    from app.services.dataset_import_execution import ImportExecution
    from app.services import dataset_import_execution
    from app.services.dataset_zip import ImportLimits, validate_zip
    from app.models import dataset_import_revision
    from scripts.migrate_dataset_import_jobs import migrate_jobs

    monkeypatch.setattr(dataset_import_execution, "validate_zip", validate_zip)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    migrate_jobs(engine, writers_stopped=True)
    sessions = sessionmaker(bind=engine)
    service = DatasetImports(tmp_path / "managed", limits=ImportLimits(free_bytes=1))
    app = FastAPI()
    app.include_router(router)

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_import_service] = lambda: service
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)

    def request(method, path, *, body=None, content=None):
        payload = json.dumps(body).encode() if body is not None else content or b""
        messages = []

        async def receive():
            return {"type": "http.request", "body": payload, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
            "method": method, "path": path, "raw_path": path.encode(), "query_string": b"",
            "scheme": "http", "server": ("synthetic.test", 80), "client": ("127.0.0.1", 1),
            "headers": [(b"content-type", b"application/json" if body is not None else b"application/zip")]}
        asyncio.run(app(scope, receive, send))
        data = b"".join(message.get("body", b"") for message in messages)
        return SimpleNamespace(status_code=messages[0]["status"], content=data,
            json=lambda: json.loads(data))

    (tmp_path / "attempts").mkdir(mode=0o700)
    worker = ImportExecution(ImportJobQueue(sessions), service, tmp_path / "attempts")
    yield request, worker, engine
    engine.dispose()


def upload(request, tmp_path, entries, *, layout="class_folders"):
    body = {"request_key": "source", "name": "Synthetic", "target_id": None}
    if layout is not None:
        body["layout"] = layout
    response = request("POST", BASE, body=body)
    assert response.status_code == 200, response.content
    source = response.json()["id"]
    original = archive(tmp_path / "source.zip", entries).read_bytes()
    assert request("PUT", f"{BASE}/{source}/archive", content=original).status_code == 200
    return source, original


def operation(request, worker, source, kind, **parameters):
    admitted = request("POST", f"{BASE}/{source}/{kind}", body={"request_key": uuid.uuid4().hex, **parameters})
    assert admitted.status_code == 202, admitted.content
    assert worker.run_once()
    assert request("GET", admitted.json()["status_url"]).json()["status"] == "succeeded"
    return request("GET", f"{BASE}/{source}").json()


@pytest.mark.parametrize("entry", ["aves/chucao/a.wav", "chucao/session/a.wav", "chucao/empty/"])
def test_new_import_rejects_nested_paths_and_cannot_override_fixed_root(layout_api, tmp_path, entry):
    request, worker, engine = layout_api
    source, original = upload(request, tmp_path, [("valid/a.wav", wav_bytes(2)),
        (entry, b"" if entry.endswith("/") else wav_bytes())])
    with engine.connect() as db:
        before = "\n".join(db.connection.driver_connection.iterdump())
    rejected = request("POST", f"{BASE}/{source}/preview", body={"request_key": "override", "root": "aves"})
    assert rejected.status_code == 422
    with engine.connect() as db:
        assert "\n".join(db.connection.driver_connection.iterdump()) == before
    result = operation(request, worker, source, "preview", root="")
    assert result["status"] == "needs_correction"
    assert result["preview"]["layout"] == "class_folders"
    assert result["preview"]["error_count"] == 1
    assert result["issue_sample"] == [{"path": entry, "code": "class_folders_required", "severity": "error",
        "action": "Organiza el ZIP como clase/audio.wav, sin carpeta contenedora ni subcarpetas."}]
    assert request("POST", f"{BASE}/{source}/confirm", body={"request_key": "blocked",
        "preview_token": result["preview_token"]}).status_code == 409
    assert request("GET", BASE + "/datasets").json()["datasets"] == []
    assert (tmp_path / "source.zip").read_bytes() == original


def test_new_import_preserves_single_class_history_and_original_audio(layout_api, tmp_path):
    request, worker, _ = layout_api
    source, _ = upload(request, tmp_path, [("chucao/", b""), ("chucao/a.wav", wav_bytes())])
    preview = operation(request, worker, source, "preview", root="")
    assert preview["status"] == "ready"
    assert preview["preview"]["root"] == "" and preview["preview"]["layout"] == "class_folders"
    recovered = request("GET", BASE).json()["imports"][0]
    assert recovered["preview_token"] == preview["preview_token"]
    result = operation(request, worker, source, "confirm", preview_token=recovered["preview_token"])
    assert result["status"] == "imported" and result["added_count"] == 1 and result["sync_status"] == "pending"
    files = request("GET", f"{BASE}/datasets/{result['dataset_id']}/files").json()["files"]
    assert [(file["class_name"], file["original_path"]) for file in files] == [("chucao", "chucao/a.wav")]
    assert files[0]["sha256"] == hashlib.sha256(wav_bytes()).hexdigest()
    downloaded = request("GET", f"{BASE}/datasets/{result['dataset_id']}/files/{files[0]['sha256']}")
    assert downloaded.status_code == 200 and downloaded.content == wav_bytes()


def test_unmarked_legacy_request_keeps_selected_root_sessions_and_replay(layout_api, tmp_path):
    request, worker, _ = layout_api
    source, _ = upload(request, tmp_path, [("aves/chucao/session/a.wav", wav_bytes())], layout=None)
    replay = request("POST", BASE, body={"request_key": "source", "name": "Synthetic", "target_id": None})
    assert replay.status_code == 200 and replay.json()["id"] == source
    preview = operation(request, worker, source, "preview", root="aves")
    assert preview["status"] == "ready" and preview["preview"]["root"] == "aves"
    result = operation(request, worker, source, "confirm", preview_token=preview["preview_token"])
    files = request("GET", f"{BASE}/datasets/{result['dataset_id']}/files").json()["files"]
    assert [(file["class_name"], file["relative_path"]) for file in files] == [("chucao", "chucao/session/a.wav")]


def test_downloadable_example_matches_new_layout(layout_api):
    request, _, _ = layout_api
    response = request("GET", BASE + "/example.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as example:
        assert example.namelist() == ["chucao/audio_01.wav", "colilarga/audio_01.wav"]
