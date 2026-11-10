"""Automatic local publication at the public synthetic ASGI/worker seams."""
import asyncio
import hashlib
import os
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_dataset_import_layout import layout_api
from tests.test_dataset_zip_validation import archive, wav_bytes

BASE = "/api/ingestion/imports"


def send_chunk(worker, source, data):
    """Use the real router with chunk headers unsupported by layout_api's transport."""
    from fastapi import FastAPI
    from app.database import get_db
    from app.routes.dataset_imports import router, get_import_service, get_import_user

    app = FastAPI()
    app.include_router(router)

    def database():
        with worker.queue.sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_import_service] = lambda: worker.service
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    messages = []

    async def receive():
        return {"type": "http.request", "body": data, "more_body": False}

    async def send(message):
        messages.append(message)

    path = f"{BASE}/{source}/receipt/chunks/0"
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1", "method": "PUT",
        "path": path, "raw_path": path.encode(), "query_string": b"", "scheme": "http",
        "server": ("synthetic.test", 80), "client": ("127.0.0.1", 1),
        "headers": [(b"content-type", b"application/octet-stream"), (b"x-chunk-offset", b"0"),
                    (b"x-chunk-sha256", hashlib.sha256(data).hexdigest().encode())]}
    asyncio.run(app(scope, receive, send))
    assert messages[0]["status"] == 200, messages


def create(request, tmp_path, entries, *, auto=True, target=None, layout="class_folders", receipt=None):
    body = {"request_key": uuid.uuid4().hex, "name": "Synthetic", "target_id": target,
            "layout": "class_folders", "auto_import": auto}
    if layout is None:
        body.pop("layout")
    response = request("POST", BASE, body=body)
    assert response.status_code == 200, response.content
    source = response.json()["id"]
    original = archive(tmp_path / f"{source}.zip", entries).read_bytes()
    if receipt:
        reserved = request("POST", f"{BASE}/{source}/receipt", body={"name": "synthetic.zip", "size_bytes": len(original)})
        assert reserved.status_code == 200, reserved.content
        assert reserved.json()["reserved_bytes"] > len(original)
        send_chunk(receipt, source, original)
        assert request("POST", f"{BASE}/{source}/receipt/finalize").status_code == 200
    else:
        assert request("PUT", f"{BASE}/{source}/archive", content=original).status_code == 200
    return source, body


def admit(request, source, kind="preview", **parameters):
    body = {"request_key": uuid.uuid4().hex, **({"root": ""} if kind == "preview" else {}), **parameters}
    response = request("POST", f"{BASE}/{source}/{kind}", body=body)
    assert response.status_code == 202, response.content
    return response.json(), body


def state(request, source):
    return request("GET", f"{BASE}/{source}").json()


def run(request, worker, source):
    execution, body = admit(request, source)
    assert worker.run_once()
    result = request("GET", execution["status_url"]).json()
    assert result["status"] == "succeeded", result
    return state(request, source), execution, body


def test_opt_in_is_authoritative_strict_and_legacy_false_replays_absence(layout_api):
    request, worker, _ = layout_api
    legacy = {"request_key": "legacy", "name": "Legacy", "layout": "class_folders"}
    created = request("POST", BASE, body=legacy)
    assert created.status_code == 200
    assert not created.json()["preview"].get("auto_import", False)
    replay = request("POST", BASE, body=dict(legacy, auto_import=False))
    assert replay.status_code == 200 and replay.json() == created.json()
    before = request("GET", BASE).json()
    for invalid in ("true", "false", 1, 0, None, [], {}):
        response = request("POST", BASE, body=dict(legacy, request_key="invalid", auto_import=invalid))
        assert response.status_code == 422
        assert request("GET", BASE).json() == before
        assert not worker.run_once()
    automatic = request("POST", BASE, body=dict(legacy, request_key="automatic", auto_import=True))
    assert automatic.status_code == 200
    assert automatic.json()["preview"]["auto_import"] is True
    conflict = request("POST", BASE, body=dict(legacy, auto_import=True))
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "La solicitud ya existe con otro destino o contenido."}


