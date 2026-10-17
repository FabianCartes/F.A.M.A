"""Sequential receipt protocol through HTTP and explicit maintenance only."""
import hashlib
from types import SimpleNamespace

import pytest

from tests.test_dataset_import_api import imports
from tests.test_dataset_import_receipts import BASE, create, start, migrate, dump


def prepared(imports, monkeypatch, size=10):
    client, _, _, sessions = imports
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", "4")
    migrate(sessions)
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    assert migrate_chunks(sessions.kw["bind"], writers_stopped=True) == {"version": 1, "verified": True}
    identity = create(client)
    assert start(client, identity, size=size).json()["chunk_bytes"] == 4
    return f"{BASE}/{identity}/receipt"


def put(client, url, index, data, offset=None, sha=None):
    return client.put(f"{url}/chunks/{index}", content=data, headers={
        "Content-Type": "application/octet-stream", "X-Chunk-Offset": str(index * 4 if offset is None else offset),
        "X-Chunk-SHA256": sha or hashlib.sha256(data).hexdigest()})


def test_durable_sequential_chunk_and_identical_replay(imports, monkeypatch):
    client, _, _, sessions = imports
    url = prepared(imports, monkeypatch)
    response = put(client, url, 0, b"abcd")
    assert response.status_code == 200, response.text
    assert response.json()["received_bytes"] == 4
    assert client.get(url).json() == response.json()
    before = dump(sessions)
    assert put(client, url, 0, b"abcd").json() == response.json()
    assert dump(sessions) == before


def test_finalize_checks_complete_integrity_and_seals_immutable_archive(imports, monkeypatch):
    client, service, _, sessions = imports
    url = prepared(imports, monkeypatch)
    before = dump(sessions)
    response = client.post(url + "/finalize")
    assert response.status_code == 409, response.text
    assert dump(sessions) == before
    for index, block in enumerate((b"abcd", b"efgh", b"ij")):
        assert put(client, url, index, block).status_code == 200
    response = client.post(url + "/finalize")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "sealed"
    identity = response.json()["import_id"]
    archive = service.root / "staging" / identity / "archive.zip"
    assert archive.read_bytes() == b"abcdefghij"
    assert not archive.with_name("receiving.part").exists()
    assert client.get(f"{BASE}/{identity}").json()["status"] == "validating"
    before = dump(sessions)
    assert client.post(url + "/finalize").json() == response.json()
    assert put(client, url, 0, b"abcd").status_code == 409
    assert put(client, url, 0, b"zzzz").status_code == 409
    assert dump(sessions) == before
    assert archive.read_bytes() == b"abcdefghij"


def test_hash_pages_cover_every_accepted_chunk_and_are_inert(imports, monkeypatch):
    client, _, _, sessions = imports
    url = prepared(imports, monkeypatch)
    for index, block in enumerate((b"abcd", b"efgh", b"ij")):
        assert put(client, url, index, block).status_code == 200
    before = dump(sessions)
    page = client.get(url + "/chunks?limit=2").json()
    assert page["total"] == 3 and len(page["chunks"]) == 2
    assert page["chunks"][0] == {"index": 0, "offset_bytes": 0, "length_bytes": 4,
                                   "sha256": hashlib.sha256(b"abcd").hexdigest()}
    last = client.get(url + "/chunks", params={"cursor": page["next_cursor"], "limit": 2}).json()
    assert [chunk["index"] for chunk in last["chunks"]] == [2]
    assert last["next_cursor"] is None
    assert client.get(url + "/chunks?limit=201").status_code == 422
    assert client.get(url + "/chunks?cursor=").status_code == 422
    assert dump(sessions) == before


def test_hash_pages_default_to_fifty_and_reject_changed_prefix_cursor(imports, monkeypatch):
    client, _, _, sessions = imports
    url = prepared(imports, monkeypatch, size=208)
    for index in range(51):
        assert put(client, url, index, b"abcd").status_code == 200
    before = dump(sessions)
    response = client.get(url + "/chunks")
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["total"] == 51 and len(first["chunks"]) == 50
    assert [chunk["index"] for chunk in first["chunks"]] == list(range(50))
    last = client.get(url + "/chunks", params={"cursor": first["next_cursor"]})
    assert last.status_code == 200, last.text
    assert [chunk["index"] for chunk in last.json()["chunks"]] == [50]
    assert last.json()["next_cursor"] is None
    assert dump(sessions) == before
    assert put(client, url, 51, b"efgh").status_code == 200
    before = dump(sessions)
    response = client.get(url + "/chunks", params={"cursor": first["next_cursor"]})
    assert response.status_code == 409, response.text
    assert dump(sessions) == before
    assert client.get(url).json()["received_bytes"] == 208


