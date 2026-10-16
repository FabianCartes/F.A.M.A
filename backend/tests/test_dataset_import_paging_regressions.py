"""Public pagination, persistence and recovery regression probes."""
import base64
import hashlib
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text

from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_dataset_zip_validation import wav_bytes

BASE = "/api/ingestion/imports"


def digest(sessions):
    with sessions.kw["bind"].connect() as conn:
        return hashlib.sha256("\n".join(conn.connection.driver_connection.iterdump()).encode()).hexdigest()


@pytest.mark.parametrize("collection", ["files", "classes", "issues"])
def test_default_page_boundary_and_rejections_preserve_every_persisted_row(imports, tmp_path, collection):
    client, _, _, sessions = imports
    job = prepare(client, tmp_path, entries=[(f"species{i}/a.wav", wav_bytes(i + 1)) for i in range(51)])
    url = f"{BASE}/{job['id']}/{collection}"
    first = client.get(url).json()
    assert len(first[collection]) == 50 and first["total"] == 51
    assert len(client.get(url, params={"limit": 200}).json()[collection]) == 51
    following = client.get(url, params={"cursor": first["next_cursor"]}).json()
    assert len(following[collection]) == 1 and following["next_cursor"] is None
    assert client.get(url).json() == first
    before = digest(sessions)
    cursors = ["a", "not-base64!", base64.urlsafe_b64encode(b"{}").decode(),
               base64.urlsafe_b64encode(json.dumps(["other", job["preview_token"], 0]).encode()).decode()]
    for cursor in cursors:
        response = client.get(url, params={"cursor": cursor})
        assert (response.status_code, response.json()) == (422, {"detail": "Cursor de página no válido."})
        assert digest(sessions) == before
    for size in [0, -1, 201]:
        assert client.get(url, params={"limit": size}).status_code == 422
        assert digest(sessions) == before
    assert client.post(f"{BASE}/{job['id']}/preview", json={"root": ""}).status_code == 200
    before = digest(sessions)
    response = client.get(url, params={"cursor": first["next_cursor"]})
    assert (response.status_code, response.json()) == (409, {"detail": "La revisión cambió. Consulta de nuevo la primera página."})
    assert digest(sessions) == before


def test_missing_summary_fails_closed_without_legacy_reads_or_partial_writes(imports, tmp_path):
    client, _, _, sessions = imports
    job = prepare(client, tmp_path)
    assert confirm(client, job).status_code == 200
    statements = []
    engine = sessions.kw["bind"]
    def record(conn, cursor, sql, params, context, many):
        statements.append(sql)
    event.listen(engine, "before_cursor_execute", record)
    try:
        for url in [BASE, BASE + "/datasets", f"{BASE}/{job['id']}"]:
            assert client.get(url).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert not any(re.search(r"(?:dataset_import\.preview|imported_dataset\.files)(?:\s|,)", sql) for sql in statements)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dataset_import_summary"))
    before = digest(sessions)
    for method, url, body in [("get", f"{BASE}/{job['id']}", None),
                              ("post", BASE, {"request_key": "new", "name": "new"}),
                              ("post", f"{BASE}/{job['id']}/cancel", {})]:
        response = client.request(method, url, json=body)
        assert (response.status_code, response.json()) == (503, {"detail": "Los metadatos requieren migración verificada antes de continuar."})
        assert digest(sessions) == before


def test_publication_totals_canonical_paths_downloads_and_owner_rejections(imports, tmp_path):
    from app.routes.dataset_imports import get_import_user

    client, _, app, sessions = imports
    target = confirm(client, prepare(client, tmp_path)).json()["dataset_id"]
    second = prepare(client, tmp_path, key="append", target_id=target, sample=2)
    candidate = client.get(f"{BASE}/{second['id']}/files").json()["files"][0]
    assert candidate["relative_path"] == f"birds/a-{candidate['sha256']}-1.wav"
    assert confirm(client, second).status_code == 200
    catalog = client.get(BASE + "/datasets").json()["datasets"][0]
    assert (catalog["file_count"], catalog["class_count"], catalog["total_size_bytes"]) == (2, 1, len(wav_bytes()) * 2)
    files = client.get(f"{BASE}/datasets/{target}/files").json()["files"]
    assert len({file["relative_path"] for file in files}) == 2
    for file in files:
        response = client.get(f"{BASE}/datasets/{target}/files/{file['sha256']}")
        assert hashlib.sha256(response.content).hexdigest() == file["sha256"]
    before = digest(sessions)
    response = client.post(f"{BASE}/{second['id']}/confirm", json={"preview_token": "f" * 64})
    assert (response.status_code, response.json()) == (409, {"detail": "La vista previa cambió. Revísala antes de confirmar."})
    assert digest(sessions) == before
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    for collection in ["files", "classes", "issues"]:
        response = client.get(f"{BASE}/{second['id']}/{collection}")
        assert (response.status_code, response.json()) == (404, {"detail": "Importación no encontrada."})
        assert digest(sessions) == before


