"""Receipt admission through authenticated HTTP and explicit maintenance migration."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text

from tests.test_dataset_import_api import imports


BASE = "/api/ingestion/imports"


def create(client, key="receipt"):
    response = client.post(BASE, json={"request_key": key, "name": key})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def migrate(sessions):
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    return migrate_receipts(sessions.kw["bind"], writers_stopped=True)


def dump(sessions):
    with sessions.kw["bind"].connect() as conn:
        return "\n".join(conn.connection.driver_connection.iterdump())


def start(client, identity, size=10, name="birds.zip"):
    return client.post(f"{BASE}/{identity}/receipt", json={"name": name, "size_bytes": size})


def test_receipt_reservation_is_durable_idempotent_and_owner_only(imports):
    client, service, app, sessions = imports
    migrate(sessions)
    identity = create(client)
    response = start(client, identity)
    assert response.status_code == 200, response.text
    expected = {"import_id": identity, "name": "birds.zip", "size_bytes": 10,
                "reserved_bytes": 10 + service.limits.expanded_bytes, "received_bytes": 0,
                "chunk_bytes": 16 * 1024**2, "status": "receiving"}
    assert response.json() == expected
    assert start(client, identity).json() == expected
    # HTTP readers use fresh sessions, not the mutation session's identity map.
    before = dump(sessions)
    assert client.get(f"{BASE}/{identity}/receipt").json() == expected
    assert dump(sessions) == before
    assert start(client, identity, size=11).status_code == 409
    assert dump(sessions) == before
    from app.routes.dataset_imports import get_import_user
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.get(f"{BASE}/{identity}/receipt").status_code == 404
    assert start(client, identity).status_code == 404
    assert dump(sessions) == before


def test_receipt_size_boundary_and_one_byte_over_are_atomic(imports):
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=20, expanded_bytes=30)
    migrate(sessions)
    identity = create(client)
    before = dump(sessions)
    assert start(client, identity, size=21).status_code == 413
    assert dump(sessions) == before
    assert start(client, identity, size=20).json()["reserved_bytes"] == 50


def test_receipt_one_owner_at_a_time_and_cancel_releases_reservation(imports):
    client, _, _, sessions = imports
    migrate(sessions)
    first = create(client, "first")
    assert start(client, first).status_code == 200
    second = create(client, "second")
    before = dump(sessions)
    assert start(client, second).status_code == 429
    assert dump(sessions) == before
    assert client.post(f"{BASE}/{first}/cancel").status_code == 200
    assert client.get(f"{BASE}/{first}/receipt").json()["reserved_bytes"] == 0
    assert start(client, second).status_code == 200
    assert start(client, first).status_code == 409


def test_reserved_receipt_cannot_bypass_budget_through_whole_archive_upload(imports):
    client, service, _, sessions = imports
    migrate(sessions)
    identity = create(client)
    assert start(client, identity).status_code == 200
    before = dump(sessions)
    response = client.put(f"{BASE}/{identity}/archive", content=b"different archive",
                          headers={"Content-Type": "application/zip"})
    assert response.status_code == 409
    assert dump(sessions) == before
    assert not service.stage(SimpleNamespace(id=identity)).exists()


def test_failed_cleanup_retains_bytes_after_cancel_releases_promise(imports, monkeypatch):
    client, service, _, sessions = imports
    migrate(sessions)
    identity = create(client)
    assert start(client, identity).status_code == 200
    directory = service.stage(SimpleNamespace(id=identity))
    directory.mkdir(mode=0o700)
    (directory / "part").write_bytes(b"synthetic")
    import shutil
    original = shutil.rmtree
    def fail(path, *args, **kwargs):
        if path == directory:
            raise OSError("induced deletion failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr("app.services.dataset_imports.shutil.rmtree", fail)
    assert client.post(f"{BASE}/{identity}/cancel").status_code == 200
    assert client.get(f"{BASE}/{identity}/receipt").json()["reserved_bytes"] == 0
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 0, "failed": 1}
    assert (directory / "part").read_bytes() == b"synthetic"
    monkeypatch.setattr("app.services.dataset_imports.shutil.rmtree", original)
    assert client.post(f"{BASE}/{identity}/cancel").status_code == 409
    assert client.get(f"{BASE}/{identity}/receipt").json()["reserved_bytes"] == 0
    with sessions() as db:
        assert service.cleanup(db, attempt_root=client.execution.root) == {"completed": 1, "failed": 0}
    assert not directory.exists()


def test_receipt_global_budget_and_free_margin_are_independent(imports, monkeypatch):
    from app.routes.dataset_imports import get_import_user
    client, service, app, sessions = imports
    service.limits = replace(service.limits, received_bytes=20, expanded_bytes=30, free_bytes=5)
    monkeypatch.setenv("FAMA_IMPORT_RESERVED_BYTES_GLOBAL", "60")
    migrate(sessions)
    first = create(client, "first")
    monkeypatch.setattr("app.services.dataset_imports.shutil.disk_usage", lambda _: SimpleNamespace(free=1000))
    assert start(client, first).status_code == 200  # 40 bytes promised.
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    second = create(client, "second")
    before = dump(sessions)
    assert start(client, second).status_code == 429
    assert dump(sessions) == before
    monkeypatch.setenv("FAMA_IMPORT_RESERVED_BYTES_GLOBAL", "100")
    monkeypatch.setattr("app.services.dataset_imports.shutil.disk_usage", lambda _: SimpleNamespace(free=84))
    assert start(client, second).status_code == 507  # 40 + 40 + 5 > 84.
    assert dump(sessions) == before
    monkeypatch.setattr("app.services.dataset_imports.shutil.disk_usage", lambda _: SimpleNamespace(free=85))
    assert start(client, second).status_code == 200


def test_receipt_explicit_owner_budget_has_exact_boundary(imports, monkeypatch):
    client, service, _, sessions = imports
    service.limits = replace(service.limits, received_bytes=20, expanded_bytes=30)
    monkeypatch.setenv("FAMA_IMPORT_RESERVED_BYTES_PER_OWNER", "40")
    migrate(sessions)
    identity = create(client)
    before = dump(sessions)
    assert start(client, identity, size=11).status_code == 429
    assert dump(sessions) == before
    assert start(client, identity, size=10).status_code == 200


def test_receipt_without_migration_does_not_create_or_mutate_schema(imports):
    client, _, _, sessions = imports
    identity = create(client)
    before = dump(sessions)
    assert start(client, identity).status_code == 503
    assert dump(sessions) == before


def test_receipt_migration_requires_maintenance_is_additive_and_replayable(imports):
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    client, _, _, sessions = imports
    identity = create(client)
    before = client.get(f"{BASE}/{identity}").json()
    engine = sessions.kw["bind"]
    with pytest.raises(ValueError, match="stop_writers"):
        migrate_receipts(engine)
    assert migrate_receipts(engine, writers_stopped=True) == {"version": 1, "verified": True}
    assert migrate_receipts(engine, writers_stopped=True) == {"version": 1, "verified": True}
    assert client.get(f"{BASE}/{identity}").json() == before
    assert "dataset_import_receipt" in inspect(engine).get_table_names()


def test_receipt_migration_refuses_incompatible_table_without_repair(imports):
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    _, _, _, sessions = imports
    engine = sessions.kw["bind"]
    # Registration by earlier cases may have created an empty table, not an
    # acknowledgement. Replace only this new table with an incompatible fixture.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS dataset_import_receipt")
        conn.execute(text("CREATE TABLE dataset_import_receipt (import_id VARCHAR(32) PRIMARY KEY)"))
    before = dump(sessions)
    with pytest.raises(ValueError, match="incompatible"):
        migrate_receipts(engine, writers_stopped=True)
    assert dump(sessions) == before


@pytest.mark.parametrize("payload", [
    {"name": "birds.zip", "size_bytes": 0},
    {"name": "birds.zip", "size_bytes": -1},
    {"name": "birds.zip", "size_bytes": True},
    {"name": "birds.zip", "size_bytes": "1"},
    {"name": "birds.zip", "size_bytes": 1.0},
    {"name": "   ", "size_bytes": 1},
    {"name": "birds.zip", "size_bytes": 1, "offset": 0},
])
def test_receipt_malformed_explicit_values_are_rejected_atomically(imports, payload):
    client, _, _, sessions = imports
    migrate(sessions)
    identity = create(client)
    before = dump(sessions)
    response = client.post(f"{BASE}/{identity}/receipt", json=payload)
    assert response.status_code == 422, response.text
    assert dump(sessions) == before


def test_multiple_published_datasets_are_not_an_owner_storage_quota(imports, tmp_path):
    from tests.test_dataset_import_api import prepare, confirm
    client, _, _, sessions = imports
    migrate(sessions)
    for sample in (1, 2):
        preview = prepare(client, tmp_path, key=f"published-{sample}",
                          name=f"Dataset {sample}", sample=sample)
        response = confirm(client, preview)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "imported"
    catalogue = client.get(f"{BASE}/datasets").content
    assert len(client.get(f"{BASE}/datasets").json()["datasets"]) == 2
    identity = create(client, "third")
    assert start(client, identity, size=1).status_code == 200
    assert client.get(f"{BASE}/datasets").content == catalogue
