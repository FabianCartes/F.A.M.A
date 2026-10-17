"""Independent S6 probes at HTTP, public execution and migration seams."""
import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_dataset_zip_validation import wav_bytes

BASE = "/api/ingestion/imports"


def dump(sessions):
    with sessions.kw["bind"].connect() as conn:
        data = "\n".join(conn.connection.driver_connection.iterdump()).encode()
    return hashlib.sha256(data).hexdigest()


class Objects:
    def __init__(self):
        self.data = {}
        self.calls = []
        self.hook = lambda key: None
        self.generation = {}

    def ensure(self, key, path, digest, metadata):
        from app.services.dataset_import_storage import IntegrityConflict
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        self.calls.append(key)
        if key in self.data and self.data[key] != (data, metadata):
            raise IntegrityConflict("independent identity conflict")
        self.data.setdefault(key, (data, metadata))
        self.hook(key)
        return self.generation.get(key, "7")

    ensure_manifest = ensure

    def read_verified(self, key, generation, digest, size, destination):
        from app.services.dataset_import_storage import IntegrityConflict
        data = self.data[key][0]
        if generation != self.generation.get(key, "7") or len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise IntegrityConflict("independent recovery conflict")
        destination.write(data)


def setup(imports):
    from app.routes.dataset_imports import get_import_storage
    client, service, app, sessions = imports
    store = Objects()
    app.dependency_overrides[get_import_storage] = lambda: store
    client.execution.storage = store
    return client, service, app, sessions, store


def sync(client, source, key="sync"):
    response = client.post(f"{BASE}/{source['id']}/sync", json={"request_key": key})
    assert response.status_code == 202, response.text
    assert client.execution.run_once()
    return client.get(response.json()["status_url"]).json()


def ref(client, dataset, rev=1):
    return client.get(f"{BASE}/datasets/{dataset}/revisions/{rev}")


@pytest.mark.parametrize("window", ["object", "manifest"])
def test_reclaim_retains_frozen_revision_after_dataset_advance(imports, tmp_path, monkeypatch, window):
    from app.services.dataset_import_execution import ImportExecution
    client, service, app, sessions, store = setup(imports)
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    extension = prepare(client, tmp_path, key="extension", target_id=dataset, sample=2)
    queue = client.execution.queue
    queue.clock = lambda: 100.0
    queue.limits = replace(queue.limits, owner_active=2)
    monkeypatch.setenv("FAMA_IMPORT_JOBS_PER_OWNER", "2")
    client.execution.worker.heartbeat_wait = lambda stop, interval: stop.wait()

    def interrupt(key):
        if key.endswith(".wav") == (window == "object"):
            queue.clock = lambda: 200.0

    store.hook = interrupt
    result = sync(client, source)
    assert result["status"] == "running"
    state = ref(client, dataset).json()
    assert state["status"] == "pending" and state["manifest"] is None
    assert state["verified_count"] == (0 if window == "object" else 1)
    before = dump(sessions)
    denied = client.get(f"{BASE}/datasets/{dataset}/revisions/1/manifest")
    assert denied.status_code == 409
    assert denied.json() == {"detail": "La revisión todavía no tiene un manifiesto completo."}
    assert dump(sessions) == before
    # Advance through a separate HTTP-admitted confirmation before reclaim.
    # The bound sync is reclaimed first, so advance during its object transfer.
    store.hook = lambda key: None
    replacement = ImportExecution(queue, service, client.execution.root, storage=store)
    advanced = []

    def advance(key):
        if advanced or not key.endswith(".wav"):
            return
        advanced.append(True)
        response = client.post(f"{BASE}/{extension['id']}/confirm", json={
            "request_key": "advance", "preview_token": extension["preview_token"]})
        assert response.status_code == 202
        other = ImportExecution(queue, service, replacement.root)
        assert other.run_once()
        assert client.get(response.json()["status_url"]).json()["status"] == "succeeded"

    store.hook = advance
    assert replacement.run_once()
    settled = client.get(result["status_url"]).json()
    assert settled["status"] == "succeeded"
    assert settled["result"] == {"dataset_id": dataset, "dataset_revision": 1, "synced_count": 1}
    frozen = ref(client, dataset).json()
    assert frozen["file_count"] == 1 and frozen["status"] == "complete"
    assert client.get(f"{BASE}/{source['id']}").json()["sync_status"] == "pending"
    store.hook = lambda key: None
    client.execution = replacement
    assert sync(client, extension, "next")["result"]["dataset_revision"] == 2
    assert ref(client, dataset, 2).json()["file_count"] == 2
    assert ref(client, dataset).json() == frozen


