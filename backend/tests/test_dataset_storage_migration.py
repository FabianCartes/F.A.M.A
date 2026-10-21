"""Public maintenance CLI exercised with an isolated in-memory database adapter."""
import json

import pytest
from sqlalchemy import create_engine

from tests.test_dataset_import_api import imports


@pytest.fixture
def storage_database(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE preserved_receipt (id INTEGER PRIMARY KEY, reserved_bytes BIGINT)")
        conn.exec_driver_sql("INSERT INTO preserved_receipt VALUES (1, 40)")
    dispose = engine.dispose
    monkeypatch.setattr(engine, "dispose", lambda: None)
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *args, **kwargs: engine)
    yield engine
    dispose()


def database_snapshot(engine):
    with engine.connect() as conn:
        return "\n".join(conn.connection.driver_connection.iterdump())


def test_storage_inspection_defaults_to_read_only_without_creating_schema(storage_database, capsys):
    from scripts.migrate_dataset_storage import main

    before = database_snapshot(storage_database)
    assert main(["--database-url", "sqlite://"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "action": "inspect", "version": 1, "state": "absent",
        "schema_verified": False, "pools": 0, "live_grants": 0,
    }
    assert database_snapshot(storage_database) == before


def prepare_job_gate(engine):
    from app.models.dataset_import_job import ImportJobGate

    with engine.begin() as conn:
        ImportJobGate.__table__.create(conn)
        conn.execute(ImportJobGate.__table__.insert(), {"id": 1, "version": 1, "generation": 0})


def test_storage_application_is_explicit_additive_repeatable_and_inactive(storage_database, capsys):
    from scripts.migrate_dataset_storage import main

    prepare_job_gate(storage_database)
    arguments = ["--database-url", "sqlite://", "--apply", "--writers-stopped"]
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {
        "action": "prepare", "version": 1, "state": "prepared",
        "schema_verified": True, "pools": 0, "live_grants": 0,
    }
    prepared = database_snapshot(storage_database)
    assert "INSERT INTO \"preserved_receipt\" VALUES(1,40)" in prepared
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "prepared"
    assert database_snapshot(storage_database) == prepared
    assert main(["--database-url", "sqlite://"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "action": "inspect", "version": 1, "state": "prepared",
        "schema_verified": True, "pools": 0, "live_grants": 0,
    }
    assert database_snapshot(storage_database) == prepared


@pytest.mark.parametrize("arguments", [
    ["--apply"], ["--writers-stopped"],
])
def test_storage_maintenance_rejects_unpaired_apply_flags_before_connecting(
        storage_database, monkeypatch, capsys, arguments):
    from scripts.migrate_dataset_storage import main

    connections = []
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **k: connections.append(a))
    before = database_snapshot(storage_database)
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "sqlite://", *arguments])
    assert error.value.code == 2
    assert connections == []
    assert database_snapshot(storage_database) == before
    assert capsys.readouterr().out == ""


def test_storage_inspection_never_creates_a_missing_sqlite_target(
        storage_database, tmp_path, monkeypatch, capsys):
    from scripts.migrate_dataset_storage import main

    target = tmp_path / "private-missing.sqlite"
    connections = []
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **k: connections.append(a))
    with pytest.raises(SystemExit) as error:
        main(["--database-url", f"sqlite:///{target}"])
    assert error.value.code == 1
    assert connections == []
    assert not target.exists()
    output = capsys.readouterr()
    assert output.out == ""
    assert str(target) not in output.err