def test_cleanup_uses_useful_chunk_activity_not_creation_or_polling(imports, monkeypatch):
    import time
    client, service, _, sessions = imports
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    url = prepared(imports, monkeypatch)
    now += service.limits.ttl_seconds + 1
    assert put(client, url, 0, b"abcd").status_code == 200
    with sessions() as db:
        service.cleanup(db)
    assert client.get(url).json()["status"] == "receiving"
    now += service.limits.ttl_seconds + 1
    before = dump(sessions)
    assert client.get(url).json()["received_bytes"] == 4
    assert dump(sessions) == before
    with sessions() as db:
        service.cleanup(db)
    assert client.get(url).json()["status"] == "cancelled"
    assert client.get(url).json()["reserved_bytes"] == 0


@pytest.mark.parametrize("index,data,offset,sha,code,message", [
    (2, b"ij", 8, None, 409, "El fragmento deja un hueco o solapa otra posición."),
    (1, b"efgh", 3, None, 409, "El fragmento deja un hueco o solapa otra posición."),
    (0, b"zzzz", 0, None, 409, "La posición ya contiene otro fragmento."),
    (1, b"efghi", 4, None, 413, "El fragmento supera la longitud esperada."),
    (1, b"efg", 4, None, 409, "La longitud o SHA-256 del fragmento no coincide."),
    (1, b"efgh", 4, "0" * 64, 409, "La longitud o SHA-256 del fragmento no coincide."),
])
def test_rejected_chunks_preserve_bytes_counters_and_hashes(imports, monkeypatch, index, data, offset, sha, code, message):
    client, service, _, sessions = imports
    url = prepared(imports, monkeypatch)
    assert put(client, url, 0, b"abcd").status_code == 200
    state = client.get(url).json()
    hashes = client.get(url + "/chunks").content
    before = dump(sessions)
    response = put(client, url, index, data, offset=offset, sha=sha)
    assert response.status_code == code, response.text
    assert response.json() == {"detail": message}
    assert dump(sessions) == before
    assert client.get(url).json() == state
    assert client.get(url + "/chunks").content == hashes
    assert (service.root / "staging" / state["import_id"] / "receiving.part").read_bytes() == b"abcd"


def test_exact_multiple_boundary_rejects_even_empty_extra_chunk(imports, monkeypatch):
    client, service, _, sessions = imports
    url = prepared(imports, monkeypatch, size=8)
    assert put(client, url, 0, b"abcd").status_code == 200
    assert put(client, url, 1, b"efgh").status_code == 200
    state = client.get(url).json()
    hashes = client.get(url + "/chunks").content
    before = dump(sessions)
    response = put(client, url, 2, b"")
    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "El fragmento supera el tamaño declarado."}
    assert dump(sessions) == before
    assert client.get(url).json() == state
    assert client.get(url + "/chunks").content == hashes
    assert (service.root / "staging" / state["import_id"] / "receiving.part").read_bytes() == b"abcdefgh"
    assert client.post(url + "/finalize").json()["status"] == "sealed"


def test_owner_checks_cancel_and_existing_import_cancel_behavior(imports, monkeypatch):
    from app.routes.dataset_imports import get_import_user
    client, service, app, sessions = imports
    url = prepared(imports, monkeypatch)
    assert put(client, url, 0, b"abcd").status_code == 200
    state, before = client.get(url).json(), dump(sessions)
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    for response in (put(client, url, 1, b"efgh"), client.get(url), client.get(url + "/chunks"),
                     client.post(url + "/finalize"), client.post(url + "/cancel")):
        assert response.status_code == 404, response.text
    assert dump(sessions) == before
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    response = client.post(url + "/cancel")
    assert response.status_code == 200
    assert response.json() == dict(state, status="cancelled", reserved_bytes=0)
    assert client.post(url + "/cancel").json() == response.json()
    assert (service.root / "staging" / state["import_id"]).exists()
    with sessions() as db:
        service.cleanup(db, attempt_root=client.execution.root)
    assert not (service.root / "staging" / state["import_id"]).exists()
    assert put(client, url, 1, b"efgh").status_code == 409
    assert client.post(url + "/finalize").status_code == 409
    legacy = create(client, "legacy-cancel")
    assert client.post(f"{BASE}/{legacy}/cancel").json()["status"] == "cancelled"


