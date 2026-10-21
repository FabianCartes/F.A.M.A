"""Shared physical promises through export HTTP admission and the public worker."""
from types import SimpleNamespace

import pytest

from tests.test_dataset_exports import exported_source, admit  # noqa: F401
from tests.test_dataset_import_api import imports  # noqa: F401
from tests.test_dataset_import_storage import configure
from tests.test_dataset_import_receipts import dump
from tests.test_dataset_zip_validation import wav_bytes


def active_queue(source, monkeypatch, *, free):
    from app.routes.dataset_exports import get_export_queue
    from app.services.dataset_exports import ExportLimits, ExportQueue

    client, service, app, sessions, _, _, _ = source
    policy = configure((client, service, app, sessions), monkeypatch, free=free)
    monkeypatch.setenv("FAMA_EXPORT_ROOT", str(policy.roots["exports"]))
    queue = ExportQueue(sessions, service, limits=ExportLimits(
        files=1, bytes=len(wav_bytes()), manifest_bytes=10000))
    app.dependency_overrides[get_export_queue] = lambda: queue
    return queue, policy


def grants(sessions):
    from sqlalchemy import select
    from app.models.dataset_storage import StorageGrant
    with sessions() as db:
        return db.execute(select(StorageGrant.__table__).order_by(StorageGrant.id)).all()


def test_export_admission_charges_manifest_payload_and_zip64_before_growth(
        exported_source, monkeypatch):
    # Max UTF-8 archive name: dataset 1024 + '/' + relative 1024 = 2049.
    # Per member: local 30 + ZIP64 20 + central 46 + ZIP64 <=32 + 2 names.
    # End records: classic 22 + ZIP64 56 + locator 20 = 98.
    envelope = 10000 + len(wav_bytes()) + 4226 + 98
    queue, policy = active_queue(exported_source, monkeypatch, free=envelope + 4)
    client, _, _, sessions, _, dataset, _ = exported_source
    url = f"/api/ingestion/imports/datasets/{dataset}/revisions/1/exports"
    before = dump(sessions)
    paths = set(policy.roots["exports"].iterdir())
    response = client.post(url, json={"request_key": "physical"})
    assert response.status_code == 507, response.text
    assert dump(sessions) == before
    assert set(policy.roots["exports"].iterdir()) == paths
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=envelope + 5))
    accepted = client.post(url, json={"request_key": "physical"})
    assert accepted.status_code == 202, accepted.text
    stored = grants(sessions)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=5))
    assert client.post(url, json={"request_key": "physical"}).json() == accepted.json()
    assert grants(sessions) == stored
    assert queue.get(1, accepted.json()["id"])["status"] == "queued"


def test_active_marker_without_export_policy_refuses_without_mutation(exported_source, monkeypatch):
    _, _ = active_queue(exported_source, monkeypatch, free=10**9)
    client, service, _, sessions, _, dataset, _ = exported_source
    service.storage_policy = None
    before = dump(sessions)
    response = client.post(f"/api/ingestion/imports/datasets/{dataset}/revisions/1/exports",
                           json={"request_key": "unconfigured"})
    assert response.status_code == 503, response.text
    assert dump(sessions) == before


def test_legacy_expired_export_is_not_adopted_on_a_later_attempt(exported_source, monkeypatch):
    from app.services.dataset_exports import ExportExecution, ExportQueue
    from app.models.dataset_export import DatasetExport
    client, service, _, sessions, storage, dataset, _ = exported_source
    job = admit(client, dataset)
    legacy = ExportQueue(sessions, service, clock=lambda: 100)
    assert legacy.claim(lease_seconds=1)["attempt"] == 1
    queue, policy = active_queue(exported_source, monkeypatch, free=10**9)
    with sessions.begin() as db:
        db.get(DatasetExport, job["id"]).lease_until = 0
    before = set(policy.roots["exports"].iterdir())
    assert ExportExecution(queue, policy.roots["exports"], storage=storage).run_once()
    assert queue.get(1, job["id"])["status"] == "failed"
    assert set(policy.roots["exports"].iterdir()) == before
    assert grants(sessions) == []


