"""Asistente por HTTP y autorización mediante la CLI pública del operador."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from app.configuration import InstallationStore, load_configuration
from app.entrypoint import create_app
from tests.test_preparacion_roles_pruebas import isolated_server, connection
from tests.test_permisos_tablas_pruebas import migrated_database, grant


ORIGIN = "http://localhost:3000"


@pytest.fixture
def node(tmp_path, migrated_database, monkeypatch):
    from google.auth.credentials import AnonymousCredentials
    _, migrator, runtime = migrated_database
    grant(migrator)
    values = {"FAMA_WEB_ORIGIN": ORIGIN, "FAMA_ALLOW_INSECURE_LOOPBACK": "1",
              "GOOGLE_CLOUD_PROJECT": "synthetic-project", "GCS_BUCKET_NAME": "synthetic-bucket"}
    for key, value in {"DATABASE_URL": runtime.render_as_string(hide_password=False),
                       "JWT_SECRET_KEY": "jwt-synthetic-" * 5, "FAMA_RATE_LIMIT_KEY": "quota-synthetic-" * 5}.items():
        path = tmp_path / key.lower()
        path.write_text(value, encoding="utf-8")
        values[key + "_FILE"] = str(path)
    InstallationStore(tmp_path).save(values)
    monkeypatch.setattr("google.auth.default", lambda **kwargs: (AnonymousCredentials(), "synthetic-project"))
    monkeypatch.setattr("google.cloud.storage.Client", lambda **kwargs: nullcontext(
        SimpleNamespace(list_blobs=lambda *args, **kwargs: iter(()))))
    token = authorize(tmp_path)
    return tmp_path, {"X-FAMA-Setup-Code": token, "Origin": ORIGIN}, runtime


def authorize(directory):
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP"}}
    result = subprocess.run(
        [sys.executable, "-m", "app.node", "--config-dir", str(directory), "setup-code", "--web-origin", ORIGIN],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["authorization_token"]


def test_only_operator_code_opens_private_configuration(tmp_path):
    InstallationStore(tmp_path).save({"FAMA_WEB_ORIGIN": ORIGIN})
    token = authorize(tmp_path)
    configuration = load_configuration({"FAMA_CONFIG_DIR": str(tmp_path)})
    with TestClient(create_app(configuration)) as client:
        assert client.get("/api/installation/status").json() == {"status": "required"}
        response = client.get("/api/installation/state")
        assert response.status_code == 401
        accepted = client.get("/api/installation/state", headers={"X-FAMA-Setup-Code": token})
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "required"
        assert token not in accepted.text
        assert accepted.headers["cache-control"] == "no-store"
        assert client.get("/api/auth/me").status_code == 503


def test_authorization_expires_rotates_and_rejects_another_origin(tmp_path, monkeypatch):
    InstallationStore(tmp_path).save({"FAMA_WEB_ORIGIN": ORIGIN})
    old = authorize(tmp_path)
    token = authorize(tmp_path)
    assert token not in (tmp_path / "authorization.json").read_text()
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(tmp_path)}))) as client:
        assert client.get("/api/installation/state", headers={"X-FAMA-Setup-Code": old}).status_code == 401
        headers = {"X-FAMA-Setup-Code": token, "Origin": "https://otro.test"}
        assert client.get("/api/installation/state", headers=headers).status_code == 403
        monkeypatch.setattr(time, "time", lambda: 9999999999)
        assert client.get("/api/installation/state", headers={"X-FAMA-Setup-Code": token}).status_code == 401


def test_operator_saves_public_resources_and_keeps_secrets_on_server(tmp_path):
    InstallationStore(tmp_path).save({"FAMA_WEB_ORIGIN": ORIGIN})
    token = authorize(tmp_path)
    headers = {"X-FAMA-Setup-Code": token, "Origin": ORIGIN}
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(tmp_path)}))) as client:
        assert client.post("/api/installation/configuration", json={}).status_code == 401
        password = "PrivateSQL:@/%2026"
        response = client.post("/api/installation/configuration", headers=headers, json={
            "project_id": "synthetic-project", "bucket_name": "synthetic-bucket",
            "database": "synthetic_db", "database_user": "synthetic_app", "database_password": password,
        })
        assert response.status_code == 200
        assert response.json()["code"] == "installation_configuration_saved"
        state = client.get("/api/installation/state", headers=headers).json()
        assert state["configuration"]["database"] == "synthetic_db"
        assert state["configuration"]["database_user"] == "synthetic_app"
        assert state["configuration"]["password_saved"] is True
        assert password not in json.dumps(state) + response.text
        from sqlalchemy.engine import make_url
        current = load_configuration({"FAMA_CONFIG_DIR": str(tmp_path)})
        assert make_url(current.database_url).password == password
        assert current.missing_requirements == ()
        assert current.installation_status == "required"
        assert password not in (tmp_path / "installation.json").read_text()


def test_checks_real_runtime_database_and_storage_independently(node, monkeypatch):
    directory, headers, _ = node
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(directory)}))) as client:
        response = client.post("/api/installation/check", headers=headers, json={})
        assert response.status_code == 200
        assert response.json()["ready"] is True, json.dumps(response.json(), sort_keys=True)
        assert response.json()["checks"]["schema"] == {"ok": True, "code": "schema_current", "revision": "0004_integration"}
        from google.api_core.exceptions import Forbidden
        def deny(*args, **kwargs):
            raise Forbidden("PrivateStorageDetailsMustNotAppear")
        monkeypatch.setattr("google.cloud.storage.Client", deny)
        failed = client.post("/api/installation/check", headers=headers, json={})
        assert failed.json()["ready"] is False
        assert failed.json()["checks"]["database"]["ok"] is True
        assert failed.json()["checks"]["storage"]["code"] == "storage_forbidden"
        assert "PrivateStorageDetailsMustNotAppear" not in failed.text


ADMIN = {"email": "first@example.test", "name": "Primera administradora", "password": "Administrator-Password-2026"}


def authenticated_admin(runtime, directory, monkeypatch):
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import get_db
    from app.routes.auth import router as auth_router
    from app.routes.users import router as users_router
    from app.services import auth
    c = load_configuration({"FAMA_CONFIG_DIR": str(directory)})
    for key in ("FAMA_WEB_ORIGIN", "FAMA_ALLOW_INSECURE_LOOPBACK", "FAMA_RATE_LIMIT_KEY"):
        monkeypatch.setenv(key, c.values[key])
    monkeypatch.setattr(auth, "SECRET_KEY", c.values["JWT_SECRET_KEY"])
    engine = create_engine(runtime)
    sessions = sessionmaker(bind=engine)
    def database():
        with sessions() as session:
            yield session
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router)
    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
            response = client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
            assert response.status_code == 200
            assert response.json()["user"]["rol"] == "administrador"
            users = client.get("/api/users")
            assert users.status_code == 200
            assert len(users.json()["users"]) == 1
    finally:
        engine.dispose()


def test_finalize_creates_login_capable_admin_and_permanently_closes_setup(node, monkeypatch):
    directory, headers, runtime = node
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(directory)}))) as client:
        response = client.post("/api/installation/complete", headers=headers, json=ADMIN)
        assert response.status_code == 200
        assert response.json() == {"code": "installation_completed", "restart_required": True}
        assert ADMIN["password"] not in response.text
        assert client.get("/api/installation/status").json() == {"status": "completed"}
        assert client.post("/api/installation/complete", headers=headers, json=ADMIN).status_code == 410
        assert client.get("/api/installation/state", headers=headers).status_code == 410
    authenticated_admin(runtime, directory, monkeypatch)


def test_restart_resumes_sql_commit_when_final_local_write_failed(node, monkeypatch):
    directory, headers, runtime = node
    configuration = load_configuration({"FAMA_CONFIG_DIR": str(directory)})
    real_replace = os.replace
    def disk_failure(source, target):
        if Path(target) == directory / "installation.json":
            raise OSError("SensitiveDiskDetailsMustNotAppear")
        return real_replace(source, target)
    with TestClient(create_app(configuration)) as client:
        with monkeypatch.context() as fault:
            fault.setattr(os, "replace", disk_failure)
            failed = client.post("/api/installation/complete", headers=headers, json=ADMIN)
        assert failed.status_code == 503
        assert "SensitiveDiskDetailsMustNotAppear" not in failed.text
        pending = client.get("/api/installation/state", headers=headers)
        assert pending.json()["resume_pending"] is True
        assert "password_hash" not in pending.text
        assert client.post("/api/installation/configuration", headers=headers,
                           json={"bucket_name": "another-bucket"}).status_code == 409
    with TestClient(create_app(configuration)) as restarted:
        resumed = restarted.post("/api/installation/complete", headers=headers, json={})
        assert resumed.status_code == 200
        assert resumed.json()["code"] == "installation_completed"
    authenticated_admin(runtime, directory, monkeypatch)


def test_configuration_cannot_change_while_finalization_is_checking_services(node, monkeypatch):
    directory, headers, _ = node
    entered, release = Event(), Event()
    def delayed_list(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return iter(())
    monkeypatch.setattr("google.cloud.storage.Client", lambda **kwargs: nullcontext(SimpleNamespace(list_blobs=delayed_list)))
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(directory)}))) as client:
        with ThreadPoolExecutor(max_workers=1) as executor:
            request = executor.submit(client.post, "/api/installation/complete", headers=headers, json=ADMIN)
            try:
                assert entered.wait(5)
                conflict = client.post("/api/installation/configuration", headers=headers, json={"bucket_name": "another-bucket"})
                assert conflict.status_code == 409
                assert conflict.json()["code"] == "installation_busy"
                code_request = subprocess.run(
                    [sys.executable, "-m", "app.node", "--config-dir", str(directory), "setup-code"],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
                assert code_request.returncode == 1
                assert json.loads(code_request.stdout) == {"code": "installation_busy"}
            finally:
                release.set()
                assert request.result(timeout=20).status_code == 200


@pytest.mark.parametrize("key,value", [
    ("JWT_SECRET_KEY", "fama_bioacoustic_secret_key_mlops_2026"),
    ("FAMA_SESSION_IDLE_SECONDS", "9999999"),
    ("FAMA_ACCESS_LIMITS_JSON", '{"unknown":{}}'),
    ("FAMA_WEB_ORIGIN", "http://outside.test"),
])
def test_invalid_access_configuration_blocks_completion(node, key, value):
    directory, headers, _ = node
    public = InstallationStore(directory).read()["values"]
    if key == "JWT_SECRET_KEY":
        Path(public[key + "_FILE"]).write_text(value, encoding="utf-8")
    else:
        InstallationStore(directory).save(dict(public, **{key: value}))
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(directory)}))) as client:
        result = client.post("/api/installation/check", headers=headers, json={})
        assert result.json()["checks"]["configuration"]["ok"] is False
        assert client.post("/api/installation/complete", headers=headers, json=ADMIN).status_code == 409
        assert client.get("/api/installation/status").json() == {"status": "required"}


def test_another_node_cannot_adopt_initialized_database(node, tmp_path):
    directory, headers, _ = node
    public = InstallationStore(directory).read()["values"]
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(directory)}))) as client:
        assert client.post("/api/installation/complete", headers=headers, json=ADMIN).status_code == 200
    other = tmp_path / "another-node"
    InstallationStore(other).save(public)
    token = authorize(other)
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(other)}))) as client:
        result = client.post("/api/installation/complete", headers={"X-FAMA-Setup-Code": token, "Origin": ORIGIN},
                             json=dict(ADMIN, email="another@example.test"))
        assert result.status_code == 409
        assert result.json()["code"] == "database_already_initialized"
        assert client.get("/api/installation/state", headers={"X-FAMA-Setup-Code": token}).json()["resume_pending"] is False


def test_failed_audit_write_rolls_back_account_and_can_resume(node, migrated_database, monkeypatch):
    directory, headers, runtime = node
    _, migrator, _ = migrated_database
    with connection(migrator) as db, db.cursor() as cursor:
        cursor.execute("""CREATE FUNCTION public.reject_initial_audit() RETURNS trigger LANGUAGE plpgsql
            AS $$ BEGIN RAISE EXCEPTION 'synthetic audit failure'; END; $$;
            CREATE TRIGGER reject_initial_audit BEFORE INSERT ON public.evento_seguridad
            FOR EACH ROW EXECUTE FUNCTION public.reject_initial_audit();""")
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(directory)}))) as client:
        failed = client.post("/api/installation/complete", headers=headers, json=ADMIN)
        assert failed.status_code == 503
        assert client.get("/api/installation/state", headers=headers).json()["resume_pending"] is True
        with connection(migrator) as db, db.cursor() as cursor:
            cursor.execute("DROP FUNCTION public.reject_initial_audit() CASCADE")
        resumed = client.post("/api/installation/complete", headers=headers, json={})
        assert resumed.status_code == 200
    authenticated_admin(runtime, directory, monkeypatch)


def test_invalid_requests_never_echo_secrets(tmp_path):
    InstallationStore(tmp_path).save({"FAMA_WEB_ORIGIN": ORIGIN})
    headers = {"X-FAMA-Setup-Code": authorize(tmp_path), "Origin": ORIGIN}
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(tmp_path)}))) as client:
        secret = "MustNeverBeEchoed"
        invalid = client.post("/api/installation/configuration", headers=headers, json={"database_password": [secret]})
        assert invalid.status_code == 422 and secret not in invalid.text
        too_large = client.post("/api/installation/configuration", headers=headers,
                                json={"database_password": secret * 2000})
        assert too_large.status_code == 413 and secret not in too_large.text
        denied = client.post("/api/installation/configuration", headers={"X-FAMA-Setup-Code": headers["X-FAMA-Setup-Code"]}, json={"bucket_name": "bucket-test"})
        assert denied.status_code == 403


def test_completed_record_never_reopens_even_without_database(tmp_path):
    store = InstallationStore(tmp_path)
    store.save({"FAMA_WEB_ORIGIN": ORIGIN})
    token = authorize(tmp_path)
    configuration = load_configuration({"FAMA_CONFIG_DIR": str(tmp_path)})
    store.save({"FAMA_WEB_ORIGIN": ORIGIN}, completed=True)
    with TestClient(create_app(configuration)) as client:
        assert client.get("/api/installation/status").json() == {"status": "completed"}
        assert client.get("/api/installation/state", headers={"X-FAMA-Setup-Code": token}).status_code == 410
    result = subprocess.run([sys.executable, "-m", "app.node", "--config-dir", str(tmp_path), "setup-code"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"code": "installation_closed"}


def test_checks_require_daily_database_permissions_before_creating_account(node, migrated_database):
    directory, headers, _ = node
    _, migrator, _ = migrated_database
    with connection(migrator) as db, db.cursor() as cursor:
        cursor.execute("REVOKE INSERT ON public.usuario FROM fama_app")
    with TestClient(create_app(load_configuration({"FAMA_CONFIG_DIR": str(directory)}))) as client:
        checked = client.post("/api/installation/check", headers=headers, json={})
        assert checked.json()["checks"]["permissions"] == {"ok": False, "code": "database_runtime_permissions_invalid"}
        assert checked.json()["ready"] is False
        assert client.post("/api/installation/complete", headers=headers, json=ADMIN).status_code == 409
        assert client.get("/api/installation/state", headers=headers).json()["resume_pending"] is False
