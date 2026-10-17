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


def test_verified_legacy_metadata_is_readable_and_extendable_without_rewriting_original_json(imports, tmp_path):
    from sqlalchemy import select
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from scripts.migrate_dataset_import_metadata import migrate_metadata
    from tests.test_dataset_import_metadata_migration import legacy_database, snapshot

    client, _, _, sessions = imports
    source, job_id, dataset_id, _, _ = legacy_database()
    engine = sessions.kw["bind"]
    try:
        original = snapshot(source)
        with engine.begin() as conn:
            for model in (DatasetImport, ImportedDataset):
                conn.execute(model.__table__.insert(), original[model.__tablename__])
        assert client.get(f"/api/ingestion/imports/{job_id}").status_code == 503
        assert client.post("/api/ingestion/imports", json={"request_key": "premature", "name": "Not yet"}).status_code == 503
        assert snapshot(engine) == original
        migrate_metadata(engine, writers_stopped=True)
        job = client.get(f"/api/ingestion/imports/{job_id}").json()
        assert job["preview"]["file_count"] == 1 and job["preview"]["synced_count"] == 0
        member = client.get(f"/api/ingestion/imports/datasets/{dataset_id}/files").json()["files"][0]
        assert member["relative_path"] == "birds/session/a.wav" and member["sync_status"] == "unverified"
        extension = prepare(client, tmp_path, key="extension", target_id=dataset_id, sample=2)
        assert confirm(client, extension).json()["added_count"] == 1
        assert client.get(f"/api/ingestion/imports/datasets/{dataset_id}/files").json()["total"] == 2
        with engine.connect() as conn:
            assert conn.execute(select(DatasetImport.__table__.c.preview).where(DatasetImport.id == job_id)).scalar_one() == original["dataset_import"][0]["preview"]
            assert conn.execute(select(ImportedDataset.__table__.c.files).where(ImportedDataset.id == dataset_id)).scalar_one() == original["imported_dataset"][0]["files"]
    finally:
        source.dispose()


def test_page_configuration_empty_pages_and_malformed_cursors_are_explicit(imports, tmp_path, monkeypatch):
    client, _, _, _ = imports
    monkeypatch.setenv("FAMA_IMPORT_PAGE_SIZE", "1")
    monkeypatch.setenv("FAMA_IMPORT_PAGE_MAX", "2")
    for index in range(3):
        assert client.post("/api/ingestion/imports", json={"request_key": str(index), "name": str(index)}).status_code == 200
    first = client.get("/api/ingestion/imports").json()
    second = client.get("/api/ingestion/imports", params={"cursor": first["next_cursor"]}).json()
    assert len(first["imports"]) == len(second["imports"]) == 1
    assert first["imports"][0]["id"] != second["imports"][0]["id"]
    assert client.get("/api/ingestion/imports?limit=3").status_code == 422
    assert client.get("/api/ingestion/imports?cursor=malformed").status_code == 422
    empty = client.get(f"/api/ingestion/imports/{first['imports'][0]['id']}/files").json()
    assert empty["files"] == [] and empty["total"] == 0 and empty["next_cursor"] is None


def test_canonical_path_collision_is_visible_before_confirmation_and_stale_member_pages_are_rejected(imports, tmp_path):
    client, _, _, _ = imports
    initial = confirm(client, prepare(client, tmp_path)).json()
    target = initial["dataset_id"]
    before = client.get(f"/api/ingestion/imports/datasets/{target}/files").json()
    extension = prepare(client, tmp_path, key="collision", target_id=target, sample=2)
    candidate = client.get(f"/api/ingestion/imports/{extension['id']}/files").json()["files"][0]
    assert candidate["original_path"] == "birds/a.wav"
    assert candidate["relative_path"] == f"birds/a-{candidate['sha256']}-1.wav"
    assert confirm(client, extension).json()["added_count"] == 1
    published = client.get(f"/api/ingestion/imports/datasets/{target}/files?limit=1").json()
    cursor = published["next_cursor"]
    added = prepare(client, tmp_path, key="next", target_id=target, sample=3)
    assert confirm(client, added).json()["added_count"] == 1
    assert client.get(f"/api/ingestion/imports/datasets/{target}/files", params={"cursor": cursor}).status_code == 409
    assert before["total"] == 1


@pytest.mark.parametrize("endpoint", ["files", "classes", "issues", "members", "history", "catalog"])
def test_explicit_empty_cursor_is_rejected_without_changing_any_persisted_data(imports, tmp_path, endpoint):
    client, _, _, sessions = imports
    job = prepare(client, tmp_path)
    target = confirm(client, job).json()["dataset_id"]
    base = "/api/ingestion/imports"
    url = {"members": f"{base}/datasets/{target}/files", "history": base,
           "catalog": f"{base}/datasets"}.get(endpoint, f"{base}/{job['id']}/{endpoint}")
    def digest():
        with sessions.kw["bind"].connect() as conn:
            return hashlib.sha256("\n".join(conn.connection.driver_connection.iterdump()).encode()).hexdigest()
    before = digest()
    response = client.get(url, params={"cursor": ""})
    assert digest() == before
    assert (response.status_code, response.json()) == (422, {"detail": "Cursor de página no válido."})