def test_export_grants_compete_with_import_and_retire_without_deleting_artifact(
        exported_source, monkeypatch):
    import io
    import zipfile
    from app.services.dataset_exports import ExportExecution
    from tests.test_dataset_import_receipts import create, start
    client, _, _, sessions, storage, dataset, _ = exported_source
    queue, policy = active_queue(exported_source, monkeypatch, free=10**9)
    job = admit(client, dataset)
    promised = grants(sessions)[0].envelope_bytes
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=promised + 5))
    identity = create(client)
    assert start(client, identity, size=10).status_code == 507
    assert ExportExecution(queue, policy.roots["exports"], storage=storage).run_once()
    result = queue.get(1, job["id"])
    assert result["status"] == "succeeded", result
    assert all(row.state == "retired" for row in grants(sessions))
    artifact = policy.roots["exports"] / result["artifact"]
    with zipfile.ZipFile(io.BytesIO(artifact.read_bytes())) as archive:
        assert archive.read("Birds/birds/a.wav") == wav_bytes()
    assert start(client, identity, size=10).status_code == 200
    assert artifact.is_file()  # Retirement is not space reclamation.


@pytest.mark.parametrize("fits", [False, True])
def test_retry_needs_fresh_capacity_and_keeps_prior_attempt_charge(exported_source, monkeypatch, fits):
    from app.services.dataset_exports import ExportExecution
    client, _, _, sessions, storage, dataset, _ = exported_source
    queue, policy = active_queue(exported_source, monkeypatch, free=10**9)
    now = [100.0]
    queue.jobs.clock = lambda: now[0]
    job = admit(client, dataset)
    read = storage.read_verified
    def expired(*args):
        result = read(*args)
        if args[0].endswith(".wav"):
            now[0] = 200.0
        return result
    storage.read_verified = expired
    assert ExportExecution(queue, policy.roots["exports"], storage=storage,
        heartbeat_wait=lambda stop, interval: stop.wait()).run_once()
    assert queue.get(1, job["id"])["status"] == "running"
    amount = grants(sessions)[0].envelope_bytes
    paths = set(policy.roots["exports"].iterdir())
    storage.read_verified = read
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=2 * amount + 4 + fits))
    assert ExportExecution(queue, policy.roots["exports"], storage=storage).run_once()
    assert queue.get(1, job["id"])["status"] == ("succeeded" if fits else "failed")
    assert len(set(policy.roots["exports"].iterdir()) - paths) == int(fits)
    assert len(grants(sessions)) == 1 + fits
    assert sum(row.state == "live" for row in grants(sessions)) == 1
    assert queue.cleanup(policy.roots["exports"])["completed"] == 1
    assert all(row.state == "retired" for row in grants(sessions))


@pytest.mark.parametrize("fault", ["manifest-overrun", "payload-overrun", "floor"])
def test_active_export_bounds_each_writer_and_preserves_failed_attempt_for_cleanup(
        exported_source, monkeypatch, fault):
    from app.services.dataset_exports import ExportExecution
    client, _, _, sessions, storage, dataset, _ = exported_source
    queue, policy = active_queue(exported_source, monkeypatch, free=10**9)
    job = admit(client, dataset)
    read = storage.read_verified
    def broken(key, generation, digest, size, destination):
        if fault == "manifest-overrun" and key.endswith(".json"):
            destination.write(b"x" * (size + 1))
        elif fault == "payload-overrun" and key.endswith(".wav"):
            destination.write(b"x" * (size + 1))
        else:
            if fault == "floor" and key.endswith(".wav"):
                monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                                    lambda _: SimpleNamespace(free=4))
            return read(key, generation, digest, size, destination)
    storage.read_verified = broken
    assert ExportExecution(queue, policy.roots["exports"], storage=storage).run_once()
    result = queue.get(1, job["id"])
    assert result["status"] == "failed" and result["sha256"] is None
    assert grants(sessions)[0].state == "live"
    paths = list(policy.roots["exports"].glob(job["id"] + "-*"))
    assert len(paths) == 1
    assert not (paths[0] / "export.zip").exists()
    if fault == "manifest-overrun":
        assert (paths[0] / "manifest.json").stat().st_size == 0
    assert queue.cleanup(policy.roots["exports"])["completed"] == 1
    assert grants(sessions)[0].state == "retired"