def test_migrated_originals_survive_append_and_rejected_backfill_replay(imports, tmp_path):
    from tests.test_dataset_import_metadata_migration import legacy_database
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from scripts.migrate_dataset_import_metadata import migrate_metadata, MetadataMigrationError

    client, _, _, sessions = imports
    source, job_id, target, _, _ = legacy_database()
    engine = sessions.kw["bind"]
    try:
        with source.connect() as old, engine.begin() as destination:
            for model in (DatasetImport, ImportedDataset):
                rows = [dict(row) for row in old.execute(select(model.__table__)).mappings()]
                destination.execute(model.__table__.insert(), rows)
    finally:
        source.dispose()
    def originals():
        with engine.connect() as conn:
            values = [conn.scalar(select(DatasetImport.__table__.c.preview).where(DatasetImport.id == job_id)),
                      conn.scalar(select(ImportedDataset.__table__.c.files).where(ImportedDataset.id == target))]
            return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    original = originals()
    migrate_metadata(engine, writers_stopped=True)
    assert originals() == original
    job = prepare(client, tmp_path, key="postmigration", target_id=target, sample=9)
    assert confirm(client, job).status_code == 200
    assert originals() == original
    before = digest(sessions)
    with pytest.raises(MetadataMigrationError):
        migrate_metadata(engine, writers_stopped=True)
    assert digest(sessions) == before


def test_revision_cursor_rejection_is_atomic(imports, tmp_path):
    client, _, _, sessions = imports
    job = prepare(client, tmp_path, entries=[("birds/a.wav", wav_bytes(1)), ("birds/b.wav", wav_bytes(2))])
    target = confirm(client, job).json()["dataset_id"]
    url = f"{BASE}/datasets/{target}/files"
    old = client.get(url, params={"limit": 1}).json()["next_cursor"]
    assert confirm(client, prepare(client, tmp_path, key="revision", target_id=target, sample=3)).status_code == 200
    before = digest(sessions)
    response = client.get(url, params={"cursor": old})
    assert (response.status_code, response.json()) == (409, {"detail": "La revisión cambió. Consulta de nuevo la primera página."})
    assert digest(sessions) == before


def test_rename_recovery_keeps_existing_members_and_rehashes_objects(imports, tmp_path, monkeypatch):
    from app.services import dataset_imports as module

    client, service, _, sessions = imports
    target = confirm(client, prepare(client, tmp_path)).json()["dataset_id"]
    appended = prepare(client, tmp_path, key="recovery", target_id=target, sample=2)
    url = f"{BASE}/datasets/{target}/files"
    before = client.get(url).json()
    original = module._durable_directory
    def fail(path):
        if path == service.root / "objects":
            raise OSError("synthetic after rename")
        return original(path)
    monkeypatch.setattr(module, "_durable_directory", fail)
    assert confirm(client, appended).status_code == 500
    assert client.get(url).json() == before
    assert client.get(f"{BASE}/{appended['id']}").json()["status"] == "committing"
    audio = next((service.root / "objects" / appended["id"]).iterdir())
    saved = audio.read_bytes()
    audio.write_bytes(b"corrupt")
    monkeypatch.setattr(module, "_durable_directory", original)
    before_hash = digest(sessions)
    response = confirm(client, appended)
    assert (response.status_code, response.json()) == (409, {"detail": "La copia local no coincide. Conserva el estado y solicita recuperación."})
    assert digest(sessions) == before_hash
    audio.write_bytes(saved)
    result = confirm(client, appended)
    assert result.status_code == 200 and result.json()["added_count"] == 1
    assert client.get(url).json()["total"] == 2
    assert confirm(client, appended).json() == result.json()
