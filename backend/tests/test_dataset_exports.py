"""T7 through authenticated HTTP, a public worker, and generation-bound fake storage."""
import hashlib
import io
import json
import shutil
import zipfile

import pytest

from tests.test_dataset_import_api import imports, prepare, confirm, operation  # noqa: F401 - public fixture
from tests.test_dataset_import_manifests import ManifestObjects
from tests.test_dataset_zip_validation import wav_bytes


@pytest.fixture
def exported_source(imports, tmp_path, monkeypatch):
    from app.routes.dataset_imports import get_import_storage
    client, service, app, sessions = imports
    storage = ManifestObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    monkeypatch.setenv("FAMA_EXPORT_DOWNLOAD_ORIGIN", "https://downloads.example.test")
    root = tmp_path / "exports"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("FAMA_EXPORT_ROOT", str(root))
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    assert operation(client, source["id"], "sync").json()["sync_status"] == "synced"
    return client, service, app, sessions, storage, dataset, source


def admit(client, dataset, key="export-1"):
    response = client.post(f"/api/ingestion/imports/datasets/{dataset}/revisions/1/exports",
                           json={"request_key": key})
    assert response.status_code == 202, response.text
    return response.json()


def test_export_without_local_sources_is_complete_and_native_resumable(exported_source, tmp_path):
    client, service, _, sessions, storage, dataset, source = exported_source
    from app.models.dataset_import_metadata import DatasetMember, ImportFile
    from app.models.dataset_import_revision import RevisionObject
    shutil.rmtree(service.root / "objects")
    shutil.rmtree(service.root / "staging")
    with sessions() as db:
        db.query(DatasetMember).delete()
        db.query(ImportFile).delete()
        db.query(RevisionObject).delete()
        db.commit()
    job = admit(client, dataset)
    assert job["status"] == "queued"
    from app.services.dataset_exports import ExportExecution, ExportQueue
    root = tmp_path / "exports"
    queue = ExportQueue(sessions, service)
    execution = ExportExecution(queue, root, storage=storage)
    assert execution.run_once()
    status = client.get(job["status_url"])
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "succeeded"
    issued = client.post(job["status_url"] + "/sessions")
    assert issued.status_code == 200, issued.text
    session = issued.json()
    assert session["url"].startswith("https://downloads.example.test/")
    # Simulate native navigation: no Bearer header or Blob API involved.
    path = session["url"]
    full = client.get(path)
    assert full.status_code == 200, full.text
    assert full.headers["content-length"] == str(len(full.content))
    assert full.headers["etag"] == '"' + hashlib.sha256(full.content).hexdigest() + '"'
    assert "attachment" in full.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(full.content)) as archive:
        assert archive.namelist() == ["Birds/birds/a.wav"]
        assert archive.read("Birds/birds/a.wav") == wav_bytes()
        assert archive.getinfo("Birds/birds/a.wav").extract_version >= 45
    for start, end in [(0, 9), (10, 29), (0, 9)]:
        part = client.get(path, headers={"Range": f"bytes={start}-{end}", "If-Range": full.headers["etag"]})
        assert part.status_code == 206
        assert part.content == full.content[start:end + 1]
        assert part.headers["content-range"] == f"bytes {start}-{end}/{len(full.content)}"


def completed(source, tmp_path, *, clock=None, limits=None):
    from app.services.dataset_exports import ExportExecution, ExportQueue
    from app.routes.dataset_exports import get_export_queue
    client, service, app, sessions, storage, dataset, _ = source
    queue = ExportQueue(sessions, service, clock=clock, limits=limits)
    app.dependency_overrides[get_export_queue] = lambda: queue
    job = admit(client, dataset)
    execution = ExportExecution(queue, tmp_path / "exports", storage=storage,
                               heartbeat_wait=lambda stop, interval: stop.wait())
    assert execution.run_once()
    return queue, execution, job