@pytest.mark.parametrize("bound", ["count", "bytes"])
def test_bounded_serial_batches_and_oversized_member(imports, tmp_path, monkeypatch, bound):
    client, _, _, _, store = setup(imports)
    size = len(wav_bytes())
    monkeypatch.setenv("FAMA_IMPORT_SYNC_BATCH_FILES", "2" if bound == "count" else "3")
    monkeypatch.setenv("FAMA_IMPORT_SYNC_BATCH_BYTES", str(size * (3 if bound == "count" else 2)))
    source = prepare(client, tmp_path, entries=[(f"birds/{i}.wav", wav_bytes(i)) for i in (1, 2, 3)])
    dataset = confirm(client, source).json()["dataset_id"]
    observations = []
    store.hook = lambda key: observations.append(ref(client, dataset).json()["verified_count"]) if key.endswith(".wav") else None
    assert sync(client, source)["status"] == "succeeded"
    assert observations == [0, 0, 2]
    old = ref(client, dataset).json()
    objects = dict(store.data)
    monkeypatch.setenv("FAMA_IMPORT_SYNC_BATCH_BYTES", str(size - 1))
    assert sync(client, source, "too-small")["status"] == "failed"
    assert ref(client, dataset).json() == old
    assert store.data == objects


@pytest.mark.parametrize("name,value", [
    ("FILES", "0"), ("FILES", "201"), ("FILES", "invalid"), ("BYTES", "0"), ("BYTES", str(15 * 1024**3 + 1))])
def test_invalid_limits_fail_without_transfer(imports, tmp_path, monkeypatch, name, value):
    client, _, _, _, store = setup(imports)
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    monkeypatch.setenv("FAMA_IMPORT_SYNC_BATCH_" + name, value)
    assert sync(client, source)["status"] == "failed"
    assert store.data == {} and store.calls == []
    assert ref(client, dataset).status_code == 404


def test_reconstruction_authorization_integrity_cleanup_and_generation(imports, tmp_path):
    from app.routes.dataset_imports import get_import_user
    from app.models.dataset_import_metadata import DatasetMember, ImportFile
    from app.models.dataset_import_revision import RevisionObject
    client, service, app, sessions, store = setup(imports)
    source = prepare(client, tmp_path, root="wrapper", entries=[
        ("wrapper/birds/session/a.wav", wav_bytes()), ("wrapper/birds/duplicate.wav", wav_bytes())])
    dataset = confirm(client, source).json()["dataset_id"]
    assert sync(client, source)["status"] == "succeeded"
    reference = ref(client, dataset).json()
    identity = reference["manifest"]
    url = f"{BASE}/datasets/{dataset}/revisions/1/manifest"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-length"] == str(len(response.content))
    assert response.headers["etag"] == '"' + hashlib.sha256(response.content).hexdigest() + '"'
    body = response.json()
    assert body["file_count"] == 1 and len(body["files"]) == 1
    member = body["files"][0]
    assert member["original_path"] == "wrapper/birds/session/a.wav"
    assert member["relative_path"] == "birds/session/a.wav"
    assert member["source_import_id"] == source["id"]
    assert store.data[member["object_key"]][0] == wav_bytes()
    assert member["size_bytes"] == len(wav_bytes())
    assert member["sha256"] == hashlib.sha256(wav_bytes()).hexdigest()
    for bad in (str(service.root), "https://", "token", "password"):
        assert bad not in response.text
    # Rejected reads and admissions leave the entire database byte-equivalent.
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    for path in (url, url.removesuffix("/manifest")):
        before = dump(sessions)
        rejected = client.get(path)
        assert rejected.status_code == 404
        assert dump(sessions) == before
    before = dump(sessions)
    assert client.post(f"{BASE}/{source['id']}/sync", json={"request_key": "foreign"}).status_code == 404
    assert dump(sessions) == before
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    for corrupt in ("generation", "bytes"):
        data, meta = store.data[identity["object_key"]]
        if corrupt == "generation":
            store.generation[identity["object_key"]] = "8"
        else:
            store.data[identity["object_key"]] = (b"x" * len(data), meta)
        before = dump(sessions)
        rejected = client.get(url)
        assert rejected.status_code == 409
        assert rejected.json() == {"detail": "El manifiesto no está disponible con la integridad y generación autorizadas."}
        assert dump(sessions) == before
        store.generation.clear()
        store.data[identity["object_key"]] = (data, meta)
    # Neither original ZIP, local WAVs nor either membership list supplies recovery.
    for path in service.root.rglob("*.zip"):
        path.unlink()
    for path in (service.root / "objects").rglob("*.wav"):
        path.unlink()
    with sessions() as db:
        db.query(RevisionObject).delete()
        db.query(DatasetMember).delete()
        db.query(ImportFile).delete()
        db.commit()
    before = dump(sessions)
    assert client.get(url).content == response.content
    assert dump(sessions) == before
    assert store.data[identity["object_key"]][0] == response.content


