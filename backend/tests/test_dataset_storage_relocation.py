"""Public offline relocation CLI contract; synthetic paths only."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from tests.test_dataset_import_api import imports, operation, confirm

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/relocate_dataset_storage.py"


def cli(source, destination, *flags):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--source-root", str(source),
         "--destination-root", str(destination), *flags],
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
             "PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": "sqlite://"},
        capture_output=True, text=True, timeout=10, check=False)


def test_cli_requires_stopped_writers_before_touching_paths(tmp_path):
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    sentinel = source / "untouched"
    sentinel.write_bytes(b"synthetic original")
    before = sentinel.stat()
    destination = tmp_path / "destination"
    result = cli(source, destination)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "--writers-stopped" in result.stderr
    assert not destination.exists()
    assert sentinel.read_bytes() == b"synthetic original"
    after = sentinel.stat()
    assert (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
        before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)


def test_cli_help_is_explicit_and_nonmutating(tmp_path):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--help"],
                            capture_output=True, text=True, timeout=10, check=False,
                            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0
    assert result.stderr == ""
    assert all(option in result.stdout for option in
               ("--source-root", "--destination-root", "--writers-stopped"))
    assert not list(tmp_path.iterdir())


def private_json(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(value, stream)


def snapshot(root):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(),
            p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("damage", [None, "existing", "corrupt", "missing", "active", "profile", "link", "binding", "unknown", "environment", "missing_archive", "missing_attempt", "empty_attempt", "trigger", "automatic"])
def test_cli_relocates_catalog_and_live_authority_without_changing_source(imports, tmp_path, monkeypatch, damage):
    from app.services.dataset_storage import PhysicalStorage
    from scripts.migrate_dataset_storage import migrate_storage, activate_empty_lab
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.services.dataset_imports import DatasetImports
    from app.database import get_db
    from app.routes.dataset_imports import get_import_service

    client, service, app, sessions = imports
    from types import SimpleNamespace
    from app.routes.dataset_imports import get_import_user
    from tests.test_dataset_import_receipts import migrate
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    from tests.test_dataset_import_chunks import put
    from tests.test_dataset_zip_validation import archive, wav_bytes
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=-1)
    migrate(sessions)
    migrate_chunks(sessions.kw["bind"], writers_stopped=True)
    if damage == "automatic":
        from app.services.dataset_import_execution import ImportExecution
        from app.services.dataset_import_jobs import ImportJobQueue
        attempt_root = tmp_path / "separate-attempts"
        attempt_root.mkdir(mode=0o700)
        client.execution = ImportExecution(ImportJobQueue(sessions), service, attempt_root)
    roots = dict(imports=str(service.root), objects=str(service.root / "objects"),
                 attempts=str(service.attempt_root), manifests=str(service.attempt_root),
                 scratch=str(tmp_path / "scratch"), exports=str(tmp_path / "exports-disabled"))
    for role in ("scratch", "exports"):
        Path(roots[role]).mkdir(mode=0o700)
    config = dict(roots=roots, pools=dict.fromkeys(roots, "ssd"), free_floors={"ssd": 1})
    policy = PhysicalStorage(**config)
    migrate_storage(sessions.kw["bind"], writers_stopped=True)
    activate_empty_lab(sessions.kw["bind"], policy, writers_stopped=True)
    service.storage_policy = policy
    response = client.post("/api/ingestion/imports", json={"request_key": "relocate", "name": "Birds", "auto_import": damage == "automatic"})
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    data = archive(tmp_path / "synthetic.zip", [("birds/a.wav", wav_bytes())]).read_bytes()
    receipt_url = f"/api/ingestion/imports/{identity}/receipt"
    receipt = client.post(receipt_url, json={"name": "synthetic.zip", "size_bytes": len(data)})
    assert receipt.status_code == 200, receipt.text
    assert put(client, receipt_url, 0, data).status_code == 200
    assert client.post(receipt_url + "/finalize").status_code == 200
    preview = operation(client, identity, "preview", {"root": ""})
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["status"] == ("imported" if damage == "automatic" else "ready"), job
    published = preview if damage == "automatic" else confirm(client, job)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "imported", published.text
    catalog_url = "/api/ingestion/imports/datasets"
    catalog = client.get(catalog_url).json()
    dataset = catalog["datasets"][0]
    files_url = f"{catalog_url}/{dataset['id']}/files"
    files = client.get(files_url).json()
    member = files["files"][0]
    download_url = f"{files_url}/{member['sha256']}"
    audio = client.get(download_url).content
    database = tmp_path / "manual.sqlite3"
    os.close(os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    with sessions.kw["bind"].connect() as connection, sqlite3.connect(database) as target:
        connection.connection.driver_connection.backup(target)
    private_json(tmp_path / "profile.json", config)
    private_json(tmp_path / "environment.json", {"FAMA_IMPORT_FREE_BYTES": "1"})
    destination = tmp_path.parent / (tmp_path.name + "-relocated")
    if damage == "existing":
        destination.mkdir(mode=0o700)
        (destination / "keep").write_bytes(b"previous destination")
    elif damage == "corrupt":
        next((service.root / "objects").rglob("*.wav")).write_bytes(b"corrupt")
    elif damage == "missing":
        original = next((service.root / "objects").rglob("*.wav"))
        original.rename(original.with_suffix(".missing"))
    elif damage == "active":
        response = client.post(f"/api/ingestion/imports/{identity}/confirm",
            json={"request_key": "pending-job", "preview_token": job["preview_token"]})
        assert response.status_code == 202, response.text
        with sessions.kw["bind"].connect() as connection, sqlite3.connect(database) as target:
            connection.connection.driver_connection.backup(target)
    elif damage == "profile":
        config["roots"]["scratch"] = str(tmp_path.parent)
        (tmp_path / "profile.json").write_text(json.dumps(config))
    elif damage == "link":
        (service.root / "external-link").symlink_to(tmp_path.parent)
    elif damage == "binding":
        (tmp_path / "environment.json").write_text(json.dumps({"FAMA_IMPORT_FREE_BYTES": "2"}))
    if damage == "unknown":
        with sessions() as db:
            policy.acquire(db, resource="unrecognized", phase="unexpected", attempt=0, token=0,
                           amounts={"ssd": 1}, policy=policy.policy_hash(service.limits))
            db.commit()
        with sessions.kw["bind"].connect() as connection, sqlite3.connect(database) as target:
            connection.connection.driver_connection.backup(target)
    if damage in ("missing_archive", "missing_attempt"):
        # Fault injection only: corruption is observed through the public CLI.
        with sqlite3.connect(database) as target:
            target.execute("DELETE FROM dataset_storage_grant WHERE state='live' AND phase=?",
                           ("archive" if damage == "missing_archive" else "attempt",))
    elif damage == "empty_attempt":
        # The worker produced this extraction; leave its expected attempt empty.
        extracted = next(Path(roots["attempts"]).glob("*/files"))
        attempt = extracted.parent
        attempt.rename(tmp_path / "displaced-attempt")
        attempt.mkdir(mode=0o700)
    if damage == "trigger":
        with sqlite3.connect(database) as target:
            target.execute("CREATE TRIGGER unexpected_authority AFTER UPDATE ON dataset_storage_pool BEGIN SELECT 1; END")
    receipt_environment = {"FAMA_IMPORT_CHUNK_BYTES": str(16 * 1024**2),
                           "FAMA_IMPORT_RESERVED_BYTES_PER_OWNER": str(16 * 1024**3),
                           "FAMA_IMPORT_RESERVED_BYTES_GLOBAL": str(16 * 1024**3)}
    if damage == "environment":
        (tmp_path / "environment.json").write_text(json.dumps(
            dict(receipt_environment, FAMA_IMPORT_FREE_BYTES="1")))
    before = snapshot(tmp_path)
    previous = snapshot(destination) if destination.exists() else None
    result = cli(tmp_path, destination, "--writers-stopped")
    if damage not in (None, "environment", "automatic"):
        assert result.returncode == 1, result.stderr
        assert result.stdout == ""
        expected = {"existing": "fresh_absolute_destination_required",
                    "corrupt": "published_content_mismatch", "missing": "published_content_mismatch",
                    "active": "active_job", "profile": "one_confined_pool_required",
                    "link": "unsupported_role_entry", "binding": "unknown_grant_binding",
                    "unknown": "unknown_grant_resource", "missing_archive": "required_live_authority",
                    "missing_attempt": "required_live_authority", "empty_attempt": "retained_payload",
                    "trigger": "unsupported_schema_object"}
        assert "relocation refused:" in result.stderr
        assert expected[damage] in result.stderr
        assert snapshot(tmp_path) == before
        if previous is not None:
            assert snapshot(destination) == previous
        else:
            assert not destination.exists()
        return
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["status"] == "complete"
    if damage == "environment":
        copied_environment = json.loads((destination / "environment.json").read_text())
        assert all(copied_environment.get(key) == value for key, value in receipt_environment.items())
    assert snapshot(tmp_path) == before
    new_policy = PhysicalStorage(**json.loads((destination / "profile.json").read_text()))
    new_service = DatasetImports(new_policy.roots["imports"], limits=service.limits, storage_policy=new_policy)
    engine = create_engine(f"sqlite:///{destination / 'manual.sqlite3'}")
    from app.models.dataset_storage import StorageGrant
    for factory, checked_policy, checked_service in ((sessions, policy, service),
            (lambda: Session(engine), new_policy, new_service)):
        with factory() as db:
            checked_policy.verify(db, checked_service)
            for grant in db.query(StorageGrant).filter_by(state="live"):
                checked_policy.require(db, checked_service, grant.resource_id, grant.phase,
                    grant.envelope_bytes, attempt=grant.attempt, token=grant.token)
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.get(download_url).status_code == 404
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=-1)
    def copied_database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = copied_database
    app.dependency_overrides[get_import_service] = lambda: new_service
    assert client.get(catalog_url).json() == catalog
    assert client.get(files_url).json() == files
    copied_audio = client.get(download_url).content
    assert copied_audio == audio
    assert hashlib.sha256(copied_audio).hexdigest() == member["sha256"]
    assert len(copied_audio) == member["size_bytes"]
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.get(download_url).status_code == 404
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=-1)
    for relative, details in before.items():
        copied = destination / relative
        if copied.is_file():
            assert copied.stat().st_ino != details[1]
    if damage == "environment":
        from dataclasses import replace
        for key, value in copied_environment.items():
            monkeypatch.setenv(key, value)
        created = client.post("/api/ingestion/imports", json={"request_key": "budget-boundary", "name": "Boundary"})
        assert created.status_code == 200, created.text
        url = f"/api/ingestion/imports/{created.json()['id']}/receipt"
        new_service.limits = replace(service.limits, expanded_bytes=16 * 1024**3)
        assert client.post(url, json={"name": "boundary.zip", "size_bytes": 1}).status_code == 429
        new_service.limits = service.limits
        reserved = client.post(url, json={"name": "boundary.zip", "size_bytes": 1})
        assert reserved.status_code == 200, reserved.text
        assert reserved.json()["chunk_bytes"] == 16 * 1024**2
        assert snapshot(tmp_path) == before
    engine.dispose()