def test_renewal_establishes_new_session_after_old_cookie_expires(exported_source, tmp_path):
    from app.services.dataset_exports import ExportLimits
    now = [100.0]
    client = exported_source[0]
    queue, _, job = completed(exported_source, tmp_path, clock=lambda: now[0],
                              limits=ExportLimits(session_seconds=10))
    original = client.post(job["status_url"] + "/sessions").json()["url"]
    first = client.get(original)
    assert first.status_code == 200
    cookie = first.request.headers["cookie"]
    now[0] = 111.0
    assert client.get(str(first.url)).status_code == 401
    renewed = client.post(job["status_url"] + "/sessions").json()["url"]
    recovered = client.get(renewed)
    assert recovered.status_code == 200, recovered.text
    assert recovered.content == first.content
    # Renewing does not transform an old credential into a renewed credential.
    assert client.get(str(first.url), headers={"Cookie": cookie}).status_code == 401


@pytest.mark.parametrize("fault", ["missing", "corrupt", "wrong-generation", "short", "oversize"])
def test_object_failure_never_exposes_partial_zip(exported_source, tmp_path, fault):
    from app.services.dataset_exports import ExportExecution, ExportQueue
    client, service, _, sessions, storage, dataset, _ = exported_source
    read = storage.read_verified
    def broken(key, generation, digest, size, destination):
        if not key.endswith(".wav"):
            return read(key, generation, digest, size, destination)
        if fault == "missing":
            raise KeyError(key)
        if fault == "wrong-generation":
            return read(key, "999", digest, size, destination)
        # A misbehaving adapter cannot bypass the export sink's own checks.
        destination.write(b"x" * (size + 1 if fault == "oversize" else size - 1 if fault == "short" else size))
    storage.read_verified = broken
    queue = ExportQueue(sessions, service)
    job = admit(client, dataset)
    assert ExportExecution(queue, tmp_path / "exports", storage=storage).run_once()
    status = client.get(job["status_url"]).json()
    assert status["status"] == "failed" and status["sha256"] is None
    assert client.post(job["status_url"] + "/sessions").status_code == 410
    assert client.get(job["status_url"] + "/download").status_code == 401
    assert not list((tmp_path / "exports").glob("*/export.zip"))


def rewrite_manifest(source, change):
    """Simulated storage fixture with an authorized digest but invalid member data."""
    from app.models.dataset_import_revision import DatasetRevision
    _, _, _, sessions, storage, dataset, _ = source
    with sessions() as db:
        row = db.query(DatasetRevision).filter_by(dataset_id=dataset).one()
        header = json.loads(storage.objects[row.manifest_key][0])
        change(header)
        entries = header.pop("files")
        data = json.dumps(header, ensure_ascii=True, sort_keys=True).encode()[:-1] + b', "files": [\n'
        data += b",\n".join(json.dumps(entry, ensure_ascii=True, sort_keys=True).encode() for entry in entries) + b"\n]}\n"
        row.manifest_sha256 = hashlib.sha256(data).hexdigest()
        row.manifest_size_bytes = len(data)
        row.manifest_key = f"private-imports/1/{dataset}/revisions/1/{row.manifest_sha256}.json"
        storage.objects[row.manifest_key] = (data, {})
        db.commit()


