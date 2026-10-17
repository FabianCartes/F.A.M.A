"""Dataset quotas through authenticated HTTP and explicit worker execution."""
from dataclasses import replace
import hashlib

import pytest

from tests.test_dataset_import_api import imports, prepare, confirm, operation
from tests.test_dataset_zip_validation import archive, wav_bytes


BASE = "/api/ingestion/imports"


def catalog(client):
    response = client.get(f"{BASE}/datasets")
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_counts_unique_new_and_existing_content_once(imports, tmp_path):
    client, _, _, _ = imports
    first = confirm(client, prepare(client, tmp_path)).json()
    target = first["dataset_id"]
    size = len(wav_bytes())
    reviewed = prepare(client, tmp_path, key="dedup", target_id=target, entries=[
        ("birds/existing.wav", wav_bytes()), ("birds/new.wav", wav_bytes(2)),
        ("birds/repeated.wav", wav_bytes(2))])
    assert reviewed["status"] == "ready"
    assert reviewed["preview"]["quota"] == {
        "current_bytes": size, "current_files": 1, "new_bytes": size, "new_files": 1,
        "projected_bytes": size * 2, "projected_files": 2,
        "limit_bytes": 15 * 1024**3, "limit_files": 50000}
    assert reviewed["preview"]["new_count"] == 1
    published = confirm(client, reviewed).json()
    assert published["status"] == "imported"
    assert published["added_count"] == 1
    assert catalog(client)["datasets"][0]["total_size_bytes"] == size * 2


@pytest.mark.parametrize("dimension,code", [("dataset_bytes", "dataset_size_limit"),
                                           ("dataset_entries", "dataset_entry_limit")])
def test_exact_dataset_boundary_and_one_unit_over_reject_without_publication(imports, tmp_path, dimension, code):
    client, service, _, _ = imports
    size = len(wav_bytes())
    service.limits = replace(service.limits, dataset_bytes=size, dataset_entries=1)
    first = prepare(client, tmp_path)
    assert first["status"] == "ready"
    assert confirm(client, first).json()["status"] == "imported"
    target = catalog(client)["datasets"][0]["id"]
    before = catalog(client)
    members = client.get(f"{BASE}/datasets/{target}/files").json()
    # Two equal-sized unique WAVs exceed bytes by exactly one, or files by one.
    service.limits = replace(service.limits, dataset_bytes=2 * size - (dimension == "dataset_bytes"),
                             dataset_entries=1 if dimension == "dataset_entries" else 2)
    over = prepare(client, tmp_path, key="over", target_id=target, sample=2)
    assert over["status"] == "needs_correction"
    issues = client.get(f"{BASE}/{over['id']}/issues").json()["issues"]
    assert [i["code"] for i in issues if i["severity"] == "error"] == [code]
    assert confirm(client, over).status_code == 409
    assert catalog(client) == before
    assert client.get(f"{BASE}/datasets/{target}/files").json() == members
    assert not (service.root / "objects" / over["id"]).exists()


@pytest.mark.parametrize("phase", ["before_journal", "before_publication"])
def test_confirmation_rechecks_effective_limits_at_both_gates(imports, tmp_path, monkeypatch, phase):
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    reviewed = prepare(client, tmp_path)
    before = catalog(client)
    lower = lambda: setattr(service, "limits", replace(service.limits, dataset_bytes=len(wav_bytes()) - 1))
    if phase == "before_journal":
        lower()
    else:
        digest = module.digest_file
        def change_during_verification(path):
            result = digest(path)
            lower()
            return result
        monkeypatch.setattr(module, "digest_file", change_during_verification)
    failed = confirm(client, reviewed)
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed", failed.text
    assert catalog(client) == before
    assert not (service.root / "objects" / reviewed["id"]).exists()
    state = client.get(f"{BASE}/{reviewed['id']}").json()
    assert state["status"] == ("ready" if phase == "before_journal" else "committing")
    # A rejected journal remains recoverable once the operator restores capacity.
    service.limits = replace(service.limits, dataset_bytes=len(wav_bytes()))
    monkeypatch.undo()
    assert confirm(client, reviewed).json()["status"] == "imported"


