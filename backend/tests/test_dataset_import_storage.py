"""Physical promises observed through HTTP, workers and explicit maintenance."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_dataset_import_api import imports
from tests.test_dataset_import_receipts import BASE, create, dump, migrate, start


def test_inactive_public_unicode_description_still_synchronizes(imports, tmp_path):
    # S1,S4: existing valid request must retain its baseline success behavior.
    import json
    from tests.test_dataset_import_api import archive, wav_bytes, operation, confirm
    from tests.test_dataset_import_sync import MemoryObjects
    client, service, _, _ = imports
    created = client.post(BASE, json={'request_key':'unicode', 'name':'Birds', 'description':'🐦'*1400})
    assert created.status_code == 200, created.text
    identity = created.json()['id']
    data = archive(tmp_path/'unicode.zip', [('bird/a.wav', wav_bytes())]).read_bytes()
    assert client.put(f'{BASE}/{identity}/archive', content=data, headers={'Content-Type':'application/zip'}).status_code == 200
    preview = operation(client, identity, 'preview', {'root':''}).json()
    published = confirm(client, preview).json()
    assert published['status'] == 'imported'
    storage = MemoryObjects(); client.execution.storage = storage
    admitted = client.post(f'{BASE}/{identity}/sync', json={'request_key':'sync'})
    assert admitted.status_code == 202
    assert client.execution.run_once()
    result = client.get(admitted.json()['status_url']).json()
    assert result['status'] == 'succeeded', result
    manifest = next(iter(storage.manifests.values()))[0]
    assert json.loads(manifest)['description'] == '🐦'*1400
    assert b'\\ud83d\\udc26' * 1400 in manifest


def test_active_public_unicode_description_rejects_oversized_header(imports, monkeypatch, tmp_path):
    from tests.test_dataset_import_api import archive, wav_bytes, operation, confirm
    from tests.test_dataset_import_sync import MemoryObjects
    configure(imports, monkeypatch, free=10**9)
    client, service, _, _ = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    created = client.post(BASE, json={'request_key':'unicode', 'name':'Birds', 'description':'🐦'*1400})
    assert created.status_code == 200, created.text
    identity = created.json()['id']
    data = archive(tmp_path/'unicode.zip', [('bird/a.wav', wav_bytes())]).read_bytes()
    assert client.put(f'{BASE}/{identity}/archive', content=data, headers={'Content-Type':'application/zip'}).status_code == 200
    published = confirm(client, operation(client, identity, 'preview', {'root':''}).json()).json()
    assert published['status'] == 'imported'
    storage = MemoryObjects(); client.execution.storage = storage
    admitted = client.post(f'{BASE}/{identity}/sync', json={'request_key':'sync'})
    assert admitted.status_code == 202
    assert client.execution.run_once()
    result = client.get(admitted.json()['status_url']).json()
    assert result['status'] == 'failed' and result['error'] == {'code':'execution_failed'}
    assert result['result'] == {} and storage.manifests == {}
    reference = client.get(f"{BASE}/datasets/{published['dataset_id']}/revisions/1").json()
    assert reference['status'] == 'pending' and reference['manifest'] is None
    assert all(path.stat().st_size == 0 for path in client.execution.root.glob('*/manifest.json'))


def configure(imports, monkeypatch, *, free=1000, manifest_bytes=128 * 1024**2):
    import builtins
    import io
    import os
    from pathlib import Path
    from app.models.dataset_storage import StoragePool, StorageSchema
    from app.services.dataset_storage import PhysicalStorage
    from scripts.migrate_dataset_storage import migrate_storage

    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=20, expanded_bytes=30, free_bytes=5)
    migrate(sessions)
    migrate_storage(sessions.kw["bind"], writers_stopped=True)
    # Inject a qualified local mount *at the OS observation seam*, not the
    # ledger. The actual host is Btrfs, intentionally unsupported until quota/
    # subvolume qualification exists. Real file I/O remains guard-confined.
    original_open = builtins.open
    def mount_view(path, *args, **kwargs):
        if isinstance(path, str) and path.startswith("/proc/self/fdinfo/"):
            descriptor = int(path.rsplit("/", 1)[1])
            observed = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            if observed.is_relative_to(service.root):
                with original_open(path, *args, **kwargs) as stream:
                    lines = stream.readlines()
                return io.StringIO("".join("mnt_id:\t999999\n" if line.startswith("mnt_id:") else line for line in lines))
        if path == "/proc/self/mountinfo":
            with original_open(path, *args, **kwargs) as stream:
                return io.StringIO(stream.read() + "999999 0 0:999 / /synthetic rw - ext4 synthetic rw\n")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", mount_view)
    roots = {"imports": service.root, "objects": service.root / "objects",
             "attempts": client.execution.root, "manifests": client.execution.root,
             "scratch": client.execution.root, "exports": client.execution.root}
    policy = PhysicalStorage(roots=roots, pools={role: "synthetic" for role in roots},
                             free_floors={"synthetic": 5}, manifest_bytes=manifest_bytes)
    with sessions.begin() as db:
        db.get(StorageSchema, 1).state = "active"  # Trusted isolated cutover fixture only.
        db.add(StoragePool(id="synthetic", configuration_sha256=policy.configuration_sha256,
                           free_floor_bytes=5))
    service.storage_policy = policy
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=free))
    return policy


def test_physical_receipt_exact_fit_replay_and_one_byte_short_are_atomic(imports, monkeypatch):
    configure(imports, monkeypatch, free=74)
    client, service, _, sessions = imports
    identity = create(client)
    before = dump(sessions)
    response = start(client, identity, size=10)
    assert response.status_code == 507, response.text  # Z + 2E + floor = 75.
    assert response.json() == {"detail": "Espacio físico insuficiente para autorizar la escritura."}
    assert dump(sessions) == before
    assert not service.stage(SimpleNamespace(id=identity)).exists()
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=75))
    accepted = start(client, identity, size=10)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"import_id": identity, "name": "birds.zip", "size_bytes": 10,
        "reserved_bytes": 40, "received_bytes": 0, "chunk_bytes": 16 * 1024**2, "status": "receiving"}
    stored = dump(sessions)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=5))
    assert start(client, identity).json() == accepted.json()
    assert dump(sessions) == stored


@pytest.mark.parametrize("phase", ["chunk", "finalize"])
def test_chunk_protocol_requires_durable_compatible_authority_before_mutation(imports, monkeypatch, phase):
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    from tests.test_dataset_import_chunks import put
    configure(imports, monkeypatch, free=75)
    client, service, _, sessions = imports
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", "4")
    migrate_chunks(sessions.kw["bind"], writers_stopped=True)
    identity = create(client)
    assert start(client, identity).status_code == 200
    url = f"{BASE}/{identity}/receipt"
    if phase == "finalize":
        for index, block in enumerate((b"abcd", b"efgh", b"ij")):
            assert put(client, url, index, block).status_code == 200
    service.storage_policy = None
    before = dump(sessions)
    files = {str(p): p.read_bytes() for p in service.root.rglob("*") if p.is_file()}
    response = put(client, url, 0, b"abcd") if phase == "chunk" else client.post(url + "/finalize")
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": "El presupuesto físico requiere un perfil activo y compatible."}
    assert dump(sessions) == before
    assert {str(p): p.read_bytes() for p in service.root.rglob("*") if p.is_file()} == files


def test_active_sync_reserves_full_manifest_ceiling_before_output_and_retries(imports, monkeypatch, tmp_path):
    from tests.test_dataset_import_api import prepare, confirm
    from tests.test_dataset_import_sync import MemoryObjects
    from scripts.migrate_dataset_storage import inspect_storage
    configure(imports, monkeypatch, free=10**9)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    published = confirm(client, prepare(client, tmp_path)).json()
    storage = MemoryObjects()
    client.execution.storage = storage
    endpoint = f"{BASE}/{published['id']}/sync"
    admitted = client.post(endpoint, json={"request_key": "sync"})
    before = set(client.execution.root.iterdir())
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=128 * 1024**2 + 1504))
    assert client.execution.run_once()
    failed = client.get(admitted.json()["status_url"]).json()
    assert failed["status"] == "failed" and failed["error"] == {"code": "staging_failed"}
    assert storage.objects == {} and storage.manifests == {}
    assert set(client.execution.root.iterdir()) == before
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2
    retry = client.post(admitted.json()["status_url"] + "/retry", json={"request_key": "sync-retry"})
    assert retry.status_code == 202
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=128 * 1024**2 + 1505))
    assert client.execution.run_once()
    result = client.get(retry.json()["status_url"]).json()
    assert result["status"] == "succeeded", result
    assert result["result"] == {"dataset_id": published["dataset_id"], "dataset_revision": 1, "synced_count": 1}
    assert len(storage.manifests) == 1 and len(storage.objects) == 1
    reference = client.get(f"{BASE}/datasets/{published['dataset_id']}/revisions/1").json()
    manifest = next(iter(storage.manifests.values()))[0]
    assert reference["status"] == "complete" and reference["manifest"]["size_bytes"] == len(manifest)
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 3
    with sessions() as db:
        assert service.cleanup(db) == {"completed": 1, "failed": 0}
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 0


def test_chunk_use_and_finalize_rename_do_not_reserve_a_second_envelope(imports, monkeypatch):
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    from scripts.migrate_dataset_storage import inspect_storage
    from tests.test_dataset_import_chunks import put
    configure(imports, monkeypatch, free=75)
    client, service, _, sessions = imports
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", "4")
    migrate_chunks(sessions.kw["bind"], writers_stopped=True)
    identity = create(client)
    assert start(client, identity).status_code == 200
    url = f"{BASE}/{identity}/receipt"
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=5))
    for index, block in enumerate((b"abcd", b"efgh", b"ij")):
        assert put(client, url, index, block).status_code == 200
    partial = service.root / "staging" / identity / "receiving.part"
    inode = partial.stat().st_ino
    assert client.post(url + "/finalize").json()["status"] == "sealed"
    archive = partial.with_name("archive.zip")
    assert archive.read_bytes() == b"abcdefghij" and archive.stat().st_ino == inode
    assert not partial.exists()
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2


def test_raw_ingress_reserves_ceiling_and_replay_growth_before_opening_output(imports, monkeypatch):
    from scripts.migrate_dataset_storage import inspect_storage
    configure(imports, monkeypatch, free=84)
    client, service, _, sessions = imports
    identity = create(client)
    endpoint = f"{BASE}/{identity}/archive"
    before = dump(sessions)
    response = client.put(endpoint, content=b"zip", headers={"Content-Type": "application/zip"})
    assert response.status_code == 507, response.text  # No trusted size: 20 + 60 + 5.
    assert response.json() == {"detail": "Espacio físico insuficiente para autorizar la escritura."}
    assert dump(sessions) == before
    assert not (service.root / "staging" / identity).exists()
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=85))
    accepted = client.put(endpoint, content=b"zip", headers={"Content-Type": "application/zip"})
    assert accepted.status_code == 200, accepted.text
    archive = service.root / "staging" / identity / "archive.zip"
    assert archive.read_bytes() == b"zip"
    before = dump(sessions)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=104))
    refused = client.put(endpoint, content=b"zip", headers={"Content-Type": "application/zip"})
    assert refused.status_code == 507, refused.text  # Live 80 + new incoming 20 + floor 5.
    assert dump(sessions) == before
    assert archive.read_bytes() == b"zip" and not archive.with_name("receiving.part").exists()
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=105))
    replay = client.put(endpoint, content=b"zip", headers={"Content-Type": "application/zip"})
    assert replay.json() == accepted.json()
    assert archive.read_bytes() == b"zip"
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2


def test_worker_checks_profile_before_attempt_directory_creation(imports, monkeypatch, tmp_path):
    from tests.test_dataset_import_api import archive, wav_bytes
    configure(imports, monkeypatch, free=10000)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    identity = create(client)
    data = archive(tmp_path / "small.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"{BASE}/{identity}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    admitted = client.post(f"{BASE}/{identity}/preview", json={"root": "", "request_key": "preview"})
    assert admitted.status_code == 202
    before = set(client.execution.root.iterdir())
    service.storage_policy = None
    assert client.execution.run_once()
    result = client.get(admitted.json()["status_url"]).json()
    assert result["status"] == "failed" and result["error"] == {"code": "staging_failed"}
    assert result["result"] == {}
    assert set(client.execution.root.iterdir()) == before
    assert client.get(f"{BASE}/{identity}").json()["status"] == "validating"


def test_initial_preview_transfers_authority_and_retry_is_charged_before_output(imports, monkeypatch, tmp_path):
    from scripts.migrate_dataset_storage import inspect_storage
    from tests.test_dataset_import_api import archive, wav_bytes
    configure(imports, monkeypatch, free=2005)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    identity = create(client)
    data = archive(tmp_path / "small.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"{BASE}/{identity}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    endpoint = f"{BASE}/{identity}/preview"
    first = client.post(endpoint, json={"root": "", "request_key": "first"})
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=5))
    assert client.execution.run_once()  # Existing initial envelope, no second 2E charge.
    assert client.get(first.json()["status_url"]).json()["status"] == "succeeded"
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2
    again = client.post(endpoint, json={"root": "", "request_key": "second"})
    before = {str(p): p.read_bytes() for p in service.root.rglob("*") if p.is_file()}
    directories = set(client.execution.root.iterdir())
    source = client.get(f"{BASE}/{identity}").json()
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=3004))
    assert client.execution.run_once()
    failed = client.get(again.json()["status_url"]).json()
    assert failed["status"] == "failed" and failed["error"] == {"code": "staging_failed"}
    assert failed["result"] == {}
    assert client.get(f"{BASE}/{identity}").json() | {"execution": None} == source | {"execution": None}
    assert set(client.execution.root.iterdir()) == directories
    assert {str(p): p.read_bytes() for p in service.root.rglob("*") if p.is_file()} == before
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2
    retry = client.post(again.json()["status_url"] + "/retry", json={"request_key": "retry"})
    assert retry.status_code == 202, retry.text
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=3005))
    assert client.execution.run_once()
    assert client.get(retry.json()["status_url"]).json()["status"] == "succeeded"
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 3


def test_confirmation_uses_reserved_publication_and_preserves_original_wav(imports, monkeypatch, tmp_path):
    from tests.test_dataset_import_api import prepare, confirm, wav_bytes
    configure(imports, monkeypatch, free=2005)
    client, service, _, _ = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    preview = prepare(client, tmp_path)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=5))
    result = confirm(client, preview)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "imported", result.text
    assert result.json()["added_count"] == 1
    dataset = result.json()["dataset_id"]
    member = client.get(f"{BASE}/datasets/{dataset}/files").json()["files"][0]
    assert client.get(f"{BASE}/datasets/{dataset}/files/{member['sha256']}").content == wav_bytes()
    # Copy publication, never a move out of validated attempt files.
    assert len(list(client.execution.root.glob("*/files/*.wav"))) == 1
    assert (service.root / "objects" / preview["id"] / (member["sha256"] + ".wav")).read_bytes() == wav_bytes()


def test_cleanup_retires_stopped_authority_but_failed_deletion_retains_files(imports, monkeypatch, tmp_path):
    import shutil
    from tests.test_dataset_import_api import prepare, confirm
    from scripts.migrate_dataset_storage import inspect_storage
    configure(imports, monkeypatch, free=10000)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    published = confirm(client, prepare(client, tmp_path)).json()
    assert published["status"] == "imported"
    staging = service.root / "staging" / published["id"]
    archive = (staging / "archive.zip").read_bytes()
    original = shutil.rmtree
    def fail(path, *args, **kwargs):
        if path == staging:
            raise OSError("induced cleanup failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(shutil, "rmtree", fail)
    with sessions() as db:
        assert service.cleanup(db) == {"completed": 0, "failed": 1}
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 0
    assert (staging / "archive.zip").read_bytes() == archive
    assert client.get(f"{BASE}/{published['id']}").json()["status"] == "imported"
    assert client.get(f"{BASE}/{published['id']}").json()["added_count"] == 1
    monkeypatch.setattr(shutil, "rmtree", original)
    with sessions() as db:
        assert service.cleanup(db) == {"completed": 1, "failed": 0}
    assert not staging.exists()
    assert (service.root / "objects" / published["id"]).is_dir()


@pytest.mark.parametrize("failure", ["construction", "first_start", "second_start"])
@pytest.mark.parametrize("active", [False, True])
def test_thread_start_failure_allows_recovery_and_cleanup(imports, monkeypatch, tmp_path, failure, active):
    import threading
    from tests.test_dataset_import_api import archive, wav_bytes

    if active:
        configure(imports, monkeypatch, free=10000)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    identity = create(client)
    data = archive(tmp_path / "thread.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"{BASE}/{identity}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    admitted = client.post(f"{BASE}/{identity}/preview", json={"root": "", "request_key": "thread-start"})
    assert admitted.status_code == 202
    with sessions() as db:
        now = client.execution.queue._now(db)
    original_start = threading.Thread.start
    started = []
    calls = 0

    def construct(thread, *args, **kwargs):
        raise RuntimeError("cannot start new thread")

    def start_thread(thread):
        nonlocal calls
        calls += 1
        if calls == (1 if failure == "first_start" else 2):
            raise RuntimeError("cannot start new thread")
        original_start(thread)
        started.append(thread)

    try:
        with monkeypatch.context() as patch:
            if failure == "construction":
                patch.setattr(threading.Thread, "__init__", construct)
            else:
                patch.setattr(threading.Thread, "start", start_thread)
            with pytest.raises(RuntimeError, match="^cannot start new thread$"):
                client.execution.run_once()
        client.execution.queue.clock = lambda: now + 120
        assert client.execution.run_once()
        response = client.get(admitted.json()["status_url"])
        assert response.status_code == 200
        assert response.json()["status"] == "succeeded", response.text
        assert client.post(f"{BASE}/{identity}/cancel").status_code == 200
        with sessions() as db:
            assert service.cleanup(db) == {"completed": 1, "failed": 0}
        assert not (service.root / "staging" / identity).exists()
    finally:
        for thread in started:
            thread.join(2)
            assert not thread.is_alive(), "heartbeat did not stop after scheduling failure"


def test_timeout_before_callback_entry_keeps_authority_until_thread_stops(imports, monkeypatch, tmp_path):
    import threading
    import shutil
    from app.services.dataset_import_execution import ImportExecution
    from scripts.migrate_dataset_storage import inspect_storage
    from tests.test_dataset_import_api import archive, wav_bytes
    configure(imports, monkeypatch, free=10000)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    entered, release = threading.Event(), threading.Event()
    threads = []
    class DelayedExecution(ImportExecution):
        def execute(self, attempt, staging, report):
            threads.append(threading.current_thread())
            entered.set()
            assert release.wait(5)
            return super().execute(attempt, staging, report)
    client.execution = DelayedExecution(client.execution.queue, service, client.execution.root, execution_seconds=0.05)
    identity = create(client)
    data = archive(tmp_path / "small.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"{BASE}/{identity}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    admitted = client.post(f"{BASE}/{identity}/preview", json={"root": "", "request_key": "slow"})
    original = shutil.rmtree
    deletions = []
    def fail(path, *args, **kwargs):
        deletions.append(str(path))
        raise OSError("must not reach deletion while callback remains capable")
    try:
        assert client.execution.run_once() and entered.is_set()
        assert client.get(admitted.json()["status_url"]).json()["error"] == {"code": "execution_timeout"}
        assert client.post(f"{BASE}/{identity}/cancel").status_code == 200
        monkeypatch.setattr(shutil, "rmtree", fail)
        with sessions() as db:
            outcome = service.cleanup(db)
        assert outcome == {"completed": 0, "failed": 0}
        assert deletions == []
        assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2
    finally:
        monkeypatch.setattr(shutil, "rmtree", original)
        release.set()
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
    with sessions() as db:
        assert service.cleanup(db) == {"completed": 1, "failed": 0}
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 0


def test_unqualified_sync_fails_before_manifest_output_or_remote_call(imports, monkeypatch, tmp_path):
    from tests.test_dataset_import_api import prepare, confirm
    configure(imports, monkeypatch, free=10000)
    client, service, _, _ = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    published = confirm(client, prepare(client, tmp_path)).json()
    assert published["status"] == "imported"
    class ForbiddenRemote:
        def ensure(self, *args):
            raise AssertionError("Unqualified remote writer must not start")
    client.execution.storage = ForbiddenRemote()
    admitted = client.post(f"{BASE}/{published['id']}/sync", json={"request_key": "sync"})
    assert admitted.status_code == 202
    directories = set(client.execution.root.iterdir())
    assert client.execution.run_once()
    result = client.get(admitted.json()["status_url"]).json()
    assert result["status"] == "failed" and result["error"] == {"code": "staging_failed"}
    assert result["result"] == {}
    assert set(client.execution.root.iterdir()) == directories
    assert client.get(f"{BASE}/{published['id']}").json()["sync_status"] == "pending"


def test_prepared_schema_keeps_unconfigured_import_publish_and_cleanup_working(imports, tmp_path):
    from scripts.migrate_dataset_storage import migrate_storage, inspect_storage
    from tests.test_dataset_import_api import prepare, confirm, wav_bytes
    client, service, _, sessions = imports
    migrate_storage(sessions.kw["bind"], writers_stopped=True)
    published = confirm(client, prepare(client, tmp_path)).json()
    assert published["status"] == "imported" and published["added_count"] == 1
    member = client.get(f"{BASE}/datasets/{published['dataset_id']}/files").json()["files"][0]
    assert client.get(f"{BASE}/datasets/{published['dataset_id']}/files/{member['sha256']}").content == wav_bytes()
    with sessions() as db:
        assert service.cleanup(db) == {"completed": 1, "failed": 0}
    assert inspect_storage(sessions.kw["bind"]) == {"version": 1, "state": "prepared",
        "schema_verified": True, "pools": 0, "live_grants": 0, "action": "inspect"}


def test_prepared_schema_preserves_unconfigured_receipt_chunks_and_cancel(imports, monkeypatch):
    from scripts.migrate_dataset_storage import migrate_storage, inspect_storage
    from tests.test_dataset_import_chunks import prepared, put
    client, _, _, sessions = imports
    migrate_storage(sessions.kw["bind"], writers_stopped=True)
    url = prepared(imports, monkeypatch)
    receipt = client.get(url).json()
    for index, block in enumerate((b"abcd", b"efgh", b"ij")):
        assert put(client, url, index, block).status_code == 200
    assert client.post(url + "/finalize").json()["status"] == "sealed"
    assert client.post(url + "/cancel").json() == dict(receipt, received_bytes=10,
                                                       reserved_bytes=0, status="cancelled")
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 0


@pytest.mark.parametrize("enabled", [True, False])
def test_manifest_download_uses_bounded_qualified_scratch_when_enabled(imports, monkeypatch, tmp_path, enabled):
    import hashlib
    from app.models.dataset_import_revision import DatasetRevision
    from app.routes.dataset_imports import get_import_storage
    from tests.test_dataset_import_api import prepare, confirm
    configure(imports, monkeypatch, free=10000)
    client, service, app, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    published = confirm(client, prepare(client, tmp_path)).json()
    payload = b'{"synthetic":true}'
    with sessions.begin() as db:
        db.add(DatasetRevision(id="a" * 32, dataset_id=published["dataset_id"], revision=1,
            owner_id=1, name="Synthetic", description="", file_count=1, total_size_bytes=204,
            status="complete", verified_count=1, verified_bytes=204, manifest_key="synthetic.json",
            manifest_generation="1", manifest_sha256=hashlib.sha256(payload).hexdigest(),
            manifest_size_bytes=len(payload)))
    calls = []
    class Remote:
        def read_verified(self, key, generation, digest, size, destination):
            calls.append(key)
            destination.write(payload)
    app.dependency_overrides[get_import_storage] = Remote
    if not enabled:
        from app.models.dataset_storage import StorageSchema
        with sessions.begin() as db:
            db.get(StorageSchema, 1).state = "prepared"
        service.storage_policy = None
    before = dump(sessions)
    response = client.get(f"{BASE}/datasets/{published['dataset_id']}/revisions/1/manifest")
    assert response.status_code == 200 and response.content == payload, response.text
    assert calls == ["synthetic.json"]
    if not enabled:
        assert dump(sessions) == before
    else:
        from scripts.migrate_dataset_storage import inspect_storage
        assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2


@pytest.mark.parametrize("defect", ["prepared", "missing_pool", "different_profile", "missing_policy"])
def test_unusable_physical_profiles_refuse_receipt_without_implicit_repair(imports, monkeypatch, defect):
    from app.models.dataset_storage import StoragePool, StorageSchema
    configure(imports, monkeypatch)
    client, service, _, sessions = imports
    identity = create(client)
    with sessions.begin() as db:
        if defect == "prepared":
            db.get(StorageSchema, 1).state = "prepared"
        elif defect == "missing_pool":
            db.delete(db.get(StoragePool, "synthetic"))
        elif defect == "different_profile":
            db.get(StoragePool, "synthetic").configuration_sha256 = "f" * 64
        else:
            service.storage_policy = None
    before = dump(sessions)
    refused = start(client, identity)
    assert refused.status_code == 503, refused.text
    assert refused.json() == {"detail": "El presupuesto físico requiere un perfil activo y compatible."}
    assert dump(sessions) == before
    assert not service.stage(SimpleNamespace(id=identity)).exists()


def test_other_writers_live_promises_compete_without_recharging_receipt_v1(imports, monkeypatch):
    from app.models.dataset_storage import StorageGrant
    from app.routes.dataset_imports import get_import_user
    from scripts.migrate_dataset_storage import inspect_storage
    policy = configure(imports, monkeypatch, free=105)
    client, service, app, sessions = imports
    # Trusted retained authority from another writer; not a claim that T3 export
    # construction is integrated. Admission observes it through the real ledger.
    with sessions.begin() as db:
        db.add(StorageGrant(id="e" * 64, pool_id="synthetic", resource_id="other-writer",
            phase="export", attempt=1, token=1, policy_sha256="a" * 64,
            envelope_bytes=30, state="live"))
    first = create(client, "first")
    assert start(client, first).json()["reserved_bytes"] == 40  # 30 + 70 + 5 = 105, not +40 again.
    own_second = create(client, "same-owner")
    before = dump(sessions)
    assert start(client, own_second).status_code == 429
    assert dump(sessions) == before
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    other = create(client, "other-owner")
    before = dump(sessions)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=174))
    refused = start(client, other)
    assert refused.status_code == 507 and refused.json() == {
        "detail": "Espacio físico insuficiente para autorizar la escritura."}
    assert dump(sessions) == before
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 3
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=175))
    assert start(client, other).status_code == 200
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 5


@pytest.mark.parametrize("defect", ["type", "length", "nullable", "primary_key", "foreign_key",
                                    "missing_check", "extra_check", "literal_case", "unique", "default"])
def test_runtime_refuses_incompatible_ledger_ddl_before_receipt_mutation(imports, monkeypatch, defect):
    from sqlalchemy.schema import CreateTable
    from app.models.dataset_storage import StorageGrant
    configure(imports, monkeypatch)
    client, service, _, sessions = imports
    identity = create(client)
    # Establish the existing per-import synchronization file through HTTP before
    # snapshotting. A lock file is not stored payload or new write authority.
    assert start(client, identity, size=21).status_code == 413
    engine = sessions.kw["bind"]
    ddl = str(CreateTable(StorageGrant.__table__).compile(engine))
    changes = {
        "type": ("envelope_bytes BIGINT", "envelope_bytes VARCHAR(64)"),
        "length": ("resource_id VARCHAR(128)", "resource_id VARCHAR(12)"),
        "nullable": ("phase VARCHAR(24) NOT NULL", "phase VARCHAR(24)"),
        "primary_key": ("PRIMARY KEY (id)", "PRIMARY KEY (id, phase)"),
        "foreign_key": ("REFERENCES dataset_storage_pool (id)", "REFERENCES dataset_import (id)"),
        "missing_check": ("CHECK (envelope_bytes > 0)", "CHECK (envelope_bytes >= 0)"),
        "extra_check": ("CHECK (envelope_bytes > 0)", "CHECK (envelope_bytes > 0), CHECK (token = 0)"),
        "literal_case": ("'live', 'retired'", "'LIVE', 'retired'"),
        "unique": ("PRIMARY KEY (id)", "PRIMARY KEY (id), UNIQUE (resource_id)"),
        "default": ("token BIGINT NOT NULL", "token BIGINT DEFAULT 1 NOT NULL"),
    }
    old, new = changes[defect]
    assert old in ddl
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE dataset_storage_grant")
        conn.exec_driver_sql(ddl.replace(old, new))
    before = dump(sessions)
    files = {str(p): p.read_bytes() for p in service.root.rglob("*") if p.is_file()}
    response = start(client, identity)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": "El presupuesto físico requiere un perfil activo y compatible."}
    assert dump(sessions) == before
    assert {str(p): p.read_bytes() for p in service.root.rglob("*") if p.is_file()} == files


@pytest.mark.parametrize("failure", ["total_bytes", "record_bytes", "members", "write_failure"])
def test_sync_auxiliary_failure_never_publishes_partial_manifest_and_retry_is_fresh(
        imports, monkeypatch, tmp_path, failure):
    import io
    from app.models.dataset_import_revision import DatasetRevision
    from tests.test_dataset_import_api import prepare, confirm
    from tests.test_dataset_import_sync import MemoryObjects
    from scripts.migrate_dataset_storage import inspect_storage
    configure(imports, monkeypatch, free=10**9, manifest_bytes=1 if failure == "total_bytes" else 128 * 1024**2)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    published = confirm(client, prepare(client, tmp_path)).json()
    if failure in ("record_bytes", "members"):
        with sessions.begin() as db:
            db.add(DatasetRevision(id="b" * 32, dataset_id=published["dataset_id"], revision=1,
                owner_id=1, name="Synthetic", description="\U0001f426" * 2000 if failure == "record_bytes" else "",
                file_count=50001 if failure == "members" else 0, total_size_bytes=0,
                status="pending", verified_count=0, verified_bytes=0))
    # Actual file-write failure, not a mocked ledger decision.
    original_open = io.open
    def fail_write(path, *args, **kwargs):
        if str(path).endswith("/manifest.json") and args and args[0] == "wb":
            raise OSError("induced manifest open failure")
        return original_open(path, *args, **kwargs)
    if failure == "write_failure":
        monkeypatch.setattr(io, "open", fail_write)
    storage = MemoryObjects()
    client.execution.storage = storage
    admitted = client.post(f"{BASE}/{published['id']}/sync", json={"request_key": "bounded"})
    assert client.execution.run_once()
    result = client.get(admitted.json()["status_url"]).json()
    assert result["status"] == "failed" and result["error"] == {"code": "execution_failed"}
    assert result["result"] == {} and storage.manifests == {}
    assert client.get(f"{BASE}/datasets/{published['dataset_id']}/revisions/1").json()["status"] == "pending"
    paths = list(client.execution.root.glob("*/manifest.json"))
    assert all(path.stat().st_size == 0 for path in paths)  # Rejected before forwarding the header.
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 3
    if failure == "write_failure":
        monkeypatch.setattr(io, "open", original_open)
        retry = client.post(admitted.json()["status_url"] + "/retry", json={"request_key": "fresh"})
        assert client.execution.run_once()
        assert client.get(retry.json()["status_url"]).json()["status"] == "succeeded"
        assert inspect_storage(sessions.kw["bind"])["live_grants"] == 4
    with sessions() as db:
        assert service.cleanup(db) == {"completed": 1, "failed": 0}
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 0
    assert (service.root / "objects" / published["id"]).is_dir()


@pytest.mark.parametrize("mode", ["exact", "free_short", "advertised_oversize", "overrun", "truncated", "digest", "remote_failure"])
def test_manifest_download_bounds_before_write_and_retires_only_stopped_writer(imports, monkeypatch, tmp_path, mode):
    import hashlib
    import tempfile
    from app.models.dataset_import_revision import DatasetRevision
    from app.routes.dataset_imports import get_import_storage
    from tests.test_dataset_import_api import prepare, confirm
    from scripts.migrate_dataset_storage import inspect_storage
    configure(imports, monkeypatch, free=10**9, manifest_bytes=20)
    client, service, app, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    published = confirm(client, prepare(client, tmp_path)).json()
    payload = b"x" * 20
    with sessions.begin() as db:
        db.add(DatasetRevision(id="c" * 32, dataset_id=published["dataset_id"], revision=1,
            owner_id=1, name="Synthetic", description="", file_count=1, total_size_bytes=204,
            status="complete", verified_count=1, verified_bytes=204, manifest_key="synthetic.json",
            manifest_generation="1", manifest_sha256=hashlib.sha256(payload).hexdigest(),
            manifest_size_bytes=21 if mode == "advertised_oversize" else 20))
    # Validate the physical file-creation seam and observe authority DURING the
    # synchronous writer, not by querying private ledger counters.
    files, calls = [], []
    original_temporary = tempfile.TemporaryFile
    def temporary(*args, **kwargs):
        assert kwargs["dir"] == service.storage_policy.roots["scratch"]
        assert inspect_storage(sessions.kw["bind"])["live_grants"] == 3
        result = original_temporary(*args, **kwargs)
        files.append(result)
        return result
    monkeypatch.setattr(tempfile, "TemporaryFile", temporary)
    class Remote:
        def read_verified(self, key, generation, digest, size, destination):
            calls.append(key)
            assert inspect_storage(sessions.kw["bind"])["live_grants"] == 3
            if mode == "remote_failure":
                destination.write(b"x")
                raise OSError("induced remote failure")
            destination.write(payload[:-1] if mode == "truncated" else b"z" * 20 if mode == "digest" else payload)
            if mode == "overrun":
                with pytest.raises(Exception, match="Manifest exceeds byte bound"):
                    destination.write(b"!")
                assert destination.tell() == 20
                raise OSError("overrun rejected before forwarding")
    app.dependency_overrides[get_import_storage] = Remote
    before = dump(sessions)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=1524 if mode == "free_short" else 1525))
    response = client.get(f"{BASE}/datasets/{published['dataset_id']}/revisions/1/manifest")
    if mode == "exact":
        assert response.status_code == 200 and response.content == payload, response.text
        assert response.headers["content-length"] == "20"
    elif mode in ("free_short", "advertised_oversize"):
        assert response.status_code == (507 if mode == "free_short" else 413), response.text
        assert response.json() == {"detail": "Espacio físico insuficiente para autorizar la escritura."
                                  if mode == "free_short" else "El manifiesto supera el límite físico permitido."}
        assert calls == [] and files == [] and dump(sessions) == before
    else:
        assert response.status_code == 409, response.text
        assert response.json() == {"detail": "El manifiesto no está disponible con la integridad y generación autorizadas."}
    assert all(file.closed for file in files)
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2
    assert client.get(f"{BASE}/{published['id']}").json()["status"] == "imported"


def test_receipt_initial_exact_fit_transfers_publication_without_another_envelope(imports, monkeypatch, tmp_path):
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    from scripts.migrate_dataset_storage import inspect_storage
    from tests.test_dataset_import_api import archive, wav_bytes, operation, confirm
    configure(imports, monkeypatch, free=10**9)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    data = archive(tmp_path / "boundary.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    identity = create(client)
    migrate_chunks(sessions.kw["bind"], writers_stopped=True)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=len(data) + 1005))
    assert start(client, identity, size=len(data)).status_code == 200
    import hashlib
    assert client.put(f"{BASE}/{identity}/receipt/chunks/0", content=data, headers={
        "Content-Type": "application/octet-stream", "X-Chunk-Offset": "0",
        "X-Chunk-SHA256": hashlib.sha256(data).hexdigest()}).status_code == 200
    assert client.post(f"{BASE}/{identity}/receipt/finalize").status_code == 200
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda _: SimpleNamespace(free=5))
    preview = operation(client, identity, "preview", {"root": ""}).json()
    assert preview["status"] == "ready"
    result = confirm(client, preview).json()
    assert result["status"] == "imported" and result["added_count"] == 1
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 2
    member = client.get(f"{BASE}/datasets/{result['dataset_id']}/files").json()["files"][0]
    assert client.get(f"{BASE}/datasets/{result['dataset_id']}/files/{member['sha256']}").content == wav_bytes()


def test_active_sync_manifest_covers_full_revision_and_escaped_unicode(imports, monkeypatch, tmp_path):
    import hashlib
    import json
    from tests.test_dataset_import_api import prepare, confirm, wav_bytes
    from tests.test_dataset_import_sync import MemoryObjects
    configure(imports, monkeypatch, free=10**9)
    client, service, _, _ = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    first = confirm(client, prepare(client, tmp_path, key="first", entries=[("bird\U0001f426/a.wav", wav_bytes())])).json()
    second = confirm(client, prepare(client, tmp_path, key="second", target_id=first["dataset_id"],
                                    entries=[("bird\U0001f426/b.wav", wav_bytes(2))])).json()
    storage = MemoryObjects()
    client.execution.storage = storage
    admitted = client.post(f"{BASE}/{second['id']}/sync", json={"request_key": "full"})
    assert client.execution.run_once()
    result = client.get(admitted.json()["status_url"]).json()
    assert result["status"] == "succeeded" and result["result"]["synced_count"] == 2
    manifest = next(iter(storage.manifests.values()))[0]
    parsed = json.loads(manifest)
    assert parsed["file_count"] == 2 and parsed["total_size_bytes"] == 408
    assert {item["source_import_id"] for item in parsed["files"]} == {first["id"], second["id"]}
    assert {item["class_name"] for item in parsed["files"]} == {"bird\U0001f426"}
    assert b"\\ud83d\\udc26" in manifest and all(len(line) <= 16384 for line in manifest.splitlines(keepends=True))
    reference = client.get(f"{BASE}/datasets/{first['dataset_id']}/revisions/2").json()
    assert reference["manifest"]["sha256"] == hashlib.sha256(manifest).hexdigest()


def test_sync_timeout_retains_auxiliary_authority_until_remote_callback_returns(imports, monkeypatch, tmp_path):
    import threading
    from tests.test_dataset_import_api import prepare, confirm
    from tests.test_dataset_import_sync import MemoryObjects
    from app.services.dataset_import_execution import ImportExecution
    from scripts.migrate_dataset_storage import inspect_storage
    configure(imports, monkeypatch, free=10**9)
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=1000, expanded_bytes=500)
    published = confirm(client, prepare(client, tmp_path)).json()
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    threads = []
    class DelayedStorage(MemoryObjects):
        def ensure_manifest(self, *args):
            entered.set()
            assert release.wait(5)
            return super().ensure_manifest(*args)
    class ObservedExecution(ImportExecution):
        def execute(self, *args):
            threads.append(threading.current_thread())
            try:
                return super().execute(*args)
            finally:
                stopped.set()
    storage = DelayedStorage()
    client.execution = ObservedExecution(client.execution.queue, service, client.execution.root,
                                         storage=storage, execution_seconds=0.1)
    admitted = client.post(f"{BASE}/{published['id']}/sync", json={"request_key": "slow-sync"})
    try:
        assert client.execution.run_once() and entered.is_set()
        result = client.get(admitted.json()["status_url"]).json()
        assert result["status"] == "failed" and result["error"] == {"code": "execution_timeout"}
        with sessions() as db:
            assert service.cleanup(db) == {"completed": 0, "failed": 0}
        assert inspect_storage(sessions.kw["bind"])["live_grants"] == 3
        assert list(client.execution.root.glob("*/manifest.json"))
    finally:
        release.set()
        assert stopped.wait(5)
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
    assert client.get(f"{BASE}/datasets/{published['dataset_id']}/revisions/1").json()["status"] == "pending"
    with sessions() as db:
        assert service.cleanup(db) == {"completed": 1, "failed": 0}
    assert inspect_storage(sessions.kw["bind"])["live_grants"] == 0
