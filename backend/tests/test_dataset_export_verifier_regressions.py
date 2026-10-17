"""Public T7 regressions reproduced by independent verification."""
import hashlib
import io
import json
import shutil
import zipfile

import pytest

from tests.test_dataset_import_api import imports, prepare, confirm, operation  # noqa: F401
from tests.test_dataset_exports import exported_source, completed  # noqa: F401
from tests.test_dataset_import_manifests import ManifestObjects
from tests.test_dataset_zip_validation import wav_bytes


def database_hash(sessions):
    with sessions() as db:
        connection = db.connection().connection.driver_connection
        data = "\n".join(connection.iterdump()).encode()
        return hashlib.sha256(data).hexdigest()


def native_session(source, tmp_path):
    client = source[0]
    _, _, job = completed(source, tmp_path)
    ticket_url = client.post(job["status_url"] + "/sessions").json()["url"]
    response = client.get(ticket_url)
    assert response.status_code == 200
    return client, ticket_url, str(response.url)


def test_rejected_range_preserves_database(exported_source, tmp_path):
    client, _, url = native_session(exported_source, tmp_path)
    sessions = exported_source[3]
    before = database_hash(sessions)
    response = client.get(url, headers={"Range": "bytes=0-1,3-4"})
    assert response.status_code == 416
    assert response.content == b""
    assert database_hash(sessions) == before


