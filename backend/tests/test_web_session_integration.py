"""Canonical session reconciliation through public HTTP, synthetic state only."""
import pytest

from tests.test_api_auth import client, test_db
from tests.test_dataset_import_api import imports
from tests.http_security import cookie_security

ORIGIN = "http://localhost:3000"
PASSWORD = "SyntheticPass123!"


@pytest.fixture
def web(test_db, monkeypatch, client):
    from app.models.user import Usuario
    from app.services import auth
    monkeypatch.setenv("FAMA_WEB_ORIGIN", ORIGIN)
    monkeypatch.setenv("FAMA_ALLOW_INSECURE_LOOPBACK", "1")
    client.headers["Origin"] = ORIGIN
    for index in (1, 2):
        test_db.add(Usuario(id=index, email=f"user{index}@example.test",
                           password_hash=auth.hash_password(PASSWORD),
                           nombre_completo=f"User {index}", rol="investigador", activo=True))
    test_db.commit()


def login(client, index=1):
    return client.post("/api/auth/login", headers={"Origin": ORIGIN},
                       json={"email": f"user{index}@example.test", "password": PASSWORD})


def test_canonical_login_confirms_cookie_identity_without_token(client, web):
    response = login(client)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"user"}
    assert response.json()["user"]["id"] == 1
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert client.get("/api/auth/me").json()["id"] == 1
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401
    for path in ("login", "me", "logout"):
        method = client.get if path == "me" else client.post
        assert method("/api/auth/web/" + path).status_code == 404


def test_logout_revokes_server_session_not_just_browser_cookie(client, web):
    assert login(client).status_code == 200
    original = client.cookies.get("fama_session_dev")
    result = client.post("/api/auth/logout", headers={"Origin": ORIGIN})
    assert result.status_code == 204, result.text
    assert result.content == b""
    assert result.headers["cache-control"] == "no-store"
    client.cookies.set("fama_session_dev", original)
    assert client.get("/api/auth/me").status_code == 401


def test_cookie_authenticates_imported_history_but_preserves_legacy_response(client, web):
    # Use the existing business fixture for legacy resource authorization only.
    from tests.http_security import administrator_http
    from app.main import app
    from fastapi.testclient import TestClient
    from app.database import get_db
    app.dependency_overrides[get_db] = client.app.dependency_overrides[get_db]
    try:
        business = TestClient(app)
        with administrator_http(app):
            before = business.get("/api/training/history").json()
            assert login(business).status_code == 200
            response = business.get("/api/training/history?include_imported=true")
            assert response.status_code == 200, response.text
            assert response.json() == before
            assert response.headers["cache-control"] == "no-store"
            assert business.get("/api/training/history", headers={"Authorization": "Bearer invalid"}).json() == before
    finally:
        business.close()
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("authorization", ["Bearer invalid", "Bearer foreign", "Basic ignored"])
def test_authorization_header_cannot_switch_cookie_identity(client, web, authorization):
    assert login(client).status_code == 200
    response = client.get("/api/auth/me", headers={"Authorization": authorization})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == 1
    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Authorization": authorization}).status_code == 401