def test_migration_cli_exact_success_failure_and_atomicity(monkeypatch, capsys):
    from scripts.migrate_dataset_import_revisions import main
    import sqlalchemy
    engine = sqlalchemy.create_engine("sqlite://")
    monkeypatch.setattr(engine, "dispose", lambda: None)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda url: engine)
    assert main(["--database-url", "sqlite://", "--writers-stopped"]) == 0
    assert capsys.readouterr().out == '{"version": 1, "verified": true}\n'
    assert main(["--database-url", "sqlite://", "--writers-stopped"]) == 0
    assert capsys.readouterr().out == '{"version": 1, "verified": true}\n'
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE imported_dataset_revision_object")
        conn.exec_driver_sql("CREATE TABLE imported_dataset_revision_object (original TEXT)")
        conn.exec_driver_sql("INSERT INTO imported_dataset_revision_object VALUES ('retained')")
    sessions = SimpleNamespace(kw={"bind": engine})
    before = dump(sessions)
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "sqlite://", "--writers-stopped"])
    assert error.value.code == 1
    assert capsys.readouterr().err == "Revision migration failed; preserve state and inspect the maintenance procedure.\n"
    assert dump(sessions) == before


@pytest.mark.parametrize("failure", ["integrity", "generation", "publication"])
def test_partial_failure_preserves_historical_complete_revision(imports, tmp_path, failure):
    from app.services.dataset_import_storage import IntegrityConflict, TransientSyncError
    client, _, _, sessions, store = setup(imports)
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    assert sync(client, source)["status"] == "succeeded"
    old = ref(client, dataset).json()
    previous = dict(store.data)
    extension = prepare(client, tmp_path, key="more", target_id=dataset, sample=2)
    confirm(client, extension)
    original = store.ensure
    attempted = []

    def fail(key, *args):
        attempted.append(key)
        if key.endswith(".json"):
            if failure == "publication":
                raise TransientSyncError("independent outage")
        elif failure == "integrity":
            raise IntegrityConflict("independent bad bytes")
        elif failure == "generation" and key in previous:
            return "8"
        return original(key, *args)

    store.ensure = store.ensure_manifest = fail
    assert sync(client, extension, "partial")["status"] == "failed"
    assert ref(client, dataset).json() == old
    partial = ref(client, dataset, 2).json()
    assert partial["status"] == "pending" and partial["manifest"] is None
    assert partial["verified_count"] < 2 if failure != "publication" else partial["verified_count"] == 2
    if failure == "publication":
        assert sum(k.endswith(".json") for k in attempted) == 3
    assert all(store.data[key] == value for key, value in previous.items())
    store.ensure = store.ensure_manifest = original
    assert sync(client, extension, "recover")["status"] == "succeeded"
    assert ref(client, dataset, 2).json()["file_count"] == 2
    assert ref(client, dataset).json() == old


def test_real_gcs_adapter_fakeclient_recovery_fences_and_cleanup_guard(imports, tmp_path):
    from google.api_core.exceptions import NotFound, PreconditionFailed
    from app.services.dataset_import_storage import GCSImportStorage
    from app.routes.dataset_imports import get_import_storage
    from pathlib import Path
    client, service, app, sessions, _ = setup(imports)
    blobs = {}

    class Blob:
        def __init__(self, key, generation=None):
            self.key, self.requested = key, generation

        def reload(self, **kwargs):
            if self.key not in blobs:
                raise NotFound("synthetic absent")
            self.data, self.metadata, self.generation = blobs[self.key]
            self.size = len(self.data)

        def upload_from_filename(self, filename, **kwargs):
            assert kwargs["if_generation_match"] == 0
            if self.key in blobs:
                raise PreconditionFailed("already exists")
            blobs[self.key] = (Path(filename).read_bytes(), self.metadata, "11")

        def download_to_file(self, sink, **kwargs):
            data, metadata, generation = blobs[self.key]
            assert kwargs["if_generation_match"] == 11
            assert kwargs["raw_download"] is True
            assert self.requested is None or self.requested == 11
            sink.write(data)

    bucket = SimpleNamespace(blob=lambda key, generation=None: Blob(key, generation))
    storage = GCSImportStorage("private-synthetic", SimpleNamespace(bucket=lambda name: bucket))
    app.dependency_overrides[get_import_storage] = lambda: storage
    client.execution.storage = storage
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    # During remote transfer a rejected cancellation cannot alter persistent state.
    original = storage.ensure

    def ensure(*args):
        before = dump(sessions)
        rejected = client.post(f"{BASE}/{source['id']}/cancel")
        assert rejected.status_code == 409
        assert dump(sessions) == before
        with sessions() as db:
            service.cleanup(db)
        assert (service.root / "objects" / source["id"]).is_dir()
        return original(*args)

    storage.ensure = ensure
    assert sync(client, source)["status"] == "succeeded"
    reference = ref(client, dataset).json()
    url = f"{BASE}/datasets/{dataset}/revisions/1/manifest"
    manifest = client.get(url)
    assert manifest.status_code == 200
    entry = manifest.json()["files"][0]
    assert entry["object_generation"] == "11"
    assert blobs[entry["object_key"]][0] == wav_bytes()
    key = reference["manifest"]["object_key"]
    data, metadata, generation = blobs[key]
    blobs[key] = (b"x" * len(data), metadata, generation)
    before = dump(sessions)
    response = client.get(url)
    assert response.status_code == 409
    assert response.json() == {"detail": "El manifiesto no está disponible con la integridad y generación autorizadas."}
    assert dump(sessions) == before
