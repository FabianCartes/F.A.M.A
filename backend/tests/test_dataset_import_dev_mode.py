"""Local development admission through public HTTP, never an ambient database."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.test_dataset_import_api import prepare, confirm

BASE = "/api/ingestion/imports"


@pytest.fixture
def local_imports(tmp_path, monkeypatch):
    from app.database import Base, get_db
    from app.routes.auth import router as auth_router
    from app.routes.dataset_imports import router, get_import_service
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_zip import ImportLimits
    from app.services import dataset_import_execution
    from app.services import auth
    from app.services.dataset_zip import validate_zip
    # This guard-compatible authorization fixture is not containment evidence.
    monkeypatch.setattr(dataset_import_execution, "validate_zip", validate_zip)
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-import-isolation-key-2026-only-for-tests")

    monkeypatch.delenv("FAMA_ENV", raising=False)
    monkeypatch.delenv("FAMA_IMPORT_DEV_MODE", raising=False)
    monkeypatch.delenv("FAMA_IMPORT_DEV_FRONTEND_IP", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    from scripts.migrate_dataset_import_jobs import migrate_jobs
    migrate_jobs(engine, writers_stopped=True)
    sessions = sessionmaker(bind=engine)
    service = DatasetImports(tmp_path / "managed", limits=ImportLimits(free_bytes=1))
    app = FastAPI()
    app.include_router(router)
    app.include_router(auth_router)

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_import_service] = lambda: service
    from app.services.dataset_import_execution import ImportExecution
    from app.services.dataset_import_jobs import ImportJobQueue
    service._initialize()
    root = service.root / "attempts"
    root.mkdir(mode=0o700)
    app.state.test_sessions = sessions
    app.state.import_execution = ImportExecution(ImportJobQueue(sessions), service, root)
    with TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False) as client:
        yield client, app
    engine.dispose()


def enable_local(monkeypatch):
    monkeypatch.setenv("FAMA_ENV", "development")
    monkeypatch.setenv("FAMA_IMPORT_DEV_MODE", "1")


def test_docker_frontend_imports_and_returns_to_normal(local_imports, tmp_path, monkeypatch):
    _, app = local_imports
    enable_local(monkeypatch)
    monkeypatch.setenv("FAMA_IMPORT_DEV_FRONTEND_IP", "172.30.253.10")
    with TestClient(app, client=("172.30.253.10", 50000)) as frontend:
        assert frontend.get(BASE + "/access").json() == {"development_mode": True, "available": True, "authenticated": False}
        job = prepare(frontend, tmp_path)
        result = confirm(frontend, job)
        assert result.status_code == 200, result.text
        assert len(frontend.get(BASE + "/datasets").json()["datasets"]) == 1
        assert frontend.get(BASE, headers={"Authorization": "Bearer invalid"}).status_code == 401
        monkeypatch.delenv("FAMA_IMPORT_DEV_MODE")
        assert frontend.get(BASE + "/access").json() == {"development_mode": False, "available": True, "authenticated": False}
        assert frontend.get(BASE).status_code == 401


@pytest.mark.parametrize("peer", ["172.30.253.11", "172.30.253.1", "192.168.1.10"])
def test_only_exact_frontend_peer_is_admitted(local_imports, monkeypatch, peer):
    _, app = local_imports
    enable_local(monkeypatch)
    monkeypatch.setenv("FAMA_IMPORT_DEV_FRONTEND_IP", "172.30.253.10")
    with TestClient(app, client=(peer, 50000)) as other:
        headers = {"X-Forwarded-For": "172.30.253.10", "Forwarded": "for=172.30.253.10"}
        assert other.get(BASE, headers=headers).status_code == 403
        assert other.post(BASE, json={"request_key": "denied", "name": "Denied"}, headers=headers).status_code == 403


@pytest.mark.parametrize("configured", ["172.30.253.0/24", "frontend", "", "invalid"])
def test_frontend_configuration_never_accepts_ranges_or_names(local_imports, monkeypatch, configured):
    _, app = local_imports
    enable_local(monkeypatch)
    monkeypatch.setenv("FAMA_IMPORT_DEV_FRONTEND_IP", configured)
    with TestClient(app, client=("172.30.253.10", 50000)) as other:
        assert other.get(BASE).status_code == 403


def test_explicit_local_mode_imports_without_login_and_preserves_auth_routes(local_imports, tmp_path, monkeypatch):
    client, _ = local_imports
    enable_local(monkeypatch)
    assert client.get(BASE + "/access").json() == {"development_mode": True, "available": True, "authenticated": False}
    assert client.get(BASE + "/limits").status_code == 200
    assert client.get(BASE + "/example.zip").status_code == 200
    job = prepare(client, tmp_path)
    imported = confirm(client, job)
    assert imported.status_code == 200, imported.text
    dataset = imported.json()["dataset_id"]
    files = client.get(f"{BASE}/datasets/{dataset}/files").json()["files"]
    assert client.get(f"{BASE}/datasets/{dataset}/files/{files[0]['sha256']}").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    monkeypatch.delenv("FAMA_IMPORT_DEV_MODE")
    assert client.get(BASE).status_code == 401


@pytest.mark.parametrize("environment", [None, "development", "production"])
def test_auth_is_required_by_default(local_imports, monkeypatch, environment):
    client, _ = local_imports
    if environment:
        monkeypatch.setenv("FAMA_ENV", environment)
    assert client.get(BASE + "/access").json() == {"development_mode": False, "available": True, "authenticated": False}
    assert client.get(BASE).status_code == 401
    assert client.get(BASE + "/limits").status_code == 401
    assert client.post(BASE, json={"request_key": "denied", "name": "No dataset"}).status_code == 401


@pytest.mark.parametrize("environment", [None, "production", "staging"])
def test_opt_in_outside_development_fails_closed(local_imports, monkeypatch, environment):
    client, _ = local_imports
    monkeypatch.setenv("FAMA_IMPORT_DEV_MODE", "1")
    if environment:
        monkeypatch.setenv("FAMA_ENV", environment)
    assert client.get(BASE + "/access").status_code == 503
    assert client.get(BASE + "/limits").status_code == 503
    assert client.post(BASE, json={"request_key": "denied", "name": "No dataset"}).status_code == 503


def test_remote_peers_cannot_use_local_exception_or_spoof_forwarding(local_imports, monkeypatch):
    _, app = local_imports
    enable_local(monkeypatch)
    with TestClient(app, client=("192.0.2.10", 50000)) as remote:
        headers = {"X-Forwarded-For": "127.0.0.1", "Forwarded": "for=127.0.0.1", "Host": "localhost"}
        assert remote.get(BASE + "/access", headers=headers).status_code == 403
        assert remote.get(BASE, headers=headers).status_code == 403


@pytest.mark.parametrize("docker_peer", [False, True])
def test_local_and_authenticated_owners_remain_isolated(local_imports, tmp_path, monkeypatch, docker_peer):
    client, _ = local_imports
    if docker_peer:
        # TestClient's public transport configuration, not proxy-header rewriting.
        client = TestClient(local_imports[1], client=("172.30.253.10", 50000))
        monkeypatch.setenv("FAMA_IMPORT_DEV_FRONTEND_IP", "172.30.253.10")
    from app.services.auth import create_user
    from app.web_settings import settings
    origin = settings().origin
    with local_imports[1].state.test_sessions() as db:
        create_user(db, "synthetic@example.test", "synthetic-password", "Synthetic User")
    client.headers["Origin"] = origin
    login = client.post("/api/auth/login", json={"email":"synthetic@example.test", "password":"synthetic-password"})
    assert login.status_code == 200, login.text
    saved_cookies = dict(client.cookies)
    private_job = prepare(client, tmp_path, key="private")
    private_dataset = confirm(client, private_job).json()["dataset_id"]
    private_files = client.get(f"{BASE}/datasets/{private_dataset}/files").json()
    enable_local(monkeypatch)
    # A real cookie session retains its owner while the explicit local mode is enabled.
    assert len(client.get(BASE + "/datasets").json()["datasets"]) == 1
    client.cookies.clear()
    assert client.get(BASE).json()["imports"] == []
    assert client.get(BASE + "/datasets").json()["datasets"] == []
    for method, suffix, payload in [
        ("GET", f"/{private_job['id']}", None),
        ("PUT", f"/{private_job['id']}/archive", None),
        ("POST", f"/{private_job['id']}/preview", {"root": "", "request_key": "foreign"}),
        ("POST", f"/{private_job['id']}/confirm", {"preview_token": private_job["preview_token"], "request_key": "foreign"}),
        ("POST", f"/{private_job['id']}/cancel", {}),
        ("GET", f"/datasets/{private_dataset}/files", None),
        ("GET", f"/datasets/{private_dataset}/files/{private_files['files'][0]['sha256']}", None),
        ("POST", "", {"request_key": "foreign", "name": "Foreign", "target_id": private_dataset}),
    ]:
        headers = {"Content-Type": "application/zip"} if method == "PUT" else {}
        assert client.request(method, BASE + suffix, json=payload, headers=headers).status_code == 404
    local_job = prepare(client, tmp_path, key="local", sample=2)
    local_dataset = confirm(client, local_job).json()["dataset_id"]
    # Invalid credentials must not silently fall back to the anonymous identity.
    assert client.get(BASE, headers={"Authorization": "Bearer invalid"}).status_code == 401
    monkeypatch.delenv("FAMA_IMPORT_DEV_MODE")
    client.cookies.update(saved_cookies)
    assert client.get(f"{BASE}/datasets/{local_dataset}/files").status_code == 404
    assert client.get(f"{BASE}/datasets/{private_dataset}/files").json() == private_files