@pytest.mark.parametrize("fault", ["schema", "total", "traversal", "absolute", "backslash", "control", "namespace", "duplicate", "generation", "bool-size", "label", "source", "name"])
def test_invalid_authorized_manifest_is_rejected_without_download(exported_source, tmp_path, fault):
    def change(header):
        entry = header["files"][0]
        if fault == "schema":
            header["schema_version"] = 2
        elif fault == "total":
            header["total_size_bytes"] += 1
        elif fault == "duplicate":
            header["files"].append(dict(entry))
        elif fault == "name":
            header["name"] = "../escape"
        else:
            key, value = {
                "traversal": ("relative_path", "birds/../escape.wav"),
                "absolute": ("relative_path", "/birds/a.wav"),
                "backslash": ("original_path", "birds\\a.wav"),
                "control": ("relative_path", "birds/a\x00.wav"),
                "namespace": ("object_key", "private-imports/2/other/object.wav"),
                "generation": ("object_generation", "latest"),
                "bool-size": ("size_bytes", True),
                "label": ("class_name", "engine"),
                "source": ("source_import_id", "../source"),
            }[fault]
            entry[key] = value
    rewrite_manifest(exported_source, change)
    _, _, job = completed(exported_source, tmp_path)
    client = exported_source[0]
    assert client.get(job["status_url"]).json()["status"] == "failed"
    assert client.post(job["status_url"] + "/sessions").status_code == 410