@pytest.mark.parametrize("auto", [False, True])
def test_valid_archive_publishes_automatically_only_when_authorized(layout_api, tmp_path, auto):
    request, worker, _ = layout_api
    source, creation = create(request, tmp_path, [("bird/a.wav", wav_bytes())], auto=auto)
    result, execution, operation = run(request, worker, source)
    if not auto:
        assert result["status"] == "ready" and result["dataset_id"] is None
        assert request("GET", BASE + "/datasets").json()["datasets"] == []
        confirmation, _ = admit(request, source, "confirm", preview_token=result["preview_token"])
        assert worker.run_once()
        assert request("GET", confirmation["status_url"]).json()["status"] == "succeeded"
        result = state(request, source)
    assert result["status"] == "imported"
    assert result["added_count"] == 1 and result["sync_status"] == "pending"
    assert result["preview"]["warning_count"] > 0  # Small classes are not errors.
    dataset = result["dataset_id"]
    files = request("GET", f"{BASE}/datasets/{dataset}/files").json()["files"]
    assert [(f["class_name"], f["original_path"]) for f in files] == [("bird", "bird/a.wav")]
    downloaded = request("GET", f"{BASE}/datasets/{dataset}/files/{files[0]['sha256']}")
    assert downloaded.status_code == 200 and downloaded.content == wav_bytes()
    catalog = request("GET", BASE + "/datasets").json()
    assert [(d["revision"], d["file_count"]) for d in catalog["datasets"]] == [(1, 1)]
    assert request("POST", BASE, body=creation).json() == result
    replay = request("POST", f"{BASE}/{source}/preview", body=operation)
    assert replay.status_code == 202 and replay.json()["id"] == execution["id"]
    assert not worker.run_once()
    assert request("GET", BASE + "/datasets").json() == catalog


@pytest.mark.parametrize("auto", [True, False])
def test_publication_retries_after_rename_preserving_automatic_and_manual_authority(
        layout_api, tmp_path, monkeypatch, auto):
    from app.services import dataset_import_execution

    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_import_chunks import migrate_chunks

    request, worker, engine = layout_api
    migrate_receipts(engine, writers_stopped=True)
    migrate_chunks(engine, writers_stopped=True)
    source, _ = create(request, tmp_path, [("bird/a.wav", wav_bytes())], auto=auto, receipt=worker)
    if auto:
        execution, _ = admit(request, source)
    else:
        ready, _, _ = run(request, worker, source)
        execution, _ = admit(request, source, "confirm", preview_token=ready["preview_token"])
    rename = dataset_import_execution.os.rename
    published = []

    def fail_after_rename(prepared, destination):
        assert prepared.parent.parent == tmp_path / "attempts"
        assert destination == tmp_path / "managed" / "objects" / source
        rename(prepared, destination)
        published.append(destination)
        raise OSError("Synthetic interruption after rename, before database commit")

    with monkeypatch.context() as fault:
        fault.setattr(dataset_import_execution.os, "rename", fail_after_rename)
        assert worker.run_once()
    assert published == [tmp_path / "managed" / "objects" / source]
    failed = request("GET", execution["status_url"]).json()
    assert failed["status"] == "failed" and failed["error"] == {"code": "execution_failed"}
    journal = state(request, source)
    assert journal["status"] == "committing" and journal["added_count"] == 0
    reserved = request("GET", f"{BASE}/{source}/receipt").json()
    assert reserved["reserved_bytes"] > 0
    assert request("GET", BASE + "/datasets").json()["datasets"] == []
    rejected = request("POST", f"{BASE}/{source}/preview", body={"request_key": "root-override", "root": "wrapper"})
    assert (rejected.status_code, rejected.json()) == (422, {
        "detail": "El formato clase/audio.wav no admite seleccionar una raíz."})
    if not auto:
        rejected = request("POST", f"{BASE}/{source}/preview", body={"request_key": "no-auto", "root": ""})
        assert (rejected.status_code, rejected.json()) == (409, {
            "detail": "La importación no admite una nueva vista previa."})
        assert state(request, source) == journal
    retry = request("POST", execution["status_url"] + "/retry", body={"request_key": "retry"})
    assert retry.status_code == 202, retry.content
    assert retry.json()["kind"] == execution["kind"]
    assert worker.queue.get(1, retry.json()["id"])["parameters"] == (
        {"root": ""} if auto else {"preview_token": journal["preview_token"]})
    assert worker.run_once()
    recovered = state(request, source)
    assert recovered["status"] == "imported" and recovered["added_count"] == 1
    finished = request("GET", retry.json()["status_url"]).json()
    assert finished["status"] == "succeeded" and finished["progress"] == 100
    assert finished["result"] == {"dataset_id": recovered["dataset_id"], "added_count": 1}
    assert recovered["dataset_id"] == journal["dataset_id"]
    assert recovered["preview_token"] == journal["preview_token"]
    assert recovered["sync_status"] == "pending"
    assert request("GET", f"{BASE}/{source}/receipt").json()["reserved_bytes"] == 0
    catalog = request("GET", BASE + "/datasets").json()["datasets"]
    assert [(d["revision"], d["file_count"]) for d in catalog] == [(1, 1)]
    files = request("GET", f"{BASE}/datasets/{recovered['dataset_id']}/files").json()["files"]
    downloaded = request("GET", f"{BASE}/datasets/{recovered['dataset_id']}/files/{files[0]['sha256']}")
    assert downloaded.status_code == 200 and downloaded.content == wav_bytes()
    assert not worker.run_once()


