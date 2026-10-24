"""Separate synchronization interface with controlled object storage, never GCS."""
import hashlib
from types import SimpleNamespace
import pytest
from tests.test_dataset_import_api import imports, prepare, confirm, operation


class MemoryObjects:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail_key = None
        self.manifests = {}

    def ensure_manifest(self, key, path, sha256, metadata):
        # Manifest identity lives separately from the original-WAV assertions.
        data = path.read_bytes()
        from app.services.dataset_import_storage import IntegrityConflict
        if hashlib.sha256(data).hexdigest() != sha256:
            raise IntegrityConflict("manifest digest mismatch")
        if key in self.manifests and self.manifests[key] != (data, metadata):
            raise IntegrityConflict("immutable manifest conflict")
        self.manifests[key] = (data, metadata)
        return "1"

    def ensure(self, key, path, sha256, metadata):
        from app.services.dataset_import_storage import TransientSyncError, IntegrityConflict
        self.calls.append(key)
        if self.fail_key and self.fail_key in key:
            raise TransientSyncError("simulated timeout")
        data = path.read_bytes()
        if key in self.objects:
            old, old_meta = self.objects[key]
            if hashlib.sha256(old).hexdigest() != sha256 or old_meta != metadata:
                raise IntegrityConflict("remote content mismatch")
        else:
            self.objects[key] = (data, metadata)
        return "1"


def test_sync_progress_survives_partial_failure_and_retries_without_overwrite(imports, tmp_path):
    from app.routes.dataset_imports import get_import_storage
    from tests.test_dataset_zip_validation import wav_bytes
    client, service, app, _ = imports
    storage = MemoryObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    job = prepare(client, tmp_path, entries=[("birds/a.wav", wav_bytes()), ("birds/b.wav", wav_bytes(2))])
    imported = confirm(client, job).json()
    files = client.get(f"/api/ingestion/imports/datasets/{imported['dataset_id']}/files").json()["files"]
    storage.fail_key = files[1]["sha256"]
    path = f"/api/ingestion/imports/{job['id']}/sync"
    failed = operation(client, job["id"], "sync")
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    result = client.get(f"/api/ingestion/imports/{job['id']}").json()
    assert result["status"] == "imported"
    assert result["sync_status"] == "error"
    assert len(storage.objects) == 1
    assert storage.calls.count(next(k for k in storage.calls if storage.fail_key in k)) == 3
    assert result["preview"]["synced_count"] == 1
    assert (service.root / "objects" / job["id"]).is_dir()
    storage.fail_key = None
    resumed = operation(client, job["id"], "sync").json()
    assert resumed["sync_status"] == "synced"
    assert len(storage.objects) == 2
    for data, _ in storage.objects.values():
        assert hashlib.sha256(data).hexdigest() in {f["sha256"] for f in files}
    # A claimed sync is reverified, not inferred from persisted counts.
    key = next(iter(storage.objects))
    _, metadata = storage.objects[key]
    storage.objects[key] = (b"wrong", metadata)
    assert operation(client, job["id"], "sync").json()["status"] == "failed"
    wrong = client.get(f"/api/ingestion/imports/{job['id']}").json()
    assert wrong["sync_status"] == "error"
    assert storage.objects[key][0] == b"wrong"
    assert (service.root / "objects" / job["id"]).is_dir()


def test_sync_requires_confirmed_import_and_owner(imports, tmp_path):
    from types import SimpleNamespace
    from app.routes.dataset_imports import get_import_storage, get_import_user
    client, _, app, _ = imports
    storage = MemoryObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    job = prepare(client, tmp_path)
    path = f"/api/ingestion/imports/{job['id']}/sync"
    assert client.post(path, json={"request_key": "unconfirmed"}).status_code == 409
    confirm(client, job)
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.post(path, json={"request_key": "foreign"}).status_code == 404
    assert storage.calls == []