@pytest.mark.parametrize("ticket", ["mistyped-ticket", ""])
def test_invalid_ticket_does_not_fall_back_to_cookie(exported_source, tmp_path, ticket):
    client, ticket_url, url = native_session(exported_source, tmp_path)
    assert client.get(ticket_url, headers={"Range": "bytes=0-1"}).status_code == 206
    sessions = exported_source[3]
    before = database_hash(sessions)
    response = client.get(url + "?ticket=" + ticket, headers={"Range": "bytes=0-1"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Sesión de descarga requerida."}
    assert database_hash(sessions) == before


@pytest.fixture
def plan_source(imports, tmp_path, monkeypatch):
    from scripts.migrate_dataset_exports import migrate_exports
    from app.routes.dataset_imports import get_import_storage
    client, service, app, sessions = imports
    migrate_exports(sessions.kw["bind"], writers_stopped=True)
    storage = ManifestObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    monkeypatch.setenv("FAMA_EXPORT_DOWNLOAD_ORIGIN", "https://downloads.example.test")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("FAMA_EXPORT_ROOT", str(root))
    source = prepare(client, tmp_path, name="Aves-Chilenas", entries=[
        ("chucao/sesion_01/audio_01.wav", wav_bytes()),
        ("colilarga/audio_02.wav", wav_bytes(2)),
    ])
    dataset = confirm(client, source).json()["dataset_id"]
    assert operation(client, source["id"], "sync").json()["sync_status"] == "synced"
    return client, service, app, sessions, storage, dataset, root


def run_plan(source, *, clock=None, limits=None):
    from app.routes.dataset_exports import get_export_queue
    from app.services.dataset_exports import ExportExecution, ExportQueue
    client, service, app, sessions, storage, dataset, root = source
    queue = ExportQueue(sessions, service, clock=clock, limits=limits)
    app.dependency_overrides[get_export_queue] = lambda: queue
    admitted = client.post(f"/api/ingestion/imports/datasets/{dataset}/revisions/1/exports",
                           json={"request_key": "plan-probe"})
    assert admitted.status_code == 202, admitted.text
    job = admitted.json()
    assert ExportExecution(queue, root, storage=storage,
                           heartbeat_wait=lambda stop, interval: stop.wait()).run_once()
    return queue, job


def test_original_plan_example_without_any_local_sources(plan_source):
    from app.models.dataset_import_metadata import DatasetMember, ImportFile
    from app.models.dataset_import_revision import RevisionObject
    client, service, _, sessions, storage, _, _ = plan_source
    shutil.rmtree(service.root / "objects")
    shutil.rmtree(service.root / "staging")
    with sessions() as db:
        for model in (DatasetMember, ImportFile, RevisionObject):
            db.query(model).delete()
        db.commit()
    frozen = dict(storage.objects)
    _, job = run_plan(plan_source)
    first = client.get(client.post(job["status_url"] + "/sessions").json()["url"])
    assert first.status_code == 200
    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        expected = {
            "Aves-Chilenas/chucao/sesion_01/audio_01.wav": wav_bytes(),
            "Aves-Chilenas/colilarga/audio_02.wav": wav_bytes(2),
        }
        assert set(archive.namelist()) == set(expected)
        for name, data in expected.items():
            assert archive.read(name) == data
            assert archive.getinfo(name).extract_version >= 45
    assert storage.objects == frozen


@pytest.mark.parametrize("fault", ["trailing", "duplicate-header", "missing-comma", "trailing-comma",
                                  "extra-field", "bool-count", "oversize-record", "double-slash",
                                  "unicode-duplicate", "empty-files"])
def test_invalid_wire_manifest_never_produces_final_export(plan_source, fault):
    from app.models.dataset_import_revision import DatasetRevision
    client, _, _, sessions, storage, dataset, root = plan_source
    def mutate(data):
        if fault == "trailing":
            return data + b"junk"
        if fault == "duplicate-header":
            return data.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')
        if fault == "missing-comma":
            return data.replace(b"},\n", b"}\n", 1)
        if fault == "trailing-comma":
            return data.replace(b"\n]}", b",\n]}")
        if fault == "oversize-record":
            return data.replace(b'"description": "Synthetic"', b'"description": "' + b"a" * 17000 + b'"')
        value = json.loads(data)
        if fault == "extra-field":
            value["files"][0]["url"] = "https://untrusted.test/file"
        if fault == "bool-count":
            value["file_count"] = True
        if fault == "double-slash":
            value["files"][0]["relative_path"] = "chucao//audio.wav"
        if fault == "unicode-duplicate":
            for entry, path in zip(value["files"], ["birds/é.wav", "birds/e\u0301.wav"]):
                entry["class_name"], entry["relative_path"] = "birds", path
        if fault == "empty-files":
            value["files"] = []
        entries = value.pop("files")
        return (json.dumps(value, sort_keys=True).encode()[:-1] + b', "files": [\n'
                + b",\n".join(json.dumps(entry, sort_keys=True).encode() for entry in entries) + b"\n]}\n")
    with sessions() as db:
        row = db.query(DatasetRevision).filter_by(dataset_id=dataset).one()
        data = mutate(storage.objects[row.manifest_key][0])
        row.manifest_sha256 = hashlib.sha256(data).hexdigest()
        row.manifest_size_bytes = len(data)
        row.manifest_key = f"private-imports/1/{dataset}/revisions/1/{row.manifest_sha256}.json"
        storage.objects[row.manifest_key] = (data, {})
        db.commit()
    frozen = dict(storage.objects)
    _, job = run_plan(plan_source)
    status = client.get(job["status_url"]).json()
    assert status["status"] == "failed" and status["sha256"] is None
    before = database_hash(sessions)
    assert client.post(job["status_url"] + "/sessions").status_code == 410
    assert database_hash(sessions) == before and storage.objects == frozen
    assert not list(root.glob("*/export.zip"))


def test_native_backpressure_protects_active_download(plan_source):
    import asyncio
    from app.services.dataset_exports import ExportLimits
    client, _, app, _, _, _, root = plan_source
    now = [100.0]
    queue, job = run_plan(plan_source, clock=lambda: now[0],
        limits=ExportLimits(session_seconds=10, artifact_seconds=20))
    first = client.get(client.post(job["status_url"] + "/sessions").json()["url"])
    cookie = first.request.headers["cookie"]
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []
        async def receive():
            await asyncio.Future()
        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                entered.set()
                await release.wait()
        path = f"/api/ingestion/imports/exports/{job['id']}/download"
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                 "http_version": "1.1", "method": "GET", "scheme": "https", "path": path,
                 "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "server": ("downloads.example.test", 443), "client": ("127.0.0.1", 1234),
                 "headers": [(b"cookie", cookie.encode()), (b"range", b"bytes=0-19")]}
        pending = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            now[0] = 121.0
            assert queue.cleanup(root) == {"completed": 0, "busy": 1, "failed": 0}
        finally:
            release.set()
            await asyncio.wait_for(pending, 2)
        assert messages[0]["status"] == 206
        assert b"".join(message.get("body", b"") for message in messages) == first.content[:20]
    asyncio.run(scenario())
    assert queue.cleanup(root) == {"completed": 1, "busy": 0, "failed": 0}
    assert not list(root.iterdir())


def test_replacement_wins_while_old_callback_is_still_unwinding(plan_source):
    from app.routes.dataset_exports import get_export_queue
    from app.services.dataset_exports import ExportQueue, ExportExecution
    client, service, app, sessions, storage, dataset, root = plan_source
    now = [100.0]
    queue = ExportQueue(sessions, service, clock=lambda: now[0])
    app.dependency_overrides[get_export_queue] = lambda: queue
    job = client.post(f"/api/ingestion/imports/datasets/{dataset}/revisions/1/exports",
                      json={"request_key": "reclaim"}).json()
    original, reads, winner = storage.read_verified, [0], []
    def read(*args):
        result = original(*args)
        if args[0].endswith(".wav"):
            reads[0] += 1
            if reads[0] == 2:
                now[0] = 200.0
                assert ExportExecution(queue, root, storage=storage,
                    heartbeat_wait=lambda stop, interval: stop.wait()).run_once()
                winner.append(client.get(job["status_url"]).json())
                assert winner[0]["status"] == "succeeded"
        return result
    storage.read_verified = read
    assert ExportExecution(queue, root, storage=storage,
        heartbeat_wait=lambda stop, interval: stop.wait()).run_once()
    assert client.get(job["status_url"]).json() == winner[0]
    native = client.get(client.post(job["status_url"] + "/sessions").json()["url"])
    assert native.status_code == 200
    assert hashlib.sha256(native.content).hexdigest() == winner[0]["sha256"]
    assert len(list(root.iterdir())) == 2


@pytest.mark.parametrize("fault", ["exact", "byte-over", "entry-over"])
def test_policy_exact_and_one_over_with_distinct_members(plan_source, fault):
    from app.services.dataset_exports import ExportLimits
    total = len(wav_bytes()) + len(wav_bytes(2))
    limits = ExportLimits(files=1 if fault == "entry-over" else 2, bytes=total - (fault == "byte-over"))
    _, job = run_plan(plan_source, limits=limits)
    assert plan_source[0].get(job["status_url"]).json()["status"] == ("succeeded" if fault == "exact" else "failed")
