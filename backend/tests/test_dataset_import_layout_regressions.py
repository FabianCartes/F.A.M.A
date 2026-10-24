"""Independent layout probes promoted after isolated verification.

Only the public ASGI transport fixture is shared with the initial tests.
"""
import hashlib
import io
import uuid
import wave
import zipfile

import pytest

from tests.test_dataset_import_layout import layout_api

BASE = "/api/ingestion/imports"
ACTION = "Organiza el ZIP como clase/audio.wav, sin carpeta contenedora ni subcarpetas."


def audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x01\x00" * 80)
    return output.getvalue()


def create(request, entries, layout=None, target=None):
    body = {"request_key": uuid.uuid4().hex, "name": "Probe", "target_id": target}
    if layout is not None:
        body["layout"] = layout
    response = request("POST", BASE, body=body)
    assert response.status_code == 200, response.content
    source = response.json()["id"]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    assert request("PUT", f"{BASE}/{source}/archive", content=output.getvalue()).status_code == 200
    return source, body


def dump(engine):
    with engine.connect() as db:
        data = "\n".join(db.connection.driver_connection.iterdump()).encode()
        return hashlib.sha256(data).hexdigest()


def run(request, worker, source, kind, **parameters):
    body = {"request_key": uuid.uuid4().hex, **parameters}
    response = request("POST", f"{BASE}/{source}/{kind}", body=body)
    assert response.status_code == 202, response.content
    assert worker.run_once()
    state = request("GET", response.json()["status_url"]).json()
    assert state["status"] == "succeeded", state
    return request("GET", f"{BASE}/{source}").json(), body


@pytest.mark.parametrize("path", [
    "wrapper/bird/a.wav", "bird/session/a.wav", "bird/empty/", "wrapper/bird/", "a.wav",
])
def test_bad_structure_and_root_override_never_publish_partial_content(layout_api, path):
    request, worker, engine = layout_api
    source, _ = create(request, [("bird/ok.wav", audio()),
        (path, b"" if path.endswith("/") else audio())], "class_folders")
    before = dump(engine)
    rejected = request("POST", f"{BASE}/{source}/preview", body={"request_key": "override", "root": "wrapper"})
    assert (rejected.status_code, rejected.json()) == (422, {
        "detail": "El formato clase/audio.wav no admite seleccionar una raíz."})
    assert dump(engine) == before
    result, _ = run(request, worker, source, "preview", root="")
    assert result["status"] == "needs_correction"
    assert result["issue_sample"] == [{"path": path, "code": "class_folders_required",
        "severity": "error", "action": ACTION}]
    before = dump(engine)
    rejected = request("POST", f"{BASE}/{source}/confirm", body={"request_key": "no",
        "preview_token": result["preview_token"]})
    assert rejected.status_code == 409
    assert dump(engine) == before
    assert request("GET", BASE + "/datasets").json()["datasets"] == []


@pytest.mark.parametrize("layout,root,path", [
    ("class_folders", "", "bird/a.wav"), (None, "wrapper", "wrapper/bird/session/a.wav"),
])
def test_recovery_replay_and_legacy_augmentation_preserve_audio(layout_api, layout, root, path):
    request, worker, engine = layout_api
    source, body = create(request, [(path, audio())], layout)
    before = dump(engine)
    replay = request("POST", BASE, body=body)
    assert replay.status_code == 200 and replay.json()["id"] == source
    assert dump(engine) == before
    preview, _ = run(request, worker, source, "preview", root=root)
    assert preview["status"] == "ready" and preview["preview"]["root"] == root
    recovered = request("GET", f"{BASE}/{source}").json()
    assert recovered["preview_token"] == preview["preview_token"]
    result, confirmation = run(request, worker, source, "confirm", preview_token=recovered["preview_token"])
    assert result["status"] == "imported" and result["added_count"] == 1
    files = request("GET", f"{BASE}/datasets/{result['dataset_id']}/files").json()["files"]
    assert [(file["original_path"], file["class_name"]) for file in files] == [(path, "bird")]
    downloaded = request("GET", f"{BASE}/datasets/{result['dataset_id']}/files/{files[0]['sha256']}")
    assert downloaded.status_code == 200 and downloaded.content == audio()
    replay = request("POST", f"{BASE}/{source}/confirm", body=confirmation)
    assert replay.status_code == 202
    assert not worker.run_once()
    augmentation, _ = create(request, [("old/bird/session/a.wav", audio())], target=result["dataset_id"])
    preview, _ = run(request, worker, augmentation, "preview", root="old")
    assert preview["status"] == "ready"
    merged, _ = run(request, worker, augmentation, "confirm", preview_token=preview["preview_token"])
    assert merged["status"] == "imported" and merged["added_count"] == 0


def test_downloadable_example_is_accepted_by_fixed_layout(layout_api):
    request, worker, _ = layout_api
    response = request("GET", BASE + "/example.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["chucao/audio_01.wav", "colilarga/audio_01.wav"]
        entries = [(name, archive.read(name)) for name in archive.namelist()]
    source, _ = create(request, entries, "class_folders")
    state, _ = run(request, worker, source, "preview", root="")
    assert state["status"] == "ready" and state["preview"]["file_count"] == 2


@pytest.mark.parametrize("entries,code", [
    ([], "no_valid_wav"), ([("bird/a.txt", b"not audio")], "wav_only"),
    ([("bird/a.wav", b"not audio")], "invalid_wav"),
    ([("bird/a.wav", audio()), ("bird/a.wav", audio())], "duplicate_path"),
])
def test_content_checks_still_block_confirmation_without_database_changes(layout_api, entries, code):
    request, worker, engine = layout_api
    source, _ = create(request, entries, "class_folders")
    state, _ = run(request, worker, source, "preview", root="")
    assert state["status"] == "needs_correction"
    assert state["issue_sample"][0]["code"] == code
    before = dump(engine)
    rejected = request("POST", f"{BASE}/{source}/confirm", body={"request_key": "no",
        "preview_token": state["preview_token"]})
    assert rejected.status_code == 409 and dump(engine) == before
    assert request("GET", BASE + "/datasets").json()["datasets"] == []


def test_unknown_policy_is_rejected_without_writes(layout_api):
    request, _, engine = layout_api
    before = dump(engine)
    response = request("POST", BASE, body={"request_key": "invalid", "name": "Probe", "layout": "sessions"})
    assert response.status_code == 422 and dump(engine) == before
