"""Public durable queue operations over private synthetic import metadata."""
from dataclasses import replace

import pytest
from fastapi import HTTPException

from tests.test_dataset_import_api import imports


def queue_fixture(imports, *, global_limit=4, owner_limit=1):
    from app.services.dataset_import_jobs import ImportJobQueue, JobLimits
    from scripts.migrate_dataset_import_jobs import migrate_jobs

    from tests.test_dataset_zip_validation import archive, wav_bytes

    client, service, _, sessions = imports
    migrate_jobs(sessions.kw["bind"], writers_stopped=True)
    queue = ImportJobQueue(sessions, limits=JobLimits(global_limit, owner_limit), clock=lambda: 100.0)
    row = client.post("/api/ingestion/imports", json={"request_key": "queue", "name": "Synthetic"}).json()
    data = archive(service.root.parent / "queue.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    assert client.put(f"/api/ingestion/imports/{row['id']}/archive", content=data,
                      headers={"Content-Type": "application/zip"}).status_code == 200
    return queue, row["id"]


def test_identical_admission_returns_one_job_and_conflict_changes_nothing(imports):
    queue, import_id = queue_fixture(imports)
    first = queue.admit(1, import_id, "preview", "operation-1", {"root": "birds"})
    assert first["status"] == "queued"
    assert first["attempt"] == 0 and first["token"] == 0
    assert first["import_id"] == import_id
    assert first["status_url"].endswith(first["id"])
    assert queue.admit(1, import_id, "preview", "operation-1", {"root": "birds"}) == first
    with pytest.raises(HTTPException) as error:
        queue.admit(1, import_id, "preview", "operation-1", {"root": "different"})
    assert error.value.status_code == 409
    assert queue.get(1, first["id"]) == first
    assert queue.active_counts(1) == {"global": 1, "owner": 1}


def test_admission_reserves_capacity_and_cancellation_releases_it_recoverably(imports):
    from app.services.dataset_import_jobs import ImportJobQueue

    queue, import_id = queue_fixture(imports, global_limit=1)
    job = queue.admit(1, import_id, "preview", "one", {"root": ""})
    with pytest.raises(HTTPException) as error:
        queue.admit(1, import_id, "preview", "two", {"root": ""})
    assert error.value.status_code == 429
    assert queue.active_counts(1) == {"global": 1, "owner": 1}
    assert queue.cancel(1, job["id"])["status"] == "cancelled"
    # A new queue instance sees the persisted release; no notification is needed.
    recovered = ImportJobQueue(queue.sessions, limits=queue.limits, clock=queue.clock)
    assert recovered.active_counts(1) == {"global": 0, "owner": 0}
    assert recovered.cancel(1, job["id"])["status"] == "cancelled"
    assert recovered.admit(1, import_id, "preview", "two", {"root": ""})["id"] != job["id"]
    assert recovered.admit(1, import_id, "preview", "one", {"root": ""})["status"] == "cancelled"


def test_job_ownership_and_polling_have_no_mutating_side_effect(imports):
    queue, import_id = queue_fixture(imports)
    job = queue.admit(1, import_id, "preview", "one", {"root": ""})
    for operation in (queue.get, queue.cancel):
        with pytest.raises(HTTPException) as error:
            operation(2, job["id"])
        assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        queue.admit(2, import_id, "preview", "other", {"root": ""})
    assert error.value.status_code == 404
    queue.clock = lambda: 200.0
    assert queue.get(1, job["id"]) == job
    assert queue.active_counts(1) == {"global": 1, "owner": 1}


def test_owner_and_global_limits_are_separate(imports):
    from app.models.dataset_import import DatasetImport
    from app.models.dataset_import_metadata import ImportSummary

    queue, import_id = queue_fixture(imports, global_limit=2, owner_limit=1)
    # Separate owner fixture without authenticating against a live user store.
    with queue.sessions() as db:
        db.add(DatasetImport(id="b" * 32, owner_id=2, request_key="other", request={},
                            status="validating", archive_sha256="a" * 64,
                            created_at=1, preview={}, added_count=0, sync_status="pending"))
        db.flush()
        db.add(ImportSummary(import_id="b" * 32, preview={}, file_count=0, class_count=0,
                             error_count=0, warning_count=0, total_size_bytes=0))
        db.commit()
    queue.admit(1, import_id, "preview", "one", {"root": ""})
    with pytest.raises(HTTPException) as error:
        queue.admit(1, import_id, "preview", "two", {"root": ""})
    assert error.value.status_code == 429
    second = queue.admit(2, "b" * 32, "preview", "one", {"root": ""})
    assert queue.active_counts(2) == {"global": 2, "owner": 1}
    queue.limits = replace(queue.limits, owner_active=2)
    with pytest.raises(HTTPException) as error:
        queue.admit(2, "b" * 32, "preview", "two", {"root": ""})
    assert error.value.status_code == 429
    assert queue.get(2, second["id"])["status"] == "queued"


