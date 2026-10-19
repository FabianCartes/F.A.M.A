import os
from dataclasses import replace
from sqlalchemy import event
from tests.test_dataset_import_layout import layout_api
from tests.s12_probe_support import *
import pytest

@pytest.mark.parametrize("auto,root", [(True, ""), (True, "wrap"), (False, "")])
def test_journal_retry_without_validator_or_source_zip(layout_api, tmp_path, monkeypatch, auto, root):
    from app.services import dataset_import_execution as execution
    from app.services.dataset_import_execution import ImportExecution
    from app.models.dataset_import_metadata import ImportSummary
    request, worker, engine = layout_api
    entries = [(f"{root}/bird/a.wav" if root else "bird/a.wav", wav_bytes())]
    source, _ = new(request, tmp_path, auto=auto, layout=None if root else "class_folders", entries=entries)
    job, _ = admit(request, source, root=root)
    if not auto:
        assert worker.run_once()
        job, _ = admit(request, source, "confirm", preview_token=state(request, source)["preview_token"])
    original = os.rename
    def interrupted(a, b):
        original(a, b)
        raise OSError("Independent post-rename interruption")
    with monkeypatch.context() as fault:
        fault.setattr(os, "rename", interrupted)
        assert worker.run_once()
    journal = state(request, source)
    assert journal["status"] == "committing" and journal["added_count"] == 0
    assert request("GET", B + "/datasets").json()["datasets"] == []
    with worker.queue.sessions() as db:
        identity = dict(db.get(ImportSummary, source).preview)
    # Intentionally remove only this synthetic ZIP: the durable journal must suffice.
    (tmp_path / "managed" / "staging" / source / "archive.zip").unlink()
    def forbidden(*args, **kwargs): pytest.fail("Recovery revalidated instead of resuming the journal")
    monkeypatch.setattr(execution, "validate_zip", forbidden)
    if root:
        reject_unchanged(engine, lambda: request("POST", f"{B}/{source}/preview", body={"request_key": "drift", "root": ""}), 422, "La recuperación debe conservar la raíz de la vista previa.")
    else:
        reject_unchanged(engine, lambda: request("POST", f"{B}/{source}/preview", body={"request_key": "drift", "root": "wrap"}), 422, "El formato clase/audio.wav no admite seleccionar una raíz.")
    if not auto:
        reject_unchanged(engine, lambda: request("POST", f"{B}/{source}/preview", body={"request_key": "legacy-preview", "root": ""}), 409, "La importación no admite una nueva vista previa.")
    retry = request("POST", job["status_url"] + "/retry", body={"request_key": "recover"})
    assert retry.status_code == 202, retry.content
    replacement = ImportExecution(worker.queue, worker.service, tmp_path / "attempts")
    assert replacement.run_once()
    final = state(request, source)
    assert final["status"] == "imported" and final["preview_token"] == journal["preview_token"]
    assert final["dataset_id"] == journal["dataset_id"] and final["added_count"] == 1
    assert final["sync_status"] == "pending" and replacement.storage is None
    with worker.queue.sessions() as db:
        after = db.get(ImportSummary, source).preview
        assert (after["staging_attempt"], after["root"]) == (identity["staging_attempt"], identity["root"])
    files = request("GET", f"{B}/datasets/{final["dataset_id"]}/files").json()["files"]
    assert len(files) == 1
    assert request("GET", f"{B}/datasets/{final["dataset_id"]}/files/{files[0]["sha256"]}").content == wav_bytes()
    assert not replacement.run_once()
    assert worker.queue.active_counts(1) == {"global": 0, "owner": 0}

@pytest.mark.parametrize("case", ["nested-empty", "wav", "label", "quota", "empty"])
def test_rejected_archives_and_commands_keep_complete_state(layout_api, tmp_path, case):
    request, worker, engine = layout_api
    entries = {"nested-empty": [("bird/ok.wav", wav_bytes()), ("bird/empty/", b"")],
        "wav": [("bird/ok.wav", wav_bytes()), ("bird/bad.wav", b"bad")],
        "label": [("bird/ok.wav", wav_bytes()), ("other/duplicate.wav", wav_bytes())],
        "quota": [("bird/ok.wav", wav_bytes())], "empty": []}[case]
    if case == "quota": worker.service.limits = replace(worker.service.limits, dataset_entries=0)
    source, _ = new(request, tmp_path, auto=True, entries=entries)
    job, _ = admit(request, source)
    assert worker.run_once()
    invalid = state(request, source)
    assert invalid["status"] == "needs_correction" and invalid["dataset_id"] is None and invalid["added_count"] == 0
    issues = request("GET", f"{B}/{source}/issues").json()["issues"]
    assert any(i["severity"] == "error" and i["action"] for i in issues)
    assert request("GET", B + "/datasets").json()["datasets"] == []
    assert list((tmp_path / "managed" / "objects").iterdir()) == []
    reject_unchanged(engine, lambda: request("POST", f"{B}/{source}/confirm", body={"request_key": "rejected", "preview_token": invalid["preview_token"]}), 409, "La vista previa cambió o no está lista para confirmar.")
    before = digest(engine)
    assert state(request, source) == invalid
    request("GET", B)
    request("GET", job["status_url"])
    assert digest(engine) == before


def test_lease_expiry_during_membership_insert_rolls_back_then_recovers(layout_api, tmp_path, monkeypatch):
    from app.models.dataset_import_metadata import DatasetMember
    from app.services.dataset_import_execution import ImportExecution
    from app.services.dataset_import_jobs import LeaseLost
    from app.services import dataset_import_execution as execution
    request, worker, engine = layout_api
    now = [100.0]
    worker.queue.clock = lambda: now[0]
    source, _ = new(request, tmp_path, auto=True)
    job, operation = admit(request, source)
    stale = []
    def expire(mapper, connection, target):
        # SQL event is a deterministic barrier inside the real final transaction.
        assert worker.queue.get(1, job["id"])["status"] == "running"
        stale.append(worker.queue.get(1, job["id"]))
        now[0] = 161.0
    event.listen(DatasetMember, "before_insert", expire)
    try: assert worker.run_once()
    finally: event.remove(DatasetMember, "before_insert", expire)
    assert len(stale) == 1
    pending = state(request, source)
    assert pending["status"] == "committing" and pending["added_count"] == 0
    assert request("GET", B + "/datasets").json()["datasets"] == []
    assert request("GET", job["status_url"]).json()["status"] == "running"
    monkeypatch.setattr(execution, "validate_zip", lambda *a, **kw: pytest.fail("Reclaimed journal was revalidated"))
    assert ImportExecution(worker.queue, worker.service, tmp_path / "attempts").run_once()
    final = state(request, source)
    assert final["status"] == "imported" and final["preview_token"] == pending["preview_token"]
    assert final["added_count"] == 1
    for callback in [lambda: worker.queue.progress(stale[0], stage="prepared", progress=99), lambda: worker.queue.heartbeat(stale[0], lease_seconds=60)]:
        before = digest(engine)
        with pytest.raises(LeaseLost): callback()
        assert digest(engine) == before
    assert request("POST", f"{B}/{source}/preview", body=operation).json()["id"] == job["id"]
    files = request("GET", f"{B}/datasets/{final["dataset_id"]}/files").json()["files"]
    assert len(files) == 1
