"""Full revision manifests through authenticated HTTP and the public worker."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from tests.test_dataset_import_api import imports, prepare, confirm, operation
from tests.test_dataset_import_sync import MemoryObjects
from tests.test_dataset_zip_validation import wav_bytes


class ManifestObjects(MemoryObjects):
    def ensure_manifest(self, key, path, sha256, metadata):
        return self.ensure(key, path, sha256, metadata)

    def read_verified(self, key, generation, sha256, size_bytes, destination):
        from app.services.dataset_import_storage import IntegrityConflict
        data = self.objects[key][0]
        if generation != "1" or len(data) != size_bytes or hashlib.sha256(data).hexdigest() != sha256:
            raise IntegrityConflict("manifest identity mismatch")
        destination.write(data)


def test_sync_publishes_full_immutable_revision_not_only_initiating_import(imports, tmp_path):
    from app.routes.dataset_imports import get_import_storage
    client, _, app, _ = imports
    storage = ManifestObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    first = prepare(client, tmp_path)
    dataset = confirm(client, first).json()["dataset_id"]
    second = prepare(client, tmp_path, key="second", target_id=dataset, sample=2)
    confirm(client, second)
    assert operation(client, second["id"], "sync").json()["sync_status"] == "synced"
    response = client.get(f"/api/ingestion/imports/datasets/{dataset}/revisions/2")
    assert response.status_code == 200, response.text
    reference = response.json()
    assert reference["status"] == "complete"
    assert reference["file_count"] == 2
    data = storage.objects[reference["manifest"]["object_key"]][0]
    manifest = json.loads(data)
    assert manifest["dataset_revision"] == 2
    assert manifest["name"] == "Birds" and manifest["description"] == "Synthetic"
    assert manifest["file_count"] == 2
    assert manifest["total_size_bytes"] == 2 * len(wav_bytes())
    assert {f["source_import_id"] for f in manifest["files"]} == {first["id"], second["id"]}
    assert {f["sha256"] for f in manifest["files"]} == {
        hashlib.sha256(wav_bytes()).hexdigest(), hashlib.sha256(wav_bytes(2)).hexdigest()}
    assert all(f["class_name"] == "birds" and f["object_generation"] == "1" for f in manifest["files"])
    assert all(f["relative_path"].startswith("birds/") and f["original_path"].startswith("birds/") for f in manifest["files"])
    assert len(storage.objects) == 3
    assert hashlib.sha256(data).hexdigest() == reference["manifest"]["sha256"]
    assert operation(client, first["id"], "sync").json()["sync_status"] == "synced"
    assert client.get(response.request.url).json() == reference
    assert storage.objects[reference["manifest"]["object_key"]][0] == data


def test_authorized_manifest_recovers_without_zip_or_local_membership(imports, tmp_path):
    from app.routes.dataset_imports import get_import_storage, get_import_user
    from app.models.dataset_import_metadata import DatasetMember, ImportFile
    client, service, app, sessions = imports
    storage = ManifestObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    operation(client, source["id"], "sync")
    path = f"/api/ingestion/imports/datasets/{dataset}/revisions/1/manifest"
    # Simulate loss of disposable/local membership sources after publication.
    (service.root / "staging" / source["id"] / "archive.zip").unlink()
    with sessions() as db:
        db.query(DatasetMember).filter_by(dataset_id=dataset).delete()
        db.query(ImportFile).filter_by(import_id=source["id"]).delete()
        db.commit()
    response = client.get(path)
    assert response.status_code == 200, response.text
    manifest = response.json()
    assert manifest["file_count"] == 1
    entry = manifest["files"][0]
    assert storage.objects[entry["object_key"]][0] == wav_bytes()
    assert entry["original_path"] == entry["relative_path"] == "birds/a.wav"
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.get(path).status_code == 404
    assert client.get(path.removesuffix("/manifest")).status_code == 404
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    reference = client.get(path.removesuffix("/manifest")).json()
    key = reference["manifest"]["object_key"]
    storage.objects[key] = (b"tampered", storage.objects[key][1])
    rejected = client.get(path)
    assert rejected.status_code == 409
    assert b"tampered" not in rejected.content


@pytest.mark.parametrize("interruption", ["object", "manifest"])
def test_reclaimed_job_reverifies_remote_creation_before_checkpoint(imports, tmp_path, interruption):
    from tests.test_dataset_import_execution import executor
    from app.services.dataset_import_execution import ImportExecution
    client, _, _, _ = imports
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    queue, execution = executor(imports, tmp_path)
    execution.worker.heartbeat_wait = lambda stop, interval: stop.wait()

    class Interrupted(ManifestObjects):
        def ensure(self, *args):
            value = super().ensure(*args)
            if interruption == "object" and args[0].endswith(".wav"):
                queue.clock = lambda: 200.0
            return value

        def ensure_manifest(self, *args):
            value = super().ensure_manifest(*args)
            if interruption == "manifest":
                queue.clock = lambda: 200.0
            return value

    storage = execution.storage = Interrupted()
    job = queue.admit(1, source["id"], "sync", "interrupted", {})
    assert execution.run_once()
    before = client.get(f"/api/ingestion/imports/datasets/{dataset}/revisions/1").json()
    assert before["status"] == "pending" and before["manifest"] is None
    assert before["verified_count"] == (0 if interruption == "object" else 1)
    assert queue.get(1, job["id"])["status"] == "running"
    objects = dict(storage.objects)
    # A new executor, same persisted job, higher token; verify without overwrite.
    storage.ensure = lambda *args: ManifestObjects.ensure(storage, *args)
    storage.ensure_manifest = lambda *args: ManifestObjects.ensure_manifest(storage, *args)
    replacement = ImportExecution(queue, execution.service, execution.root, storage=storage)
    assert replacement.run_once()
    settled = queue.get(1, job["id"])
    assert settled["status"] == "succeeded" and settled["attempt"] == 2
    assert client.get(f"/api/ingestion/imports/datasets/{dataset}/revisions/1").json()["status"] == "complete"
    assert all(storage.objects[key] == value for key, value in objects.items())
    assert len(storage.objects) == 2
    assert len([key for key in storage.calls if key.endswith(".wav")]) == 2


@pytest.mark.parametrize("conflict", ["generation", "manifest_generation", "integrity"])
def test_verified_identity_conflicts_never_overwrite_complete_manifest(imports, tmp_path, conflict):
    from app.routes.dataset_imports import get_import_storage
    client, _, app, _ = imports
    storage = ManifestObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    operation(client, source["id"], "sync")
    url = f"/api/ingestion/imports/datasets/{dataset}/revisions/1"
    reference = client.get(url).json()
    original = dict(storage.objects)
    if conflict == "generation":
        ensure = storage.ensure
        storage.ensure = lambda *args: "2" if args[0].endswith(".wav") else ensure(*args)
    elif conflict == "manifest_generation":
        storage.ensure_manifest = lambda *args: "2"
    else:
        key = next(k for k in storage.objects if k.endswith(".wav"))
        storage.objects[key] = (b"wrong", storage.objects[key][1])
    assert operation(client, source["id"], "sync").json()["status"] == "failed"
    assert client.get(url).json() == reference
    manifest_key = reference["manifest"]["object_key"]
    assert storage.objects[manifest_key] == original[manifest_key]


@pytest.mark.parametrize("bound", ["files", "bytes"])
def test_batches_checkpoint_with_count_byte_and_serial_concurrency_bounds(imports, tmp_path, monkeypatch, bound):
    from app.routes.dataset_imports import get_import_storage
    client, _, app, _ = imports
    monkeypatch.setenv("FAMA_IMPORT_SYNC_BATCH_FILES", "2" if bound == "files" else "3")
    monkeypatch.setenv("FAMA_IMPORT_SYNC_BATCH_BYTES", str(len(wav_bytes()) * (3 if bound == "files" else 2)))
    source = prepare(client, tmp_path, entries=[(f"birds/{i}.wav", wav_bytes(i)) for i in range(1, 4)])
    dataset = confirm(client, source).json()["dataset_id"]
    observed = []

    class Observe(ManifestObjects):
        busy = False
        def ensure(self, *args):
            assert not self.busy
            self.busy = True
            try:
                if args[0].endswith(".wav"):
                    state = client.get(f"/api/ingestion/imports/datasets/{dataset}/revisions/1").json()
                    observed.append(state["verified_count"])
                    assert state["status"] == "pending" and state["manifest"] is None
                return super().ensure(*args)
            finally:
                self.busy = False

    app.dependency_overrides[get_import_storage] = lambda: storage
    storage = Observe()
    assert operation(client, source["id"], "sync").json()["sync_status"] == "synced"
    assert observed == [0, 0, 2]


def test_manifest_failure_keeps_revision_partial_until_explicit_retry(imports, tmp_path):
    from app.routes.dataset_imports import get_import_storage
    from app.services.dataset_import_storage import TransientSyncError
    client, _, app, _ = imports
    storage = ManifestObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    def unavailable(*args):
        raise TransientSyncError("synthetic interrupted publication")
    storage.ensure_manifest = unavailable
    assert operation(client, source["id"], "sync").json()["status"] == "failed"
    path = f"/api/ingestion/imports/datasets/{dataset}/revisions/1"
    partial = client.get(path).json()
    assert partial["verified_count"] == 1 and partial["status"] == "pending" and partial["manifest"] is None
    assert client.get(path + "/manifest").status_code == 409
    storage.ensure_manifest = lambda *args: ManifestObjects.ensure_manifest(storage, *args)
    assert operation(client, source["id"], "sync").json()["sync_status"] == "synced"
    assert client.get(path).json()["status"] == "complete"


def test_changed_current_revision_never_inherits_frozen_snapshot_completion(imports, tmp_path):
    from dataclasses import replace
    from tests.test_dataset_import_execution import executor
    from app.services.dataset_import_execution import ImportExecution
    client, _, _, _ = imports
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    extension = prepare(client, tmp_path, key="extension", target_id=dataset, sample=2)
    queue, execution = executor(imports, tmp_path)
    queue.limits = replace(queue.limits, owner_active=2)
    other = ImportExecution(queue, execution.service, execution.root)

    class Advance(ManifestObjects):
        changed = False
        def ensure(self, *args):
            if not self.changed:
                self.changed = True
                admitted = queue.admit(1, extension["id"], "confirm", "advance", {"preview_token": extension["preview_token"]})
                assert other.run_once()
                assert queue.get(1, admitted["id"])["status"] == "succeeded"
            return super().ensure(*args)

    storage = execution.storage = Advance()
    admitted = queue.admit(1, source["id"], "sync", "frozen", {})
    assert execution.run_once()
    assert queue.get(1, admitted["id"])["status"] == "succeeded"
    assert queue.get(1, admitted["id"])["result"]["dataset_revision"] == 1
    assert client.get(f"/api/ingestion/imports/{source['id']}").json()["sync_status"] == "pending"
    path = f"/api/ingestion/imports/datasets/{dataset}/revisions/"
    ref = client.get(path + "1").json()
    assert ref["status"] == "complete" and ref["file_count"] == 1
    assert client.get(path + "2").status_code == 404
    next_job = queue.admit(1, extension["id"], "sync", "new-revision", {})
    assert execution.run_once()
    assert queue.get(1, next_job["id"])["status"] == "succeeded"
    assert client.get(path + "2").json()["file_count"] == 2
    assert client.get(path + "1").json() == ref


def test_new_revision_preserves_previously_verified_member_generation(imports, tmp_path):
    from app.routes.dataset_imports import get_import_storage
    client, _, app, _ = imports
    storage = ManifestObjects()
    app.dependency_overrides[get_import_storage] = lambda: storage
    source = prepare(client, tmp_path)
    dataset = confirm(client, source).json()["dataset_id"]
    operation(client, source["id"], "sync")
    old_digest = hashlib.sha256(wav_bytes()).hexdigest()
    extension = prepare(client, tmp_path, key="new-generation", target_id=dataset, sample=2)
    confirm(client, extension)
    original = storage.ensure
    storage.ensure = lambda *args: "2" if old_digest in args[0] else original(*args)
    assert operation(client, extension["id"], "sync").json()["status"] == "failed"
    path = f"/api/ingestion/imports/datasets/{dataset}/revisions/"
    assert client.get(path + "2").json()["manifest"] is None
    assert client.get(path + "1").json()["status"] == "complete"
