"""Definitive local failures close an attempt, not its diagnostics or disk charge."""
import hashlib

import pytest

from tests.test_dataset_import_api import imports
from tests.test_dataset_import_receipts import migrate, start
from tests.test_dataset_zip_validation import archive, wav_bytes

BASE = "/api/ingestion/imports"


def receive(imports, tmp_path, *, key="failed", entries=None):
    client, _, _, sessions = imports
    migrate(sessions)
    created = client.post(BASE, json={"request_key": key, "name": key,
                                    "layout": "class_folders", "auto_import": True})
    assert created.status_code == 200, created.text
    identity = created.json()["id"]
    data = archive(tmp_path / f"{key}.zip", entries or [("birds/a.wav", wav_bytes())]).read_bytes()
    assert start(client, identity, len(data)).status_code == 200
    receipt = f"{BASE}/{identity}/receipt"
    uploaded = client.put(receipt + "/chunks/0", content=data, headers={
        "Content-Type": "application/octet-stream", "X-Chunk-Offset": "0",
        "X-Chunk-SHA256": hashlib.sha256(data).hexdigest()})
    assert uploaded.status_code == 200, uploaded.text
    assert client.post(receipt + "/finalize").status_code == 200
    return identity


def test_definitive_preview_failure_cancels_and_releases_only_logical_promise(imports, tmp_path):
    client, service, _, _ = imports
    identity = receive(imports, tmp_path)
    admitted = client.post(f"{BASE}/{identity}/preview", json={"request_key": "preview", "root": ""})
    assert admitted.status_code == 202
    staging = service.root / "staging" / identity / "archive.zip"
    staging.write_bytes(b"synthetic damaged archive")
    assert client.execution.run_once()
    assert client.get(admitted.json()["status_url"]).json()["status"] == "failed"
    source = client.get(f"{BASE}/{identity}").json()
    assert source["status"] == "cancelled"
    assert source["error"] == "execution_failed"
    assert client.get(f"{BASE}/{identity}/receipt").json()["reserved_bytes"] == 0
    assert staging.read_bytes() == b"synthetic damaged archive"
    fresh = receive(imports, tmp_path, key="corrected")
    assert fresh != identity
    assert client.get(BASE + "/datasets").json()["datasets"] == []


def test_validation_errors_cancel_but_keep_issue_diagnostics(imports, tmp_path):
    client, _, _, _ = imports
    identity = receive(imports, tmp_path, entries=[("birds/not-audio.wav", b"not a WAV")])
    admitted = client.post(f"{BASE}/{identity}/preview", json={"request_key": "invalid", "root": ""})
    assert admitted.status_code == 202
    assert client.execution.run_once()
    assert client.get(admitted.json()["status_url"]).json()["status"] == "succeeded"
    source = client.get(f"{BASE}/{identity}").json()
    assert source["status"] == "cancelled"
    assert source["preview"]["error_count"] > 0
    assert any(issue["severity"] == "error" for issue in client.get(f"{BASE}/{identity}/issues").json()["issues"])
    assert client.get(f"{BASE}/{identity}/receipt").json()["reserved_bytes"] == 0


def test_warnings_alone_still_publish_automatic_import(imports, tmp_path):
    client, _, _, _ = imports
    identity = receive(imports, tmp_path)
    admitted = client.post(f"{BASE}/{identity}/preview", json={"request_key": "warnings", "root": ""})
    assert admitted.status_code == 202
    assert client.execution.run_once()
    source = client.get(f"{BASE}/{identity}").json()
    assert source["preview"]["warning_count"] > 0
    assert source["status"] == "imported"
