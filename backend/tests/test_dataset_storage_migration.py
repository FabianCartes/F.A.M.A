"""Explicit preparation of empty synthetic metadata; never operational activation."""
import pytest
from sqlalchemy import create_engine

from tests.test_dataset_import_api import imports


def test_inspect_does_not_prepare_and_preparation_requires_stopped_writers():
    from scripts.migrate_dataset_storage import inspect_storage, migrate_storage
    engine = create_engine("sqlite://")
    try:
        absent = {"version": 1, "state": "absent", "schema_verified": False, "pools": 0, "live_grants": 0}
        assert inspect_storage(engine) == dict(absent, action="inspect")
        with pytest.raises(ValueError, match="stop_writers_before_storage_migration"):
            migrate_storage(engine)
        assert inspect_storage(engine) == dict(absent, action="inspect")
    finally:
        engine.dispose()


def test_empty_lab_preparation_is_idempotent_and_never_authorizes(imports):
    from scripts.migrate_dataset_storage import inspect_storage, migrate_storage
    client, service, _, sessions = imports
    engine = sessions.kw["bind"]
    expected = {"version": 1, "state": "prepared", "schema_verified": True, "pools": 0, "live_grants": 0}
    assert migrate_storage(engine, writers_stopped=True) == dict(expected, action="prepare")
    assert migrate_storage(engine, writers_stopped=True) == dict(expected, action="prepare")
    assert inspect_storage(engine) == dict(expected, action="inspect")


def test_preparation_refuses_existing_import_without_adoption(imports):
    from scripts.migrate_dataset_storage import inspect_storage, migrate_storage
    client, _, _, sessions = imports
    response = client.post("/api/ingestion/imports", json={"request_key": "existing", "name": "Existing"})
    assert response.status_code == 200
    before = inspect_storage(sessions.kw["bind"])
    with pytest.raises(ValueError, match="storage_requires_empty_lab"):
        migrate_storage(sessions.kw["bind"], writers_stopped=True)
    assert inspect_storage(sessions.kw["bind"]) == before
    assert client.get(f"/api/ingestion/imports/{response.json()['id']}").json()["status"] == "receiving"