@pytest.mark.parametrize("entries,code", [
    ([("bird/ok.wav", wav_bytes()), ("bird/session/a.wav", wav_bytes(2))], "class_folders_required"),
    ([("bird/ok.wav", wav_bytes()), ("bird/empty/", b"")], "class_folders_required"),
    ([("bird/ok.wav", wav_bytes()), ("bird/bad.wav", b"broken")], "invalid_wav"),
    ([("bird/a.wav", wav_bytes()), ("other/b.wav", wav_bytes())], "label_conflict"),
])
def test_invalid_automatic_archive_shows_diagnostics_without_partial_dataset(layout_api, tmp_path, entries, code):
    request, worker, _ = layout_api
    source, _ = create(request, tmp_path, entries)
    result, _, _ = run(request, worker, source)
    assert result["status"] == "needs_correction"
    assert result["dataset_id"] is None and result["added_count"] == 0
    assert result["preview"]["auto_import"] is True and result["preview"]["error_count"] > 0
    issues = request("GET", f"{BASE}/{source}/issues").json()["issues"]
    errors = [issue for issue in issues if issue["severity"] == "error"]
    assert code in [issue["code"] for issue in errors]
    assert all(issue["action"] for issue in errors)
    if code == "class_folders_required":
        assert errors[0]["action"] == "Organiza el ZIP como clase/audio.wav, sin carpeta contenedora ni subcarpetas."
    catalog = request("GET", BASE + "/datasets").json()
    assert catalog["datasets"] == []
    rejected = request("POST", f"{BASE}/{source}/confirm", body={"request_key": "no-partial",
        "preview_token": result["preview_token"]})
    assert rejected.status_code == 409
    assert state(request, source) == result
    assert request("GET", BASE + "/datasets").json() == catalog