def test_chunk_schema_needs_explicit_ack_and_migration_preserves_receipt_v1(imports, monkeypatch):
    from scripts.migrate_dataset_import_chunks import migrate_chunks, main
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    import contextlib
    import io
    client, _, _, sessions = imports
    migrate(sessions)
    identity = create(client)
    assert start(client, identity).status_code == 200
    before = dump(sessions)
    url = f"{BASE}/{identity}/receipt"
    assert put(client, url, 0, b"abcd").status_code == 503
    assert client.post(url + "/finalize").status_code == 503
    assert client.get(url + "/chunks").status_code == 503
    assert dump(sessions) == before
    engine = sessions.kw["bind"]
    with pytest.raises(ValueError, match="stop_writers_before_chunk_migration"):
        migrate_chunks(engine)
    state = client.get(url).content
    assert migrate_chunks(engine, writers_stopped=True) == {"version": 1, "verified": True}
    assert client.get(url).content == state
    before = dump(sessions)
    assert migrate_chunks(engine, writers_stopped=True) == {"version": 1, "verified": True}
    assert migrate_receipts(engine, writers_stopped=True) == {"version": 1, "verified": True}
    assert dump(sessions) == before
    # CLI owns its engine, while this synthetic fixture owns its memory database.
    monkeypatch.setattr("sqlalchemy.create_engine", lambda _: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        assert main(["--database-url", "sqlite://", "--writers-stopped"]) == 0
    assert output.getvalue() == '{"version": 1, "verified": true}\n'
    assert errors.getvalue() == "" and dump(sessions) == before


def test_chunk_migration_rejects_incompatible_schema_without_changing_data(imports):
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    _, _, _, sessions = imports
    migrate(sessions)
    engine = sessions.kw["bind"]
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS dataset_import_chunk")
        conn.exec_driver_sql("CREATE TABLE dataset_import_chunk (import_id VARCHAR(32) PRIMARY KEY)")
    before = dump(sessions)
    with pytest.raises(ValueError, match="incompatible"):
        migrate_chunks(engine, writers_stopped=True)
    assert dump(sessions) == before


def test_finalize_rejects_changed_middle_and_preserves_receiving_state(imports, monkeypatch):
    client, service, _, sessions = imports
    url = prepared(imports, monkeypatch)
    for index, block in enumerate((b"abcd", b"efgh", b"ij")):
        assert put(client, url, index, block).status_code == 200
    state, before = client.get(url).json(), dump(sessions)
    partial = service.root / "staging" / state["import_id"] / "receiving.part"
    partial.write_bytes(b"abcdzzzzij")
    response = client.post(url + "/finalize")
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "La integridad del archivo recibido no coincide."}
    assert client.get(url).json() == state and dump(sessions) == before
    assert partial.read_bytes() == b"abcdzzzzij"


def test_sealed_receipt_enters_existing_worker_and_protects_active_cancel(imports, monkeypatch, tmp_path):
    from tests.test_dataset_import_api import archive, wav_bytes
    client, _, _, sessions = imports
    data = archive(tmp_path / "tiny.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    url = prepared(imports, monkeypatch, size=len(data))
    for index, offset in enumerate(range(0, len(data), 4)):
        assert put(client, url, index, data[offset:offset + 4]).status_code == 200
    assert client.post(url + "/finalize").status_code == 200
    identity = client.get(url).json()["import_id"]
    response = client.post(f"{BASE}/{identity}/preview", json={"request_key": "review", "root": ""})
    assert response.status_code == 202, response.text
    before = dump(sessions)
    assert client.post(url + "/cancel").status_code == 409
    assert client.post(url + "/finalize").status_code == 409
    assert dump(sessions) == before
    assert client.execution.run_once()
    assert client.get(response.json()["status_url"]).json()["status"] == "succeeded"
    assert client.get(f"{BASE}/{identity}").json()["status"] == "ready"


def test_legacy_whole_upload_and_receipt_admission_replay_still_work(imports, monkeypatch):
    client, _, _, _ = imports
    url = prepared(imports, monkeypatch)
    state = client.get(url).json()
    assert start(client, state["import_id"]).json() == state
    identity = create(client, "whole-body")
    response = client.put(f"{BASE}/{identity}/archive", content=b"legacy", headers={"Content-Type": "application/zip"})
    assert response.status_code == 200 and response.json()["status"] == "validating"
    assert client.put(f"{BASE}/{identity}/archive", content=b"legacy", headers={"Content-Type": "application/zip"}).json() == response.json()


def test_cancel_releases_promise_but_cleanup_retries_directory_durability(imports, monkeypatch):
    from app.services import dataset_imports
    client, service, _, sessions = imports
    url = prepared(imports, monkeypatch)
    assert put(client, url, 0, b"abcd").status_code == 200
    original = dataset_imports._durable_directory
    def fail(path):
        if path == service.root / "staging":
            raise OSError("Synthetic deletion durability failure")
        return original(path)
    monkeypatch.setattr(dataset_imports, "_durable_directory", fail)
    response = client.post(url + "/cancel")
    assert response.status_code == 200, response.text
    assert client.get(url).json()["reserved_bytes"] == 0
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 0, "failed": 1}
    monkeypatch.setattr(dataset_imports, "_durable_directory", original)
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 1, "failed": 0}
    assert client.get(url).json()["reserved_bytes"] == 0


def test_migration_rejects_orphan_chunk_records_without_partial_ack(imports):
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    from sqlalchemy import text
    _, _, _, sessions = imports
    migrate(sessions)
    # Synthetic maintenance input, not a runtime storage test seam.
    assert migrate_chunks(sessions.kw["bind"], writers_stopped=True)["verified"]
    with sessions.kw["bind"].begin() as conn:
        conn.execute(text("INSERT INTO dataset_import_chunk "
            "(import_id, chunk_index, offset_bytes, length_bytes, sha256) VALUES (:id, 0, 0, 4, :sha)"),
            {"id": "f" * 32, "sha": "0" * 64})
    before = dump(sessions)
    with pytest.raises(ValueError, match="incompatible_chunk_reference"):
        migrate_chunks(sessions.kw["bind"], writers_stopped=True)
    assert dump(sessions) == before