def test_storage_empty_orm_tables_require_explicit_preparation(storage_database, capsys):
    from app.models.dataset_storage import STORAGE_MODELS
    from scripts.migrate_dataset_storage import main

    prepare_job_gate(storage_database)
    with storage_database.begin() as conn:
        for model in STORAGE_MODELS:
            model.__table__.create(conn)
    before = database_snapshot(storage_database)
    assert main(["--database-url", "sqlite://"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "action": "inspect", "version": 1, "state": "uninitialized",
        "schema_verified": False, "pools": 0, "live_grants": 0,
    }
    assert database_snapshot(storage_database) == before
    assert main(["--database-url", "sqlite://", "--apply", "--writers-stopped"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "prepared"


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("defect", ["partial", "extra_column", "missing_marker_with_data"])
def test_storage_incompatible_state_is_rejected_without_repair(
        storage_database, capsys, apply, defect):
    from app.models.dataset_storage import STORAGE_MODELS, StoragePool
    from scripts.migrate_dataset_storage import main

    prepare_job_gate(storage_database)
    with storage_database.begin() as conn:
        for model in STORAGE_MODELS[:1] if defect == "partial" else STORAGE_MODELS:
            model.__table__.create(conn)
        if defect == "extra_column":
            conn.exec_driver_sql("ALTER TABLE dataset_storage_grant ADD COLUMN unexpected INTEGER")
        if defect == "missing_marker_with_data":
            conn.execute(StoragePool.__table__.insert(), {
                "id": "private-pool", "configuration_sha256": "a" * 64, "free_floor_bytes": 5,
            })
    before = database_snapshot(storage_database)
    arguments = ["--database-url", "sqlite://"] + (["--apply", "--writers-stopped"] if apply else [])
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 1
    assert database_snapshot(storage_database) == before
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Storage maintenance failed; preserve state and inspect the maintenance procedure.\n"


def test_storage_application_requires_existing_verified_queue_without_creating_it(storage_database, capsys):
    from scripts.migrate_dataset_storage import main

    before = database_snapshot(storage_database)
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "sqlite://", "--apply", "--writers-stopped"])
    assert error.value.code == 1
    assert database_snapshot(storage_database) == before
    assert capsys.readouterr().out == ""


def test_storage_replay_preserves_existing_grants_and_omits_private_bindings(storage_database, capsys):
    from app.models.dataset_storage import StorageGrant, StoragePool
    from scripts.migrate_dataset_storage import main

    prepare_job_gate(storage_database)
    arguments = ["--database-url", "sqlite://", "--apply", "--writers-stopped"]
    assert main(arguments) == 0
    capsys.readouterr()
    with storage_database.begin() as conn:
        conn.execute(StoragePool.__table__.insert(), {
            "id": "private-pool", "configuration_sha256": "a" * 64, "free_floor_bytes": 5,
        })
        conn.execute(StorageGrant.__table__.insert(), {
            "id": "b" * 64, "pool_id": "private-pool", "resource_id": "private-resource",
            "phase": "attempt", "attempt": 1, "token": 2, "policy_sha256": "c" * 64,
            "envelope_bytes": 80, "state": "live",
        })
    before = database_snapshot(storage_database)
    for options, action in [(arguments, "prepare"), (["--database-url", "sqlite://"], "inspect")]:
        assert main(options) == 0
        assert json.loads(capsys.readouterr().out) == {
            "action": action, "version": 1, "state": "prepared",
            "schema_verified": True, "pools": 1, "live_grants": 1,
        }
        assert database_snapshot(storage_database) == before


def test_storage_preparation_preserves_actual_receipt_http_contract(imports, monkeypatch, capsys):
    from scripts.migrate_dataset_storage import main
    from tests.test_dataset_import_receipts import create, migrate, start

    client, _, _, sessions = imports
    migrate(sessions)
    identity = create(client)
    assert start(client, identity).status_code == 200
    endpoint = f"/api/ingestion/imports/{identity}/receipt"
    receipt = client.get(endpoint).json()
    engine = sessions.kw["bind"]
    before = database_snapshot(engine)
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    assert main(["--database-url", "sqlite://", "--apply", "--writers-stopped"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "prepared"
    assert client.get(endpoint).json() == receipt
    after = database_snapshot(engine)
    # Only this new schema's preparation marker is added, never a v1 backfill.
    assert after.replace('INSERT INTO "dataset_storage_schema" VALUES(1,1,\'prepared\');\n', "") == before


@pytest.mark.parametrize("apply", [False, True])
def test_storage_rejects_restrictive_extra_check(storage_database, capsys, apply):
    from app.models.dataset_storage import STORAGE_MODELS
    from scripts.migrate_dataset_storage import main

    prepare_job_gate(storage_database)
    with storage_database.begin() as conn:
        for model in STORAGE_MODELS:
            model.__table__.create(conn)
        conn.exec_driver_sql("DROP TABLE dataset_storage_pool")
        conn.exec_driver_sql("""
            CREATE TABLE dataset_storage_pool (
                id VARCHAR(64) NOT NULL PRIMARY KEY,
                configuration_sha256 VARCHAR(64) NOT NULL,
                free_floor_bytes BIGINT NOT NULL,
                CHECK (free_floor_bytes >= 0),
                CHECK (free_floor_bytes = 0)
            )
        """)
    before = database_snapshot(storage_database)
    arguments = ["--database-url", "sqlite://"] + (["--apply", "--writers-stopped"] if apply else [])
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Storage maintenance failed; preserve state and inspect the maintenance procedure.\n"
    assert database_snapshot(storage_database) == before
