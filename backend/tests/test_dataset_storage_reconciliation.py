"""Explicit drain-first reconciliation, never automatic legacy-work adoption."""
import json

import pytest

from tests.test_dataset_import_api import imports  # noqa: F401
from tests.test_dataset_import_storage import configure
from tests.test_dataset_import_receipts import create, start, dump


def prepared(imports, monkeypatch):
    from app.models.dataset_storage import StoragePool, StorageSchema
    policy = configure(imports, monkeypatch, free=10**9)
    with imports[3].begin() as db:
        db.get(StorageSchema, 1).state = "prepared"
        db.query(StoragePool).delete()
    return policy


def test_inventory_classifies_live_legacy_receipt_without_mutation(imports, monkeypatch, capsys):
    from scripts.reconcile_dataset_storage import main
    policy = prepared(imports, monkeypatch)
    client, _, _, sessions = imports
    # Preparation is inert: this is an ordinary unconfigured legacy receipt.
    imports[1].storage_policy = None
    identity = create(client)
    assert start(client, identity, size=10).status_code == 200
    engine = sessions.kw["bind"]
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    before = dump(sessions)
    assert main(["--database-url", "sqlite://"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["action"] == "inventory" and result["drained"] is False
    assert result["counts"]["recoverable_imports"] == 1
    assert result["counts"]["active_receipts"] == 1
    assert result["state"] == "prepared" and result["live_grants"] == 0
    assert identity not in json.dumps(result) and str(policy.roots["imports"]) not in json.dumps(result)
    assert dump(sessions) == before


def test_explicit_drained_cutover_is_atomic_idempotent_and_keeps_v1(imports, monkeypatch):
    from scripts.reconcile_dataset_storage import reconcile_storage
    from app.services.dataset_storage import physical_storage
    policy = prepared(imports, monkeypatch)
    _, service, _, sessions = imports
    engine = sessions.kw["bind"]
    with pytest.raises(ValueError, match="stop_writers"):
        reconcile_storage(engine, policy=policy, apply=True)
    before = dump(sessions)
    result = reconcile_storage(engine, policy=policy, apply=True, writers_stopped=True)
    assert result["action"] == "activate" and result["state"] == "active"
    assert result["drained"] is True and result["live_grants"] == 0
    assert before != dump(sessions)
    with sessions() as db:
        assert physical_storage(service, db) is policy
    after = dump(sessions)
    assert reconcile_storage(engine, policy=policy, apply=True, writers_stopped=True) == result
    assert dump(sessions) == after


def test_cutover_refuses_recoverable_work_without_backfill_or_cancellation(imports, monkeypatch):
    from scripts.reconcile_dataset_storage import reconcile_storage
    policy = prepared(imports, monkeypatch)
    client, service, _, sessions = imports
    service.storage_policy = None
    identity = create(client)
    assert start(client, identity, size=10).status_code == 200
    before = dump(sessions)
    with pytest.raises(ValueError, match="reconciliation_required"):
        reconcile_storage(sessions.kw["bind"], policy=policy, apply=True, writers_stopped=True)
    assert dump(sessions) == before
    assert client.get(f"/api/ingestion/imports/{identity}/receipt").json()["reserved_bytes"] == 40


@pytest.mark.parametrize("defect", ["live_grant", "pool", "busy", "cleanup", "missing_summary"])
def test_cutover_preserves_ambiguous_or_busy_state(imports, monkeypatch, defect):
    import fcntl
    import os
    from app.models.dataset_import import DatasetImport
    from app.models.dataset_import_metadata import ImportSummary
    from app.models.dataset_storage import StorageGrant, StoragePool
    from scripts.reconcile_dataset_storage import reconcile_storage
    policy = prepared(imports, monkeypatch)
    client, service, _, sessions = imports
    service.storage_policy = None
    fd = None
    if defect in ("cleanup", "missing_summary"):
        identity = create(client)
        with sessions.begin() as db:
            db.get(DatasetImport, identity).status = "cancelled"
            if defect == "cleanup":
                db.get(ImportSummary, identity).preview = {"_cleanup": {"state": "deleting"}}
            else:
                db.delete(db.get(ImportSummary, identity))
    elif defect in ("pool", "live_grant"):
        with sessions.begin() as db:
            db.add(StoragePool(id="synthetic", configuration_sha256="0" * 64, free_floor_bytes=5))
            db.flush()
            if defect == "live_grant":
                db.add(StorageGrant(id="1" * 64, pool_id="synthetic", resource_id="leaked",
                    phase="attempt", attempt=1, token=1, policy_sha256="2" * 64,
                    envelope_bytes=10, state="live"))
    else:
        path = policy.roots["exports"] / ("a" * 32 + "-1-1")
        path.mkdir(mode=0o700)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(fd, fcntl.LOCK_SH)
    before = dump(sessions)
    try:
        with pytest.raises(Exception):
            reconcile_storage(sessions.kw["bind"], policy=policy, apply=True, writers_stopped=True)
        assert dump(sessions) == before
    finally:
        if fd is not None:
            os.close(fd)


@pytest.mark.parametrize("arguments", [[], ["--apply"], ["--writers-stopped"],
    ["--apply", "--writers-stopped"], ["--profile", "private.json"]])
def test_reconciliation_cli_rejects_incomplete_invocation_before_connecting(monkeypatch, arguments):
    from scripts.reconcile_dataset_storage import main
    called = []
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: called.append(a))
    with pytest.raises(SystemExit) as error:
        main(arguments if not arguments else ["--database-url", "sqlite://", *arguments])
    assert error.value.code == 2 and called == []


def test_completed_retained_dataset_survives_explicit_cutover(imports, monkeypatch, tmp_path):
    from tests.test_dataset_import_api import prepare, confirm
    from scripts.reconcile_dataset_storage import reconcile_storage
    client, service, _, sessions = imports
    published = confirm(client, prepare(client, tmp_path)).json()
    with sessions() as db:
        service.cleanup(db, attempt_root=client.execution.root)
    policy = prepared(imports, monkeypatch)
    # Fixture preparation preserves the already published objects and history.
    paths = {str(p): p.read_bytes() for p in service.root.rglob("*.wav")}
    assert paths
    result = reconcile_storage(sessions.kw["bind"], policy=policy, apply=True, writers_stopped=True)
    assert result["state"] == "active" and result["live_grants"] == 0
    assert {str(p): p.read_bytes() for p in service.root.rglob("*.wav")} == paths
    assert client.get("/api/ingestion/imports/datasets").json()["datasets"][0]["id"] == published["dataset_id"]


def test_cli_explicit_profile_activates_only_the_selected_synthetic_store(imports, monkeypatch, tmp_path, capsys):
    from scripts.reconcile_dataset_storage import main
    policy = prepared(imports, monkeypatch)
    engine = imports[3].kw["bind"]
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    profile = tmp_path / "private-profile.json"
    profile.write_text(json.dumps(dict(roots={role: str(path) for role, path in policy.roots.items()},
        pools=policy.pools, free_floors=policy.free_floors, manifest_bytes=policy.manifest_bytes)))
    assert main(["--database-url", "sqlite://", "--apply", "--writers-stopped", "--profile", str(profile)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["action"] == "activate" and result["state"] == "active" and result["live_grants"] == 0
    assert str(tmp_path) not in json.dumps(result)


def test_readonly_inventory_does_not_create_a_misspelled_database(tmp_path, monkeypatch, capsys):
    from scripts.reconcile_dataset_storage import main
    target = tmp_path / "missing.sqlite"
    connections = []
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: connections.append(a))
    with pytest.raises(SystemExit) as error:
        main(["--database-url", f"sqlite:///{target}"])
    assert error.value.code == 1 and not target.exists() and connections == []
    output = capsys.readouterr()
    assert output.out == "" and str(target) not in output.err