def test_automatic_quota_and_existing_label_conflict_leave_target_unchanged(layout_api, tmp_path):
    request, worker, _ = layout_api
    source, _ = create(request, tmp_path, [("bird/a.wav", wav_bytes())])
    imported, _, _ = run(request, worker, source)
    target = imported["dataset_id"]
    catalog = request("GET", BASE + "/datasets").json()
    files = request("GET", f"{BASE}/datasets/{target}/files").json()
    limits = worker.service.limits
    for entries, code, quota in [
        ([("other/a.wav", wav_bytes()), ("bird/new.wav", wav_bytes(2))], "label_conflict", {}),
        ([("bird/new.wav", wav_bytes(2))], "dataset_size_limit", {"dataset_bytes": len(wav_bytes())}),
        ([("bird/new.wav", wav_bytes(2))], "dataset_entry_limit", {"dataset_entries": 1}),
    ]:
        worker.service.limits = replace(limits, **quota)
        source, _ = create(request, tmp_path, entries, target=target)
        rejected, _, _ = run(request, worker, source)
        assert rejected["status"] == "needs_correction" and rejected["added_count"] == 0
        issues = request("GET", f"{BASE}/{source}/issues").json()["issues"]
        assert code in [issue["code"] for issue in issues]
        assert all(issue["action"] for issue in issues if issue["severity"] == "error")
        assert request("GET", BASE + "/datasets").json() == catalog
        assert request("GET", f"{BASE}/datasets/{target}/files").json() == files


