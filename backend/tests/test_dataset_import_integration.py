"""T8 public lifecycle with synthetic audio, memory SQLite and fake generations.

The shared HTTP fixture uses the cooperative synthetic validator because the
unchanged memory-only runner forbids subprocesses. T4 OS containment is separate.
"""
import hashlib
import io
import json
import resource
import shutil
import time
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.test_dataset_import_api import imports  # noqa: F401 - shared public fixture
from tests.test_dataset_import_manifests import ManifestObjects
from tests.test_dataset_import_receipts import dump
from tests.test_dataset_zip_validation import archive, wav_bytes


BASE = "/api/ingestion/imports"


def checked(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def put(client, url, index, data, chunk_bytes):
    return client.put(f"{url}/chunks/{index}", content=data, headers={
        "Content-Type": "application/octet-stream",
        "X-Chunk-Offset": str(index * chunk_bytes),
        "X-Chunk-SHA256": hashlib.sha256(data).hexdigest(),
    })


def execute(client, execution, identity, kind, **payload):
    admission = checked(client.post(f"{BASE}/{identity}/{kind}", json={
        "request_key": f"{kind}-{identity}", **payload}), 202)
    assert admission["status"] == "queued"
    assert execution.run_once()
    assert checked(client.get(admission["status_url"]))["status"] == "succeeded"
    return checked(client.get(f"{BASE}/{identity}"))


def observed_get(client, engine, url, **kwargs):
    statements = []
    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        response = client.get(url, **kwargs)
        checked(response)
        return response, len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def disk_bytes(root):
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def test_receipt_to_native_export_recovers_and_remains_bounded(imports, tmp_path, monkeypatch):
    from app.routes.dataset_imports import get_import_storage
    from app.routes.dataset_exports import get_export_queue
    from app.services.dataset_import_execution import ImportExecution
    from app.services.dataset_exports import ExportExecution, ExportLimits, ExportQueue
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_import_chunks import migrate_chunks

    original, service, app, sessions = imports
    engine = sessions.kw["bind"]
    for migrate in (migrate_receipts, migrate_chunks):
        assert migrate(engine, writers_stopped=True) == {"version": 1, "verified": True}
    chunk_bytes = 4096  # Small synthetic transfer units, not a new production default.
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", str(chunk_bytes))
    monkeypatch.setenv("FAMA_EXPORT_DOWNLOAD_ORIGIN", "https://downloads.example.test")
    export_root = tmp_path / "exports"
    export_root.mkdir(mode=0o700)
    monkeypatch.setenv("FAMA_EXPORT_ROOT", str(export_root))
    measurements = []

    for count in (60, 600):
        expected = {f"birds/{index:04}.wav": wav_bytes(index + 1) for index in range(count)}
        data = archive(tmp_path / f"source-{count}.zip", expected.items()).read_bytes()
        identity = checked(original.post(BASE, json={"request_key": f"integral-{count}",
            "name": f"Synthetic-{count}", "description": "T8 synthetic lifecycle"}))["id"]
        url = f"{BASE}/{identity}/receipt"
        checked(original.post(url, json={"name": "one.zip", "size_bytes": len(data)}))
        for index in range(3):
            checked(put(original, url, index, data[index * chunk_bytes:(index + 1) * chunk_bytes], chunk_bytes))
        accepted = checked(original.get(url))["received_bytes"]
        assert accepted == 3 * chunk_bytes

        # Recreate the HTTP consumer, not a process-kill simulation. Compare every
        # acknowledged chunk before sending the unacknowledged suffix only.
        with TestClient(app, raise_server_exceptions=False) as client:
            prefix = checked(client.get(url + "/chunks"))["chunks"]
            assert len(prefix) == 3
            for chunk in prefix:
                start = chunk["offset_bytes"]
                block = data[start:start + chunk["length_bytes"]]
                assert hashlib.sha256(block).hexdigest() == chunk["sha256"]
            altered = bytearray(data[chunk_bytes:2 * chunk_bytes])
            altered[len(altered) // 2] ^= 1
            before = dump(sessions)
            checked(put(client, url, 1, bytes(altered), chunk_bytes), 409)
            assert dump(sessions) == before
            assert checked(client.get(url))["received_bytes"] == accepted
            for offset in range(accepted, len(data), chunk_bytes):
                checked(put(client, url, offset // chunk_bytes, data[offset:offset + chunk_bytes], chunk_bytes))
            assert checked(client.post(url + "/finalize"))["status"] == "sealed"
            source = execute(client, original.execution, identity, "preview", root="")
            assert source["status"] == "ready" and source["preview"]["new_count"] == count
            assert checked(client.get(BASE + "/datasets"))["total"] == len(measurements)
            assert len(source["issue_sample"]) <= 5

            pages = []
            for limit in (50, 200):
                response, queries = observed_get(client, engine, f"{BASE}/{identity}/files", params={"limit": limit})
                page = response.json()
                assert len(page["files"]) == min(limit, count) and page["total"] == count
                assert (page["next_cursor"] is not None) == (count > limit)
                pages.append({"limit": limit, "bytes": len(response.content), "queries": queries})
            assert checked(client.get(f"{BASE}/{identity}/files?limit=201"), 422)
            result = execute(client, original.execution, identity, "confirm", preview_token=source["preview_token"])
            assert result["status"] == "imported" and result["added_count"] == count
            assert result["sync_status"] == "pending"
            assert checked(client.get(url))["reserved_bytes"] == 0
            dataset = result["dataset_id"]
            revision_url = f"{BASE}/datasets/{dataset}/revisions/1"

            # Lose the first sync lease immediately after creating an object.
            # A replacement executor must reverify it, not publish a partial revision.
            now = [time.time()]
            queue = original.execution.queue
            queue.clock = lambda: now[0]
            class InterruptedStorage(ManifestObjects):
                interrupt = True
                def ensure(self, *args):
                    value = super().ensure(*args)
                    if self.interrupt:
                        self.interrupt = False
                        now[0] += 100
                    return value
            storage = InterruptedStorage()
            app.dependency_overrides[get_import_storage] = lambda: storage
            execution = ImportExecution(queue, service, original.execution.root, storage=storage,
                heartbeat_wait=lambda stop, interval: stop.wait())
            admitted = checked(client.post(f"{BASE}/{identity}/sync", json={"request_key": "sync"}), 202)
            assert execution.run_once()
            partial = checked(client.get(revision_url))
            assert partial["status"] == "pending" and partial["manifest"] is None
            assert checked(client.get(admitted["status_url"]))["status"] == "running"
            replacement = ImportExecution(queue, service, execution.root, storage=storage)
            assert replacement.run_once()
            assert checked(client.get(admitted["status_url"]))["status"] == "succeeded"
            reference = checked(client.get(revision_url))
            assert reference["status"] == "complete" and reference["file_count"] == count
            manifest_bytes = storage.objects[reference["manifest"]["object_key"]][0]
            assert hashlib.sha256(manifest_bytes).hexdigest() == reference["manifest"]["sha256"]
            manifest = json.loads(manifest_bytes)
            assert {entry["relative_path"]: entry["sha256"] for entry in manifest["files"]} == {
                path: hashlib.sha256(value).hexdigest() for path, value in expected.items()}
            assert all(entry["object_generation"] == "1" for entry in manifest["files"])
            observed_peak = disk_bytes(tmp_path)

            # Disposable local sources are absent. Immutable remote references
            # remain authoritative; no membership records need to be deleted.
            shutil.rmtree(service.root / "objects" / identity)
            shutil.rmtree(service.root / "staging" / identity)
            (tmp_path / f"source-{count}.zip").unlink()
            export_clock = [time.time()]
            exports = ExportQueue(sessions, service, clock=lambda: export_clock[0],
                limits=ExportLimits(artifact_seconds=20, session_seconds=10))
            app.dependency_overrides[get_export_queue] = lambda: exports
            job = checked(client.post(revision_url + "/exports", json={"request_key": f"export-{count}"}), 202)
            assert ExportExecution(exports, export_root, storage=storage).run_once()
            assert checked(client.get(job["status_url"]))["status"] == "succeeded"
            link = checked(client.post(job["status_url"] + "/sessions"))["url"]
            downloaded = client.get(link)
            assert downloaded.status_code == 200
            assert downloaded.headers["content-length"] == str(len(downloaded.content))
            assert downloaded.headers["etag"] == '"' + hashlib.sha256(downloaded.content).hexdigest() + '"'
            with zipfile.ZipFile(io.BytesIO(downloaded.content)) as exported:
                assert set(exported.namelist()) == {f"Synthetic-{count}/{path}" for path in expected}
                for path, value in expected.items():
                    assert exported.read(f"Synthetic-{count}/{path}") == value
            native_url = str(downloaded.url)
            for start, end in ((0, 9), (10, 29), (0, 9)):
                response = client.get(native_url, headers={"Range": f"bytes={start}-{end}",
                    "If-Range": downloaded.headers["etag"]})
                assert response.status_code == 206 and response.content == downloaded.content[start:end + 1]
            export_clock[0] += 11
            assert client.get(native_url).status_code == 401
            renewed = checked(client.post(job["status_url"] + "/sessions"))["url"]
            assert client.get(renewed).content == downloaded.content
            observed_peak = max(observed_peak, disk_bytes(tmp_path))
            export_clock[0] += 10
            assert exports.cleanup(export_root) == {"completed": 1, "busy": 0, "failed": 0}
            with sessions() as db:
                service.cleanup(db, attempt_root=execution.root)
            assert not list(export_root.iterdir())
            assert not (service.root / "staging" / identity).exists()
            assert checked(client.get(revision_url)) == reference
            assert storage.objects[reference["manifest"]["object_key"]][0] == manifest_bytes
            measurements.append({"files": count, "zip_bytes": len(data), "pages": pages,
                "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "observed_private_disk_high_water_bytes": observed_peak,
                "private_disk_residual_bytes": disk_bytes(tmp_path), "export_artifacts_remaining": 0})
            queue.clock = time.time
    assert [page["queries"] for page in measurements[0]["pages"]] == [page["queries"] for page in measurements[1]["pages"]]
    print("T8_METRICS " + json.dumps(measurements, sort_keys=True))