def receive(client, tmp_path, key, *, target_id=None, sample=1):
    response = client.post(BASE, json={"request_key": key, "name": key, "target_id": target_id})
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    data = archive(tmp_path / f"{key}.zip", [("birds/a.wav", wav_bytes(sample))]).read_bytes()
    url = f"{BASE}/{identity}/receipt"
    receipt = client.post(url, json={"name": f"{key}.zip", "size_bytes": len(data)})
    assert receipt.status_code == 200, receipt.text
    chunk_bytes = receipt.json()["chunk_bytes"]
    for index, offset in enumerate(range(0, len(data), chunk_bytes)):
        chunk = data[offset:offset + chunk_bytes]
        uploaded = client.put(f"{url}/chunks/{index}", content=chunk, headers={
            "Content-Type": "application/octet-stream", "X-Chunk-Offset": str(offset),
            "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()})
        assert uploaded.status_code == 200, uploaded.text
    sealed = client.post(url + "/finalize")
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "sealed"
    return operation(client, identity, "preview", {"root": ""}).json()


def receipt_schema(sessions):
    from tests.test_dataset_import_receipts import migrate
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    migrate(sessions)
    migrate_chunks(sessions.kw["bind"], writers_stopped=True)


def test_fragmented_publication_releases_reservation_atomically_and_replay_is_inert(imports, tmp_path, monkeypatch):
    client, service, _, sessions = imports
    receipt_schema(sessions)
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", "100")
    service.limits = replace(service.limits, dataset_bytes=len(wav_bytes()), dataset_entries=1)
    reviewed = receive(client, tmp_path, "fragmented")
    url = f"{BASE}/{reviewed['id']}/receipt"
    assert client.get(url).json()["reserved_bytes"] > 0
    published = confirm(client, reviewed).json()
    assert published["status"] == "imported"
    assert client.get(url).json()["reserved_bytes"] == 0
    before = catalog(client)
    # Lowering a quota must not invalidate already-published idempotent replay.
    service.limits = replace(service.limits, dataset_bytes=1)
    assert confirm(client, reviewed).json()["added_count"] == 1
    assert catalog(client) == before
    members = client.get(f"{BASE}/datasets/{published['dataset_id']}/files").json()["files"]
    assert len(members) == 1
    downloaded = client.get(f"{BASE}/datasets/{published['dataset_id']}/files/{members[0]['sha256']}")
    assert downloaded.status_code == 200
    assert downloaded.content == wav_bytes()
    assert client.get(url).json()["reserved_bytes"] == 0


def test_inconsistent_dataset_summary_fails_closed_without_repair(imports, tmp_path):
    from app.models.dataset_import_metadata import DatasetSummary
    client, service, _, sessions = imports
    target = confirm(client, prepare(client, tmp_path)).json()["dataset_id"]
    reviewed = prepare(client, tmp_path, key="inconsistent", target_id=target, sample=2)
    with sessions() as db:
        db.get(DatasetSummary, target).class_count = 99
        db.commit()
    before = catalog(client)
    members = client.get(f"{BASE}/datasets/{target}/files").json()
    failed = confirm(client, reviewed)
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed", failed.text
    assert catalog(client) == before
    assert client.get(f"{BASE}/datasets/{target}/files").json() == members
    assert not (service.root / "objects" / reviewed["id"]).exists()


@pytest.mark.parametrize("when", ["preview", "confirm"])
def test_quota_rejection_retains_reservation_until_safe_cancel_or_retry(imports, tmp_path, when):
    client, service, _, sessions = imports
    receipt_schema(sessions)
    size = len(wav_bytes())
    if when == "preview":
        service.limits = replace(service.limits, dataset_bytes=size - 1)
    reviewed = receive(client, tmp_path, "reserved")
    url = f"{BASE}/{reviewed['id']}/receipt"
    promise = client.get(url).json()["reserved_bytes"]
    assert promise > 0
    if when == "preview":
        assert reviewed["status"] == "needs_correction"
        assert confirm(client, reviewed).status_code == 409
    else:
        service.limits = replace(service.limits, dataset_bytes=size - 1)
        assert confirm(client, reviewed).json()["status"] == "failed"
    assert client.get(url).json()["reserved_bytes"] == promise
    assert catalog(client)["datasets"] == []
    assert not (service.root / "objects" / reviewed["id"]).exists()
    assert client.post(f"{BASE}/{reviewed['id']}/cancel").status_code == 200
    assert client.get(url).json()["reserved_bytes"] == 0
    assert client.post(f"{BASE}/{reviewed['id']}/cancel").status_code == 200
    assert client.get(url).json()["reserved_bytes"] == 0


def test_duplicate_collection_and_label_conflict_keep_previous_behavior_at_capacity(imports, tmp_path):
    client, service, _, sessions = imports
    receipt_schema(sessions)
    service.limits = replace(service.limits, dataset_bytes=len(wav_bytes()), dataset_entries=1)
    first = confirm(client, receive(client, tmp_path, "first")).json()
    target = first["dataset_id"]
    before = catalog(client)
    duplicate = receive(client, tmp_path, "duplicate")
    assert duplicate["preview"]["duplicate_collection"] is True
    assert duplicate["preview"]["quota"]["new_files"] == 0
    assert duplicate["preview"]["quota"]["new_bytes"] == 0
    published = confirm(client, duplicate).json()
    assert published["status"] == "imported"
    assert published["added_count"] == 0 and published["dataset_id"] == target
    assert client.get(f"{BASE}/{duplicate['id']}/receipt").json()["reserved_bytes"] == 0
    conflict = prepare(client, tmp_path, key="conflict", target_id=target,
                       entries=[("motor/a.wav", wav_bytes())])
    assert conflict["status"] == "needs_correction"
    issues = client.get(f"{BASE}/{conflict['id']}/issues").json()["issues"]
    assert [i["code"] for i in issues if i["severity"] == "error"] == ["label_conflict"]
    assert confirm(client, conflict).status_code == 409
    assert catalog(client) == before


def test_two_reviewed_confirmations_cannot_publish_past_dataset_capacity(imports, tmp_path, monkeypatch):
    import threading
    from app.services import dataset_import_execution as module
    client, service, _, _ = imports
    target = confirm(client, prepare(client, tmp_path)).json()["dataset_id"]
    service.limits = replace(service.limits, dataset_bytes=2 * len(wav_bytes()), dataset_entries=2)
    first = prepare(client, tmp_path, key="competing-a", target_id=target, sample=2)
    second = prepare(client, tmp_path, key="competing-b", target_id=target, sample=3)
    assert first["status"] == second["status"] == "ready"
    monkeypatch.setenv("FAMA_IMPORT_JOBS_PER_OWNER", "2")
    client.execution.queue.limits = replace(client.execution.queue.limits, owner_active=2)
    admitted = [client.post(f"{BASE}/{source['id']}/confirm", json={
        "request_key": "competing", "preview_token": source["preview_token"]}) for source in (first, second)]
    assert [r.status_code for r in admitted] == [202, 202]
    blocked, release = threading.Event(), threading.Event()
    digest = module.digest_file
    def pause(path):
        result = digest(path)
        blocked.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(module, "digest_file", pause)
    client.execution.worker.heartbeat_wait = lambda stop, interval: stop.wait()
    results = []
    thread = threading.Thread(target=lambda: results.append(client.execution.run_once()))
    thread.start()
    try:
        assert blocked.wait(5)
        assert catalog(client)["datasets"][0]["file_count"] == 1
        assert client.get(admitted[1].json()["status_url"]).json()["status"] == "queued"
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and results == [True]
    monkeypatch.setattr(module, "digest_file", digest)
    assert client.execution.run_once()
    states = [client.get(r.json()["status_url"]).json()["status"] for r in admitted]
    assert states == ["succeeded", "failed"]
    current = catalog(client)["datasets"][0]
    assert (current["file_count"], current["revision"], current["total_size_bytes"]) == (2, 2, 2 * len(wav_bytes()))
    assert client.get(f"{BASE}/datasets/{target}/files").json()["total"] == 2
    assert not (service.root / "objects" / second["id"]).exists()
    assert confirm(client, second).status_code == 409


def test_recovery_rechecks_quota_and_releases_only_with_membership_commit(imports, tmp_path, monkeypatch):
    client, service, _, sessions = imports
    receipt_schema(sessions)
    reviewed = receive(client, tmp_path, "recover")
    url = f"{BASE}/{reviewed['id']}/receipt"
    promise = client.get(url).json()["reserved_bytes"]
    complete = client.execution.queue.complete_publication
    def interrupt(db, job, result):
        # An interruption after rename and reservation assignment must roll back
        # membership, source success and release, leaving the journal recoverable.
        raise OSError("synthetic interruption before publication commit")
    monkeypatch.setattr(client.execution.queue, "complete_publication", interrupt)
    assert confirm(client, reviewed).json()["status"] == "failed"
    assert (service.root / "objects" / reviewed["id"]).is_dir()
    assert catalog(client)["datasets"] == []
    assert client.get(url).json()["reserved_bytes"] == promise
    monkeypatch.setattr(client.execution.queue, "complete_publication", complete)
    service.limits = replace(service.limits, dataset_bytes=len(wav_bytes()) - 1)
    assert confirm(client, reviewed).json()["status"] == "failed"
    assert catalog(client)["datasets"] == []
    assert client.get(url).json()["reserved_bytes"] == promise
    service.limits = replace(service.limits, dataset_bytes=len(wav_bytes()))
    assert confirm(client, reviewed).json()["status"] == "imported"
    assert catalog(client)["datasets"][0]["file_count"] == 1
    assert client.get(url).json()["reserved_bytes"] == 0


def test_configured_dataset_limits_are_public_without_raising_archive_defaults(imports, monkeypatch):
    from app.services.dataset_zip import ImportLimits
    client, service, _, _ = imports
    monkeypatch.setenv("FAMA_IMPORT_DATASET_BYTES", "900")
    monkeypatch.setenv("FAMA_IMPORT_DATASET_ENTRIES", "3")
    service.limits = ImportLimits.from_environment()
    response = client.get(f"{BASE}/limits")
    assert response.status_code == 200
    limits = response.json()
    assert (limits["dataset_bytes"], limits["dataset_entries"]) == (900, 3)
    assert (limits["received_bytes"], limits["expanded_bytes"], limits["entries"]) == (64 * 1024**2, 256 * 1024**2, 2000)