def test_interruption_before_journal_can_retry_validation(layout_api, tmp_path, monkeypatch):
    request, worker, _ = layout_api
    source, _ = create(request, tmp_path, [("bird/a.wav", wav_bytes())])
    execution, _ = admit(request, source)
    fsync = os.fsync
    interrupted = []

    def fail_validated_audio(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if path.is_relative_to(tmp_path / "attempts") and path.suffix == ".wav":
            interrupted.append(path)
            raise OSError("Synthetic interruption before preview/journal publication")
        return fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", fail_validated_audio)
        assert worker.run_once()
    assert interrupted
    assert request("GET", execution["status_url"]).json()["status"] == "failed"
    before = state(request, source)
    assert before["status"] == "validating" and before["preview_token"] is None
    assert request("GET", BASE + "/datasets").json()["datasets"] == []
    retry = request("POST", execution["status_url"] + "/retry", body={"request_key": "retry"})
    assert retry.status_code == 202
    assert worker.run_once()
    assert state(request, source)["status"] == "imported"
    assert state(request, source)["added_count"] == 1


@pytest.mark.parametrize("point", ["before_journal", "after_rename"])
def test_expired_attempt_cannot_commit_and_reclaimed_preview_recovers(layout_api, tmp_path, monkeypatch, point):
    from app.services.dataset_import_jobs import LeaseLost
    from app.services.dataset_import_execution import ImportExecution

    request, worker, _ = layout_api
    source, _ = create(request, tmp_path, [("bird/a.wav", wav_bytes())])
    execution, operation = admit(request, source)
    now = [100.0]
    worker.queue.clock = lambda: now[0]
    fsync, rename = os.fsync, os.rename
    stale = []

    def expire():
        stale.append(worker.queue.get(1, execution["id"]))
        now[0] = 161.0

    def expire_after_audio(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if not stale and path.is_relative_to(tmp_path / "attempts") and path.suffix == ".wav":
            expire()
        return fsync(fd)

    def expire_after_rename(prepared, destination):
        assert destination == tmp_path / "managed" / "objects" / source
        rename(prepared, destination)
        expire()

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync" if point == "before_journal" else "rename",
                      expire_after_audio if point == "before_journal" else expire_after_rename)
        assert worker.run_once()
    assert len(stale) == 1
    pending = worker.queue.get(1, execution["id"])
    assert pending["status"] == "running" and pending["parameters"] == {"root": ""}
    journal = state(request, source)
    assert journal["status"] == ("validating" if point == "before_journal" else "committing")
    assert request("GET", BASE + "/datasets").json()["datasets"] == []
    replacement = ImportExecution(worker.queue, worker.service, tmp_path / "attempts")
    assert replacement.run_once()
    recovered = state(request, source)
    assert recovered["status"] == "imported" and recovered["added_count"] == 1
    current = worker.queue.get(1, execution["id"])
    assert current["attempt"] == 2 and current["status"] == "succeeded"
    for callback in (lambda: worker.queue.heartbeat(stale[0], lease_seconds=60),
                     lambda: worker.queue.progress(stale[0], stage="prepared", progress=99)):
        with pytest.raises(LeaseLost):
            callback()
    assert state(request, source) == recovered
    assert request("POST", f"{BASE}/{source}/preview", body=operation).json()["id"] == execution["id"]
    assert not replacement.run_once()
    dataset = recovered["dataset_id"]
    files = request("GET", f"{BASE}/datasets/{dataset}/files").json()["files"]
    assert len(files) == 1
    assert request("GET", f"{BASE}/datasets/{dataset}/files/{files[0]['sha256']}").content == wav_bytes()


def test_recovery_admission_keeps_ownership_capacity_exclusion_and_reviewed_root(layout_api, tmp_path, monkeypatch):
    from fastapi import HTTPException

    request, worker, _ = layout_api
    source, _ = create(request, tmp_path, [("wrap/bird/session/a.wav", wav_bytes())], layout=None)
    execution, _ = admit(request, source, root="wrap")
    rename = os.rename

    def fail_after_rename(prepared, destination):
        assert destination == tmp_path / "managed" / "objects" / source
        rename(prepared, destination)
        raise OSError("Synthetic interruption with a reviewed legacy root")

    with monkeypatch.context() as fault:
        fault.setattr(os, "rename", fail_after_rename)
        assert worker.run_once()
    journal = state(request, source)
    assert journal["status"] == "committing" and journal["preview"]["root"] == "wrap"
    rejected = request("POST", f"{BASE}/{source}/preview", body={"request_key": "root-drift", "root": ""})
    assert (rejected.status_code, rejected.json()) == (422, {
        "detail": "La recuperación debe conservar la raíz de la vista previa."})
    with pytest.raises(HTTPException) as foreign:
        worker.queue.admit(2, source, "preview", "foreign", {"root": "wrap"})
    assert foreign.value.status_code == 404
    assert worker.queue.active_counts(1) == {"global": 0, "owner": 0}
    other, _ = create(request, tmp_path, [("bird/other.wav", wav_bytes(2))])
    occupying, _ = admit(request, other)
    for total, owner in [(1, 2), (4, 1)]:
        monkeypatch.setenv("FAMA_IMPORT_CONCURRENT_IMPORTS", str(total))
        monkeypatch.setenv("FAMA_IMPORT_JOBS_PER_OWNER", str(owner))
        rejected = request("POST", execution["status_url"] + "/retry", body={"request_key": "capacity"})
        assert (rejected.status_code, rejected.json()) == (429, {"detail": "Se alcanzó el límite de trabajos activos."})
        assert worker.queue.active_counts(1) == {"global": 1, "owner": 1}
        assert state(request, source) == journal
    assert request("POST", occupying["status_url"] + "/cancel").status_code == 200
    monkeypatch.setenv("FAMA_IMPORT_CONCURRENT_IMPORTS", "4")
    monkeypatch.setenv("FAMA_IMPORT_JOBS_PER_OWNER", "2")
    retry = request("POST", execution["status_url"] + "/retry", body={"request_key": "recover"})
    assert retry.status_code == 202
    rejected = request("POST", f"{BASE}/{source}/preview", body={"request_key": "competing", "root": "wrap"})
    assert (rejected.status_code, rejected.json()) == (409, {"detail": "La importación ya tiene un trabajo activo."})
    assert worker.queue.active_counts(1) == {"global": 1, "owner": 1}
    assert worker.run_once()
    recovered = state(request, source)
    assert recovered["status"] == "imported" and recovered["preview_token"] == journal["preview_token"]
    assert recovered["preview"]["root"] == "wrap" and recovered["added_count"] == 1
    assert worker.queue.active_counts(1) == {"global": 0, "owner": 0}