@pytest.mark.parametrize("mode", ["new", "existing", "race", "wrong_bytes", "wrong_metadata"])
def test_gcs_adapter_uses_conditional_creation_and_generation_bound_digest_verification(tmp_path, mode):
    from google.api_core.exceptions import NotFound, PreconditionFailed
    from app.services.dataset_import_storage import GCSImportStorage, IntegrityConflict
    from tests.test_dataset_zip_validation import wav_bytes
    path = tmp_path / "synthetic.wav"
    path.write_bytes(wav_bytes())
    digest = hashlib.sha256(wav_bytes()).hexdigest()
    identity = {"owner_id": "1", "dataset_id": "dataset", "class_name": "birds"}
    expected = dict(identity, sha256=digest)
    calls = []

    class Blob:
        generation = "7"
        size = len(wav_bytes())
        metadata = None
        exists = mode != "new" and mode != "race"
        def reload(self, **kwargs):
            assert kwargs == {"timeout": 10, "retry": None}
            if not self.exists:
                raise NotFound("missing")
            self.metadata = {} if mode == "wrong_metadata" else expected
        def upload_from_filename(self, filename, **kwargs):
            calls.append((filename, kwargs))
            assert kwargs == {"content_type": "audio/wav", "if_generation_match": 0, "timeout": 10, "retry": None}
            self.exists = True
            if mode == "race":
                raise PreconditionFailed("another writer")
        def download_to_file(self, sink, **kwargs):
            assert kwargs == {"if_generation_match": 7, "raw_download": True, "timeout": 10, "retry": None}
            sink.write(b"x" * self.size if mode == "wrong_bytes" else wav_bytes())

    blob = Blob()
    client = SimpleNamespace(bucket=lambda bucket: SimpleNamespace(blob=lambda key: blob))
    storage = GCSImportStorage("synthetic-bucket", client)
    if mode.startswith("wrong"):
        with pytest.raises(IntegrityConflict):
            storage.ensure("private-imports/1/dataset/audio.wav", path, digest, identity)
        assert calls == []
    else:
        assert storage.ensure("private-imports/1/dataset/audio.wav", path, digest, identity) == "7"
        assert len(calls) == (1 if mode in ("new", "race") else 0)


def test_manifest_adapter_creates_json_conditionally_and_verifies_exact_bytes(tmp_path):
    from google.api_core.exceptions import NotFound
    from app.services.dataset_import_storage import GCSImportStorage
    data = b'{"schema_version":1,"files":[]}'
    path = tmp_path / "manifest.json"
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    metadata = {"owner_id": "1", "dataset_id": "synthetic", "dataset_revision": "1"}
    calls = []
    class Blob:
        generation, size = "9", len(data)
        exists = False
        def reload(self, **kwargs):
            if not self.exists:
                raise NotFound("synthetic")
        def upload_from_filename(self, filename, **kwargs):
            calls.append(kwargs)
            self.exists = True
        def download_to_file(self, sink, **kwargs):
            assert kwargs["if_generation_match"] == 9 and kwargs["raw_download"] is True
            sink.write(data)
    blob = Blob()
    storage = GCSImportStorage("synthetic", SimpleNamespace(bucket=lambda _: SimpleNamespace(blob=lambda _: blob)))
    assert storage.ensure_manifest("private/manifest.json", path, digest, metadata) == "9"
    assert calls == [{"content_type": "application/json", "if_generation_match": 0, "timeout": 10, "retry": None}]
    assert storage.ensure_manifest("private/manifest.json", path, digest, metadata) == "9"
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["valid", "wrong_digest", "oversize", "generation_conflict"])
def test_manifest_adapter_recovers_only_authorized_generation_and_integrity(tmp_path, mode):
    from google.api_core.exceptions import PreconditionFailed
    from app.services.dataset_import_storage import GCSImportStorage, IntegrityConflict
    data = b'{"schema_version":1}'
    calls = []
    class Blob:
        def download_to_file(self, sink, **kwargs):
            assert kwargs == {"if_generation_match": 9, "raw_download": True, "timeout": 10, "retry": None}
            if mode == "generation_conflict":
                raise PreconditionFailed("synthetic")
            sink.write(data + b"x" if mode == "oversize" else b"x" * len(data) if mode == "wrong_digest" else data)
    def blob(key, **kwargs):
        calls.append((key, kwargs))
        return Blob()
    storage = GCSImportStorage("synthetic", SimpleNamespace(bucket=lambda _: SimpleNamespace(blob=blob)))
    with (tmp_path / "private.json").open("w+b") as target:
        if mode == "valid":
            storage.read_verified("authorized/manifest.json", "9", hashlib.sha256(data).hexdigest(), len(data), target)
            target.seek(0)
            assert target.read() == data
        else:
            with pytest.raises(IntegrityConflict):
                storage.read_verified("authorized/manifest.json", "9", hashlib.sha256(data).hexdigest(), len(data), target)
    assert calls == [("authorized/manifest.json", {"generation": 9})]
