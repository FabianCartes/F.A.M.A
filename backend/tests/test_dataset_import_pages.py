"""Bounded authenticated review and catalog through the public HTTP interface."""
from types import SimpleNamespace
import re
import hashlib
import pytest

from tests.test_dataset_import_api import imports, prepare, confirm, operation
from tests.test_dataset_zip_validation import wav_bytes


def test_review_pages_are_bounded_stable_owner_scoped_and_token_bound(imports, tmp_path):
    from app.routes.dataset_imports import get_import_user

    client, _, app, _ = imports
    job = prepare(client, tmp_path, entries=[
        (f"class{i}/audio.wav", wav_bytes(i + 1)) for i in range(3)])
    assert not {"files", "classes", "errors", "warnings", "sync_files"} & job["preview"].keys()
    assert job["preview"]["file_count"] == 3
    assert job["preview"]["class_count"] == 3
    assert job["preview"]["warning_count"] == 3
    base = f"/api/ingestion/imports/{job['id']}"
    for collection in ("files", "classes", "issues"):
        first = client.get(f"{base}/{collection}?limit=2")
        assert first.status_code == 200, first.text
        page = first.json()
        assert len(page[collection]) == 2 and page["total"] == 3
        assert page["snapshot"] == job["preview_token"]
        assert page["next_cursor"]
        second = client.get(f"{base}/{collection}", params={"limit": 2, "cursor": page["next_cursor"]}).json()
        assert len(second[collection]) == 1 and second["next_cursor"] is None
        assert client.get(f"{base}/{collection}?limit=201").status_code == 422
        app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
        assert client.get(f"{base}/{collection}", params={"cursor": page["next_cursor"]}).status_code == 404
        app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    old = client.get(f"{base}/files?limit=1").json()["next_cursor"]
    assert operation(client, job["id"], "preview", {"root": ""}).status_code == 200
    assert client.get(f"{base}/files", params={"cursor": old}).status_code == 409


def test_published_pages_and_summaries_do_not_select_legacy_collections(imports, tmp_path):
    from sqlalchemy import event

    client, _, _, sessions = imports
    job = prepare(client, tmp_path, entries=[
        (f"birds/{i}.wav", wav_bytes(i + 1)) for i in range(3)])
    result = confirm(client, job).json()
    base = "/api/ingestion/imports"
    statements = []
    engine = sessions.kw["bind"]
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert client.get(f"{base}/{job['id']}").json()["preview"]["file_count"] == 3
        assert len(client.get(base, params={"limit": 1}).json()["imports"]) == 1
        dataset = client.get(f"{base}/datasets", params={"limit": 1}).json()["datasets"][0]
        assert dataset["file_count"] == 3 and dataset["class_count"] == 1
        assert "classes" not in dataset
        first = client.get(f"{base}/datasets/{result['dataset_id']}/files?limit=2").json()
        second = client.get(f"{base}/datasets/{result['dataset_id']}/files", params={"cursor": first["next_cursor"]}).json()
        assert len(first["files"]) == 2 and len(second["files"]) == 1
        assert {f["id"] for f in first["files"]}.isdisjoint(f["id"] for f in second["files"])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert not any(re.search(r"(?:dataset_import\.preview|imported_dataset\.files)(?:\s|,)", sql) for sql in statements)
