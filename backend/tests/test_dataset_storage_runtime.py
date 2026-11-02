"""Shared public runtime selection; no ambient application or database."""
import json


def profile_for(tmp_path):
    from app.services.dataset_storage import PhysicalStorage
    root = tmp_path / "physical-imports"
    root.mkdir(mode=0o700)
    objects = root / "objects"
    objects.mkdir(mode=0o700)
    attempts = tmp_path / "physical-attempts"
    attempts.mkdir(mode=0o700)
    roots = dict(imports=str(root), objects=str(objects), attempts=str(attempts),
                 manifests=str(attempts), scratch=str(attempts), exports=str(attempts))
    config = dict(roots=roots, pools=dict.fromkeys(roots, "ssd"), free_floors={"ssd": 1024**3})
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(config))
    return path, PhysicalStorage(**config)

import pytest
from fastapi import HTTPException
from tests.test_dataset_import_api import imports


def test_unset_profile_preserves_default(tmp_path, monkeypatch):
    from app.services.dataset_storage_runtime import runtime_import_service
    monkeypatch.delenv("FAMA_IMPORT_STORAGE_PROFILE", raising=False)
    service = runtime_import_service(tmp_path / "not-created")
    assert service.root == tmp_path / "not-created"
    assert not service.root.exists()
    assert service.storage_policy is None


def test_http_and_worker_builder_share_mapping_without_activation(tmp_path, monkeypatch):
    from app.services.dataset_storage_runtime import runtime_import_service
    from app.routes.dataset_imports import get_import_service
    path, policy = profile_for(tmp_path)
    monkeypatch.setenv("FAMA_IMPORT_STORAGE_PROFILE", str(path))
    monkeypatch.setenv("FAMA_IMPORT_ROOT", str(policy.roots["imports"]))
    http = get_import_service()
    worker = runtime_import_service(policy.roots["imports"], attempt_root=policy.roots["attempts"])
    assert http.root == worker.root == policy.roots["imports"]
    assert http.attempt_root == worker.attempt_root == policy.roots["attempts"]
    assert http.storage_policy.configuration_sha256 == worker.storage_policy.configuration_sha256
    assert worker.storage_policy.manifest_bytes == 64 * 1024**2
    with pytest.raises(HTTPException) as error:
        runtime_import_service(policy.roots["imports"], attempt_root=tmp_path)
    assert error.value.status_code == 503
    assert list(policy.roots["objects"].iterdir()) == []
    assert list(policy.roots["attempts"].iterdir()) == []


@pytest.mark.parametrize("damage", ["symlink", "writable", "directory", "root-mismatch"])
def test_profile_path_and_mapping_fail_closed(tmp_path, monkeypatch, damage):
    from app.services.dataset_storage_runtime import runtime_import_service
    path, policy = profile_for(tmp_path)
    root = policy.roots["imports"]
    if damage == "symlink":
        link = tmp_path / "profile-link.json"
        link.symlink_to(path)
        path = link
    elif damage == "writable":
        path.chmod(0o666)
    elif damage == "directory":
        path = tmp_path
    else:
        root = tmp_path
    monkeypatch.setenv("FAMA_IMPORT_STORAGE_PROFILE", str(path))
    with pytest.raises(HTTPException) as error:
        runtime_import_service(root)
    assert error.value.status_code == 503
    assert list(policy.roots["objects"].iterdir()) == []


def test_http_invalid_profile_refuses_without_admission(imports, monkeypatch):
    from app.routes.dataset_imports import get_import_service
    from scripts.migrate_dataset_storage import inspect_storage
    client, _, app, sessions = imports
    before = inspect_storage(sessions.kw["bind"])
    baseline = client.get("/api/ingestion/imports").json()
    app.dependency_overrides.pop(get_import_service)
    monkeypatch.setenv("FAMA_IMPORT_STORAGE_PROFILE", "")
    response = client.post("/api/ingestion/imports", json={"request_key": "refused", "name": "Refused"})
    assert response.status_code == 503
    assert response.json() == {"detail": "El presupuesto físico requiere un perfil activo y compatible."}
    assert inspect_storage(sessions.kw["bind"]) == before
    monkeypatch.delenv("FAMA_IMPORT_STORAGE_PROFILE")
    # Restore the original fixture service to observe public state without creating paths.
    app.dependency_overrides[get_import_service] = lambda: imports[1]
    assert client.get("/api/ingestion/imports").json() == baseline


@pytest.mark.parametrize("raw", ["", "{}", "[]", '{"roots":{},"roots":{}}', "x" * 65537])
def test_invalid_profile_is_sanitized_before_worker_database(tmp_path, monkeypatch, capsys, raw):
    from app.services.dataset_storage_runtime import runtime_import_service
    from scripts.run_dataset_import_worker import main
    import sqlalchemy
    root = tmp_path / "imports"
    staging = tmp_path / "attempts"
    root.mkdir(mode=0o700)
    staging.mkdir(mode=0o700)
    profile = tmp_path / "profile.json"
    profile.write_text(raw)
    monkeypatch.setenv("FAMA_IMPORT_STORAGE_PROFILE", str(profile) if raw else "")
    calls = []
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **kw: calls.append(a))
    with pytest.raises(HTTPException) as error:
        runtime_import_service(root, attempt_root=staging)
    assert error.value.status_code == 503
    assert error.value.detail == "El presupuesto físico requiere un perfil activo y compatible."
    with pytest.raises(SystemExit) as error:
        main(["--database-url", "sqlite://", "--import-root", str(root),
              "--staging-root", str(staging), "--local-only", "--execution-seconds", "900"])
    assert error.value.code == 1
    assert calls == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Import worker unavailable; preserve state and inspect the operation manual.\n"
