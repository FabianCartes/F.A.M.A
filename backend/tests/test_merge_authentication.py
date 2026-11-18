"""Joined access through actual HTTP sessions; no remote services."""
import pytest
from tests.test_web_sessions import login, ORIGIN, PASSWORD


@pytest.fixture
def web(monkeypatch):
    """Web sessions over an Alembic-migrated schema, which the import queue requires."""
    import os
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.configuration import activate_configuration, get_configuration, load_configuration
    from app.database import get_db
    from app.models.user import Usuario
    from app.routes.auth import router
    from app.services.auth import hash_password
    from tests.http_security import configure_access_limits
    from tests.schema_support import migrated_engine

    configure_access_limits(monkeypatch)
    monkeypatch.setenv("FAMA_WEB_ORIGIN", ORIGIN)
    previous_configuration = get_configuration()
    activate_configuration(load_configuration(dict(os.environ)))
    engine = migrated_engine()
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        for index, role in enumerate(("administrador", "investigador"), 1):
            db.add(Usuario(id=index, email=f"{role}@example.test", password_hash=hash_password(PASSWORD),
                           nombre_completo=role, rol=role, activo=True))
        db.commit()

    def isolated_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = isolated_db
    try:
        with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
            yield client, sessions
    finally:
        engine.dispose()
        activate_configuration(previous_configuration)


def test_zip_uses_revocable_cookie_and_checks_mutation_origin(web, tmp_path):
    from app.routes.dataset_imports import router, get_import_service
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_zip import ImportLimits
    client, sessions = web
    client.app.include_router(router)
    client.app.dependency_overrides[get_import_service] = lambda: DatasetImports(tmp_path/"imports", limits=ImportLimits(free_bytes=1))
    base = "/api/ingestion/imports"
    assert client.get(base+"/limits").status_code == 401
    assert login(client).status_code == 200
    assert client.get(base+"/access").json()["authenticated"] is True
    assert client.get(base+"/limits").status_code == 200
    rejected = client.post(base, headers={"Origin":"https://foreign.test"}, json={"request_key":"external", "name":"Private"})
    assert rejected.status_code == 403
    created = client.post(base, headers={"Origin": ORIGIN}, json={"request_key":"owned", "name":"Private"})
    assert created.status_code == 200, created.text
    assert client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 204
    assert client.get(base+"/limits").status_code == 401


def test_unsupported_zip_platform_stays_explicit_without_loading_posix_services():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.import_capability import zip_router
    app = FastAPI()
    app.include_router(zip_router(supported=False))
    client = TestClient(app)
    status = client.get("/api/ingestion/imports/access")
    assert status.status_code == 200
    assert status.json()["available"] is False
    assert client.post("/api/ingestion/imports").status_code == 503
