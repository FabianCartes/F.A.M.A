"""Independent acceptance probes promoted after synthetic T3b verification."""
import hashlib

import pytest

from tests.test_dataset_import_api import imports


BASE = "/api/ingestion/imports"


def prepare_receipt(imports, monkeypatch, size=9):
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    client, service, _, sessions = imports
    monkeypatch.setenv("FAMA_IMPORT_CHUNK_BYTES", "4")
    migrate_receipts(sessions.kw["bind"], writers_stopped=True)
    migrate_chunks(sessions.kw["bind"], writers_stopped=True)
    response = client.post(BASE, json={"request_key": "regression", "name": "Regression"})
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    url = f"{BASE}/{identity}/receipt"
    assert client.post(url, json={"name": "sample.zip", "size_bytes": size}).status_code == 200
    return url, service.root / "staging" / identity / "receiving.part"


def send_block(client, url, index, data):
    return client.put(f"{url}/chunks/{index}", content=data, headers={
        "Content-Type": "application/octet-stream", "X-Chunk-Offset": str(index * 4),
        "X-Chunk-SHA256": hashlib.sha256(data).hexdigest()})


@pytest.mark.parametrize("mutation,error", [
    ("UPDATE dataset_import_receipt SET received_bytes=3", "incompatible_chunk_progress"),
    ("UPDATE dataset_import_chunk SET offset_bytes=1", "incompatible_chunk_prefix"),
    ("DELETE FROM dataset_import_chunk_activity", "incompatible_chunk_activity"),
    ("UPDATE dataset_import_chunk SET sha256='" + "z" * 64 + "'", "incompatible_chunk_prefix"),
])
def test_migration_rejects_inconsistent_prefix_without_partial_activation(imports, monkeypatch, mutation, error):
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    client, _, _, sessions = imports
    url, path = prepare_receipt(imports, monkeypatch)
    assert send_block(client, url, 0, b"abcd").status_code == 200
    engine = sessions.kw["bind"]
    with engine.begin() as connection:
        connection.exec_driver_sql(mutation)
        connection.exec_driver_sql("DELETE FROM dataset_import_chunk_schema")
    def dump():
        with engine.connect() as connection:
            return "\n".join(connection.connection.driver_connection.iterdump())
    before = dump()
    with pytest.raises(ValueError, match=error):
        migrate_chunks(engine, writers_stopped=True)
    assert dump() == before and path.read_bytes() == b"abcd"