def test_explicit_migration_preserves_sources_is_replayable_and_requires_maintenance(imports):
    from sqlalchemy import select
    from app.models.dataset_import import DatasetImport
    from scripts.migrate_dataset_import_jobs import JobMigrationError, migrate_jobs

    _, _, _, sessions = imports
    engine = sessions.kw["bind"]
    with engine.connect() as conn:
        before = list(conn.execute(select(DatasetImport.__table__)).mappings())
    with pytest.raises(JobMigrationError, match="stop_writers"):
        migrate_jobs(engine)
    assert migrate_jobs(engine, writers_stopped=True) == {"version": 1, "verified": True}
    assert migrate_jobs(engine, writers_stopped=True) == {"version": 1, "verified": True}
    with engine.connect() as conn:
        assert list(conn.execute(select(DatasetImport.__table__)).mappings()) == before


@pytest.mark.parametrize("kind, parameters", [
    ("preview", {"root": "", "ignored": True}), ("preview", {"root": 3}),
    ("confirm", {"preview_token": "a" * 64}), ("sync", {}),
])
def test_invalid_operation_is_rejected_before_reserving_capacity(imports, kind, parameters):
    queue, import_id = queue_fixture(imports)
    with pytest.raises(HTTPException) as error:
        queue.admit(1, import_id, kind, "invalid", parameters)
    assert error.value.status_code in (409, 422)
    assert queue.active_counts(1) == {"global": 0, "owner": 0}


def test_rejected_admission_rolls_back_every_persisted_change(imports):
    queue, import_id = queue_fixture(imports)
    job = queue.admit(1, import_id, "preview", "operation", {"root": ""})
    engine = queue.sessions.kw["bind"]

    def dump():
        with engine.connect() as conn:
            return "\n".join(conn.connection.driver_connection.iterdump())

    for owner, key, params in [(1, "operation", {"root": "changed"}),
                               (1, "over-capacity", {"root": ""}),
                               (2, "foreign", {"root": ""})]:
        before = dump()
        with pytest.raises(HTTPException):
            queue.admit(owner, import_id, "preview", key, params)
        assert dump() == before
    before = dump()
    with pytest.raises(HTTPException):
        queue.cancel(2, job["id"])
    assert dump() == before


def test_migration_refuses_missing_unique_index_instead_of_repairing_it(imports):
    from scripts.migrate_dataset_import_jobs import JobMigrationError, migrate_jobs

    queue, _ = queue_fixture(imports)
    engine = queue.sessions.kw["bind"]
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX uq_import_job_active_import")
    with pytest.raises(JobMigrationError, match="incompatible_job_indexes"):
        migrate_jobs(engine, writers_stopped=True)


def test_admission_without_explicit_migration_is_unavailable_without_creating_schema(imports):
    from sqlalchemy import inspect
    from app.services.dataset_import_jobs import ImportJobQueue

    client, _, _, sessions = imports
    engine = sessions.kw["bind"]
    # Metadata may have been registered by an earlier case. Neither its presence
    # nor create_all counts as the explicit queue initialization acknowledgement.
    row = client.post("/api/ingestion/imports", json={"request_key": "not-migrated", "name": "X"}).json()
    before = set(inspect(engine).get_table_names())
    with pytest.raises(HTTPException) as error:
        ImportJobQueue(sessions).admit(1, row["id"], "preview", "one", {"root": ""})
    assert error.value.status_code == 503
    assert set(inspect(engine).get_table_names()) == before


def test_migration_rejects_missing_foreign_key_without_changing_data(imports):
    from sqlalchemy import ForeignKeyConstraint, MetaData, inspect
    from app.models.dataset_import_job import ImportJob
    from scripts.migrate_dataset_import_jobs import JobMigrationError, migrate_jobs

    queue, _ = queue_fixture(imports)
    engine = queue.sessions.kw["bind"]
    replacement = ImportJob.__table__.to_metadata(MetaData())
    for constraint in list(replacement.constraints):
        if isinstance(constraint, ForeignKeyConstraint):
            replacement.constraints.remove(constraint)
    with engine.begin() as conn:
        ImportJob.__table__.drop(conn)
        replacement.create(conn)
    assert inspect(engine).get_foreign_keys("dataset_import_job") == []

    def dump():
        with engine.connect() as conn:
            return "\n".join(conn.connection.driver_connection.iterdump())

    before = dump()
    with pytest.raises(JobMigrationError, match="incompatible_job_foreign_keys"):
        migrate_jobs(engine, writers_stopped=True)
    assert dump() == before
