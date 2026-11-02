"""Explicit activation applies only to new synthetic empty labs."""
import pytest
from tests.test_dataset_import_api import imports
from tests.test_dataset_storage_runtime import profile_for
from sqlalchemy.orm import Session
from fastapi import HTTPException


def test_activation_requires_explicit_stopped_writers(imports):
    from scripts.migrate_dataset_storage import activate_empty_lab, inspect_storage, migrate_storage
    _, _, _, sessions = imports
    engine = sessions.kw["bind"]
    migrate_storage(engine, writers_stopped=True)
    before = inspect_storage(engine)
    with pytest.raises(ValueError, match="stop_writers_before_storage_activation"):
        activate_empty_lab(engine, None)
    assert inspect_storage(engine) == before


def test_fresh_activation_admits_and_refuses_reactivation(imports, tmp_path):
    from scripts.migrate_dataset_storage import activate_empty_lab, inspect_storage, migrate_storage
    from app.services.dataset_imports import DatasetImports
    _, _, _, sessions = imports
    engine = sessions.kw["bind"]
    _, policy = profile_for(tmp_path)
    service = DatasetImports(policy.roots["imports"], storage_policy=policy)
    migrate_storage(engine, writers_stopped=True)
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            policy.verify(db, service)
        assert error.value.status_code == 503
    result = activate_empty_lab(engine, policy, writers_stopped=True)
    assert result == dict(version=1, state="active", schema_verified=True,
                          pools=1, live_grants=0, action="activate")
    with Session(engine) as db:
        policy.verify(db, service)
        policy.initial(db, service, "synthetic", 1)
        policy.require(db, service, "synthetic", "archive", 1)
        db.rollback()
    before = inspect_storage(engine)
    with pytest.raises(ValueError, match="storage_requires_prepared_empty_lab"):
        activate_empty_lab(engine, policy, writers_stopped=True)
    assert inspect_storage(engine) == before


def test_existing_import_is_not_adopted(imports, tmp_path):
    from scripts.migrate_dataset_storage import activate_empty_lab, inspect_storage, migrate_storage
    client, _, _, sessions = imports
    engine = sessions.kw["bind"]
    migrate_storage(engine, writers_stopped=True)
    _, policy = profile_for(tmp_path)
    response = client.post("/api/ingestion/imports", json={"request_key": "existing", "name": "Existing"})
    assert response.status_code == 200
    before = inspect_storage(engine)
    with pytest.raises(ValueError, match="storage_requires_empty_lab"):
        activate_empty_lab(engine, policy, writers_stopped=True)
    assert inspect_storage(engine) == before
    assert client.get(f"/api/ingestion/imports/{response.json()['id']}").json()["status"] == "receiving"


def test_failed_transition_rolls_back_pool_authority(imports, tmp_path):
    from scripts.migrate_dataset_storage import activate_empty_lab, inspect_storage, migrate_storage
    from sqlalchemy.exc import DBAPIError
    _, _, _, sessions = imports
    engine = sessions.kw["bind"]
    migrate_storage(engine, writers_stopped=True)
    _, policy = profile_for(tmp_path)
    before = inspect_storage(engine)
    # Fixture-only database fault at the actual transition, after pool insertion.
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TRIGGER refuse_activation BEFORE UPDATE ON dataset_storage_schema "
                             "BEGIN SELECT RAISE(ABORT, 'synthetic transition failure'); END")
    with pytest.raises(DBAPIError):
        activate_empty_lab(engine, policy, writers_stopped=True)
    assert inspect_storage(engine) == before
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            policy.verify(db)
        assert error.value.status_code == 503


def test_changed_root_is_rejected_without_activation(imports, tmp_path):
    from scripts.migrate_dataset_storage import activate_empty_lab, inspect_storage, migrate_storage
    _, _, _, sessions = imports
    engine = sessions.kw["bind"]
    migrate_storage(engine, writers_stopped=True)
    _, policy = profile_for(tmp_path)
    before = inspect_storage(engine)
    # A real topology change after profile construction, not a mocked verifier.
    policy.roots["attempts"].chmod(0o755)
    with pytest.raises(ValueError):
        activate_empty_lab(engine, policy, writers_stopped=True)
    assert inspect_storage(engine) == before