def test_cookie_requires_trusted_origin_even_with_authorization(client, web):
    assert login(client).status_code == 200
    headers = {"Authorization": "Bearer ignored"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    headers["Origin"] = "https://foreign.example.test"
    assert client.get("/api/auth/me", headers=headers).status_code == 403


def test_import_cookie_keeps_exact_owner_even_for_two_administrators(imports, web, monkeypatch):
    from app.routes.auth import router
    from app.routes.dataset_imports import get_import_user
    from app.models.user import Usuario
    from app.services.auth import hash_password
    http, service, application, sessions = imports
    application.include_router(router)
    application.dependency_overrides.pop(get_import_user)
    monkeypatch.setenv("FAMA_ENV", "development")
    monkeypatch.setenv("FAMA_IMPORT_DEV_MODE", "1")
    from fastapi.testclient import TestClient
    with sessions() as db:
        for index in (1, 2):
            db.add(Usuario(id=index, email=f"user{index}@example.test", password_hash=hash_password(PASSWORD),
                           nombre_completo=f"User {index}", rol="administrador", activo=True))
        db.commit()
    with TestClient(application, client=("127.0.0.1", 50000)) as local:
        assert login(local).status_code == 200
        result = local.post("/api/ingestion/imports", headers={"Origin": ORIGIN},
                            json={"request_key": "cookie-owner", "name": "Private collection"})
        assert result.status_code == 200, result.text
        job = result.json()
        assert local.get(f"/api/ingestion/imports/{job['id']}").status_code == 200
        assert login(local, 2).status_code == 200
        denied = local.get(f"/api/ingestion/imports/{job['id']}")
        assert denied.status_code == 404, denied.text
        assert local.get("/api/ingestion/imports/datasets").json()["datasets"] == []
        assert login(local, 1).status_code == 200
        assert local.get(f"/api/ingestion/imports/{job['id']}").json() == job


def test_session_schema_requires_explicit_idempotent_migration(client, web, test_db):
    from app.models.web_session import SesionWeb
    from app.models.access_quota import CuotaAcceso
    from app.models.security_audit import EventoSeguridad
    engine = test_db.get_bind()
    for table in (SesionWeb.__table__, CuotaAcceso.__table__, EventoSeguridad.__table__):
        table.drop(engine)
    assert login(client).status_code == 503
    from scripts.migrate_web_sessions import migrate_web_sessions
    with pytest.raises(RuntimeError, match="writers"):
        migrate_web_sessions(engine)
    assert login(client).status_code == 503
    migrate_web_sessions(engine, writers_stopped=True)
    migrate_web_sessions(engine, writers_stopped=True)
    assert login(client).status_code == 200
    assert client.get("/api/auth/me").json()["id"] == 1


def test_incompatible_session_schema_fails_before_creating_cookie(client, web, test_db):
    from app.models.web_session import SesionWeb
    from sqlalchemy import text
    engine = test_db.get_bind()
    SesionWeb.__table__.drop(engine)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE sesion_web (token_hash VARCHAR(64) PRIMARY KEY NOT NULL, id_usuario INTEGER NOT NULL, expira_en BIGINT NOT NULL, inactiva_en BIGINT NOT NULL)"))
    response = login(client)
    assert response.status_code == 503, response.text
    assert "set-cookie" not in response.headers
    from scripts.migrate_web_sessions import migrate_web_sessions
    with pytest.raises(RuntimeError, match="Incompatible"):
        migrate_web_sessions(engine, writers_stopped=True)
    assert login(client).status_code == 503


@pytest.mark.parametrize("kind", ["idle", "absolute"])
def test_session_expiration_boundaries_are_enforced(client, web, monkeypatch, kind):
    from app.services import web_sessions
    clock = [1000]
    monkeypatch.setattr(web_sessions.time, "time", lambda: clock[0])
    monkeypatch.setenv("FAMA_SESSION_MAX_AGE_SECONDS", "10")
    monkeypatch.setenv("FAMA_SESSION_IDLE_SECONDS", "4")
    assert login(client).status_code == 200
    if kind == "idle":
        clock[0] = 1004
    else:
        for now in (1003, 1006, 1009):
            clock[0] = now
            assert client.get("/api/auth/me").status_code == 200
        clock[0] = 1010
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Sesión requerida o expirada."}


def test_suspended_user_cannot_login_or_use_existing_session(client, web, test_db):
    from app.models.user import Usuario
    assert login(client).status_code == 200
    test_db.get(Usuario, 1).activo = False
    test_db.commit()
    assert client.get("/api/auth/me").status_code == 401
    response = login(client)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_cross_origin_writes_do_not_revoke_or_replace_session(client, web):
    assert login(client).status_code == 200
    original = client.cookies.get("fama_session_dev")
    for headers in ({"Origin": "null"}, {"Origin": "https://foreign.example.test"}):
        response = client.post("/api/auth/login", headers=headers,
                               json={"email": "user2@example.test", "password": PASSWORD})
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert client.post("/api/auth/logout", headers=headers).status_code == 403
        assert client.cookies.get("fama_session_dev") == original
        assert client.get("/api/auth/me").json()["id"] == 1


def test_login_rotation_revokes_previous_browser_session(client, web):
    assert login(client).status_code == 200
    original = client.cookies.get("fama_session_dev")
    assert login(client, 2).status_code == 200
    assert client.get("/api/auth/me").json()["id"] == 2
    client.cookies.clear()
    client.cookies.set("fama_session_dev", original)
    assert client.get("/api/auth/me").status_code == 401


def test_web_login_limits_and_no_store_errors(client, web):
    for _ in range(5):
        response = client.post("/api/auth/login", headers={"Origin": ORIGIN},
                               json={"email": "user1@example.test", "password": "wrong"})
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
    response = login(client)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/auth/me").status_code == 401