def test_retained_download_lock_blocks_cleanup_after_grant_retirement(exported_source, monkeypatch):
    import fcntl
    import os
    from app.services.dataset_exports import ExportExecution
    from app.models.dataset_export import DatasetExport
    client, _, _, sessions, storage, dataset, _ = exported_source
    queue, policy = active_queue(exported_source, monkeypatch, free=10**9)
    job = admit(client, dataset)
    assert ExportExecution(queue, policy.roots["exports"], storage=storage).run_once()
    result = queue.get(1, job["id"])
    path = policy.roots["exports"] / result["artifact"]
    data = path.read_bytes()
    with sessions.begin() as db:
        db.get(DatasetExport, job["id"]).expires_at = 0
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        assert queue.cleanup(policy.roots["exports"])["busy"] == 1
        assert path.read_bytes() == data
        assert all(row.state == "retired" for row in grants(sessions))
    finally:
        os.close(fd)
    assert queue.cleanup(policy.roots["exports"])["completed"] == 1
    assert not path.exists()


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("mode", ["policy", "retired", "legacy"])
def test_initial_authority_cannot_be_reinterpreted_or_resurrected(
        exported_source, monkeypatch, mode, retry):
    # Promoted from the independent verifier's authority/refusal probes.
    from dataclasses import replace
    from app.models.dataset_export import DatasetExport
    from app.models.dataset_storage import StorageGrant
    from app.services.dataset_exports import ExportExecution
    client, service, _, sessions, storage, dataset, _ = exported_source
    if mode == "legacy":
        job = admit(client, dataset)
    queue, policy = active_queue(exported_source, monkeypatch, free=10**9)
    if mode != "legacy":
        job = admit(client, dataset)
    if retry:
        assert queue.claim(lease_seconds=1)["attempt"] == 1
        with sessions.begin() as db:
            db.get(DatasetExport, job["id"]).lease_until = 0
    if mode == "policy":
        queue.limits = replace(queue.limits, bytes=queue.limits.bytes + 1)
    elif mode == "retired":
        with sessions.begin() as db:
            for grant in db.query(StorageGrant):
                grant.state = "retired"
    before = grants(sessions)
    assert ExportExecution(queue, policy.roots["exports"], storage=storage, execution_seconds=1).run_once()
    result = queue.get(1, job["id"])
    assert (result["attempt"], result["status"], result["error"]) == (1 + retry, "failed", "staging_failed")
    assert grants(sessions) == before
    assert not list(policy.roots["exports"].glob(job["id"] + "-*"))


def test_callback_timeout_keeps_charge_until_actual_exit(exported_source, monkeypatch):
    import threading
    from app.services.dataset_exports import ExportExecution
    client, _, _, sessions, storage, dataset, _ = exported_source
    queue, policy = active_queue(exported_source, monkeypatch, free=10**9)
    job = admit(client, dataset)
    entered, release = threading.Event(), threading.Event()
    read = storage.read_verified
    def blocked(key, *args):
        if key.endswith(".wav"):
            entered.set()
            assert release.wait(5)
        return read(key, *args)
    storage.read_verified = blocked
    execution = ExportExecution(queue, policy.roots["exports"], storage=storage, execution_seconds=1)
    try:
        assert execution.run_once() and entered.is_set()
        assert queue.get(1, job["id"])["error"] == "execution_timeout"
        before = grants(sessions)
        assert queue.cleanup(policy.roots["exports"]) == {"completed": 0, "busy": 1, "failed": 0}
        assert grants(sessions) == before and before[0].state == "live"
    finally:
        release.set()
        execution.worker._work.join(5)
    assert not execution.worker._work.is_alive()
    assert grants(sessions)[0].state == "live"
    assert queue.cleanup(policy.roots["exports"])["completed"] == 1
    assert grants(sessions)[0].state == "retired"


def test_full_utf8_names_and_zip64_central_records_fit_the_grant(exported_source, monkeypatch):
    import zipfile
    from app.services.dataset_exports import ExportExecution
    from tests.test_dataset_exports import rewrite_manifest
    client, _, _, sessions, storage, dataset, _ = exported_source
    relative = "birds/" + "a" * 1014 + ".wav"
    def change(header):
        header["name"] = "d" * 1024
        header["files"][0]["relative_path"] = relative
    rewrite_manifest(exported_source, change)
    queue, policy = active_queue(exported_source, monkeypatch, free=10**9)
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 1)
    job = admit(client, dataset)
    amount = grants(sessions)[0].envelope_bytes
    assert ExportExecution(queue, policy.roots["exports"], storage=storage, execution_seconds=1).run_once()
    result = queue.get(1, job["id"])
    assert result["status"] == "succeeded"
    path = policy.roots["exports"] / result["artifact"]
    data = path.read_bytes()
    assert all(record in data for record in (b"PK\x06\x06", b"PK\x06\x07", b"PK\x01\x02"))
    assert len(data) + (path.parent / "manifest.json").stat().st_size <= amount
    with zipfile.ZipFile(path) as archive:
        member, = archive.infolist()
        assert len(member.filename.encode()) == 2049
        assert archive.read(member.filename) == wav_bytes()