def test_http_ownership_idempotency_ranges_and_route_fail_closed(exported_source, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.routes.dataset_imports import get_import_user
    client, _, app, _, _, dataset, _ = exported_source
    queue, _, job = completed(exported_source, tmp_path)
    assert admit(client, dataset)["id"] == job["id"]
    history = client.get(f"/api/ingestion/imports/datasets/{dataset}/exports")
    assert history.status_code == 200 and history.json()["exports"][0]["id"] == job["id"]
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.get(job["status_url"]).status_code == 404
    assert client.get(f"/api/ingestion/imports/datasets/{dataset}/exports").status_code == 404
    assert client.post(job["status_url"] + "/sessions").status_code == 404
    assert client.post(f"/api/ingestion/imports/datasets/{dataset}/revisions/1/exports",
                       json={"request_key": "foreign"}).status_code == 404
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    monkeypatch.delenv("FAMA_EXPORT_DOWNLOAD_ORIGIN")
    assert client.post(job["status_url"] + "/sessions").status_code == 503
    monkeypatch.setenv("FAMA_EXPORT_DOWNLOAD_ORIGIN", "https://downloads.example.test")
    issued = client.post(job["status_url"] + "/sessions").json()
    downloaded = client.get(issued["url"])
    url = str(downloaded.url)
    headers = downloaded.headers
    assert client.head(url).headers["content-length"] == headers["content-length"]
    assert client.get(url, headers={"Range": "bytes=-7"}).content == downloaded.content[-7:]
    assert client.get(url, headers={"Range": "bytes=10-"}).content == downloaded.content[10:]
    assert client.get(url, headers={"Range": "bytes=0-1", "If-Range": '"other"'}).content == downloaded.content
    for value in ["bytes=999999-", "bytes=-0", "bytes=5-2", "bytes=0-1,4-5", "bad"]:
        rejected = client.get(url, headers={"Range": value})
        assert rejected.status_code == 416 and rejected.content == b""
        assert rejected.headers["content-range"] == "bytes */" + headers["content-length"]
    # A ticket is only a bootstrap. Losing the established cookie does not make it reusable.
    client.cookies.clear()
    assert client.get(issued["url"]).status_code == 401


def test_reclaim_blocks_stale_worker_and_recovers_from_persisted_job(exported_source, tmp_path):
    from app.services.dataset_exports import ExportExecution, ExportQueue
    from app.routes.dataset_exports import get_export_queue
    client, service, app, sessions, storage, dataset, _ = exported_source
    now = [100.0]
    queue = ExportQueue(sessions, service, clock=lambda: now[0])
    app.dependency_overrides[get_export_queue] = lambda: queue
    job = admit(client, dataset)
    read = storage.read_verified
    def interrupt(*args):
        result = read(*args)
        if args[0].endswith(".wav"):
            now[0] = 200.0
        return result
    storage.read_verified = interrupt
    first = ExportExecution(queue, tmp_path / "exports", storage=storage,
                            heartbeat_wait=lambda stop, interval: stop.wait())
    assert first.run_once()
    assert client.get(job["status_url"]).json()["status"] == "running"
    assert client.post(job["status_url"] + "/sessions").status_code == 410
    storage.read_verified = read
    replacement = ExportExecution(queue, tmp_path / "exports", storage=storage)
    assert replacement.run_once()
    assert client.get(job["status_url"]).json()["status"] == "succeeded"
    assert queue.get(1, job["id"])["attempt"] == 2
    assert len(list((tmp_path / "exports").iterdir())) == 2


def test_cleanup_preserves_active_range_then_retries_parent_fsync(exported_source, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app.services import dataset_exports
    from app.routes import dataset_exports as routes
    from app.services.dataset_exports import ExportLimits
    now = [100.0]
    queue, _, job = completed(exported_source, tmp_path, clock=lambda: now[0],
        limits=ExportLimits(artifact_seconds=20, session_seconds=10))
    client = exported_source[0]
    url = client.post(job["status_url"] + "/sessions").json()["url"]
    first = client.get(url)
    started, release = threading.Event(), threading.Event()
    read = routes.os.read
    def blocked(fd, size):
        data = read(fd, size)
        if data.startswith(b"PK"):
            started.set()
            assert release.wait(5), "controlled transfer was not released"
        return data
    monkeypatch.setattr(routes.os, "read", blocked)
    root = tmp_path / "exports"
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.get, str(first.url), headers={"Range": "bytes=0-9"})
        try:
            assert started.wait(5)
            now[0] = 121.0
            assert queue.cleanup(root) == {"completed": 0, "busy": 1, "failed": 0}
        finally:
            release.set()
        assert pending.result(timeout=5).content == first.content[:10]
    durable = dataset_exports._durable_directory
    def fail_once(path):
        monkeypatch.setattr(dataset_exports, "_durable_directory", durable)
        raise OSError("synthetic parent fsync failure")
    monkeypatch.setattr(dataset_exports, "_durable_directory", fail_once)
    assert queue.cleanup(root)["failed"] == 1
    assert client.get(job["status_url"]).json()["status"] == "expired"
    assert queue.cleanup(root)["failed"] == 0
    assert not list(root.iterdir())
    assert client.get(str(first.url)).status_code == 401


@pytest.mark.parametrize("bound", ["exact", "byte-excess", "file-excess"])
def test_export_checks_totals_against_bounded_policy(exported_source, tmp_path, bound):
    from app.services.dataset_exports import ExportLimits
    client = exported_source[0]
    limits = ExportLimits(files=1, bytes=len(wav_bytes()) - (bound == "byte-excess"))
    if bound == "file-excess":
        rewrite_manifest(exported_source, lambda header: header["files"].append(dict(header["files"][0])))
    queue, _, job = completed(exported_source, tmp_path, limits=limits)
    assert client.get(job["status_url"]).json()["status"] == ("succeeded" if bound == "exact" else "failed")


def test_sessions_are_bounded_and_renewal_does_not_revoke_live_ranges(exported_source, tmp_path):
    client = exported_source[0]
    queue, _, job = completed(exported_source, tmp_path)
    first = client.get(client.post(job["status_url"] + "/sessions").json()["url"])
    original_cookie = first.request.headers["cookie"]
    for _ in range(7):
        assert client.post(job["status_url"] + "/sessions").status_code == 200
    assert client.post(job["status_url"] + "/sessions").status_code == 429
    assert client.get(str(first.url), headers={"Cookie": original_cookie, "Range": "bytes=0-9"}).content == first.content[:10]


def test_same_size_changed_artifact_cannot_keep_original_identity(exported_source, tmp_path):
    client = exported_source[0]
    queue, _, job = completed(exported_source, tmp_path)
    issued = client.post(job["status_url"] + "/sessions").json()
    first = client.get(issued["url"])
    path = tmp_path / "exports" / queue.get(1, job["id"])["artifact"]
    path.chmod(0o600)
    path.write_bytes(b"x" * len(first.content))
    assert client.get(str(first.url)).status_code == 409
