"""Web session reconciliation through public HTTP interfaces, synthetic state only."""
import pytest

from tests.test_api_auth import client, test_db
from tests.test_dataset_import_api import imports

ORIGIN = "http://localhost:3000"
PASSWORD = "SyntheticPass123!"


@pytest.fixture
def web(test_db, monkeypatch):
    from app.models.user import Usuario
    from app.services import auth
    monkeypatch.setenv("FAMA_WEB_ORIGIN", ORIGIN)
    monkeypatch.setenv("FAMA_ALLOW_INSECURE_LOOPBACK", "1")
    monkeypatch.setenv("FAMA_RATE_LIMIT_KEY", "synthetic-rate-limit-key-for-isolated-tests-only")
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-bearer-signing-key-for-isolated-tests-only")
    for index in (1, 2):
        test_db.add(Usuario(id=index, email=f"user{index}@example.test",
                           password_hash=auth.hash_password(PASSWORD),
                           nombre_completo=f"User {index}", rol="investigador", activo=True))
    test_db.commit()


def login(client, index=1):
    return client.post("/api/auth/web/login", headers={"Origin": ORIGIN},
                       json={"email": f"user{index}@example.test", "password": PASSWORD})


def test_web_login_confirms_cookie_identity_without_replacing_bearer(client, web):
    response = login(client)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"user"}
    assert response.json()["user"]["id"] == 1
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert client.get("/api/auth/web/me").json()["id"] == 1
    bearer = client.post("/api/auth/login", json={"email": "user1@example.test", "password": PASSWORD})
    assert bearer.status_code == 200
    assert bearer.json()["token_type"] == "bearer"
    headers = {"Authorization": "Bearer " + bearer.json()["access_token"]}
    assert client.get("/api/auth/me", headers=headers).json()["id"] == 1
    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_server_session_not_just_browser_cookie(client, web):
    assert login(client).status_code == 200
    original = client.cookies.get("fama_session_dev")
    result = client.post("/api/auth/web/logout", headers={"Origin": ORIGIN})
    assert result.status_code == 204, result.text
    assert result.content == b""
    assert result.headers["cache-control"] == "no-store"
    client.cookies.set("fama_session_dev", original)
    assert client.get("/api/auth/web/me").status_code == 401


def test_cookie_authenticates_imported_history_but_legacy_stays_public(client, web):
    before = client.get("/api/training/history").json()
    assert login(client).status_code == 200
    response = client.get("/api/training/history?include_imported=true")
    assert response.status_code == 200, response.text
    assert response.json() == before
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/training/history", headers={"Authorization": "Bearer invalid"}).json() == before


@pytest.mark.parametrize("cookie_kind,bearer_kind", [("valid", "foreign"), ("invalid", "valid"), ("valid", "invalid")])
def test_dual_credentials_never_fall_back_or_switch_identity(client, web, cookie_kind, bearer_kind):
    from app.services.auth import create_access_token
    assert login(client).status_code == 200
    before = client.get("/api/training/history").json()
    if cookie_kind == "invalid":
        client.cookies.clear()
        client.cookies.set("fama_session_dev", "x" * 43)
    token = "invalid" if bearer_kind == "invalid" else create_access_token({"sub": "2" if bearer_kind == "foreign" else "1"})
    response = client.get("/api/training/history?include_imported=true", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401, response.text
    assert client.get("/api/training/history").json() == before


def test_matching_credentials_require_trusted_cookie_origin(client, web):
    from app.services.auth import create_access_token
    assert login(client).status_code == 200
    headers = {"Authorization": "Bearer " + create_access_token({"sub": "1"})}
    assert client.get("/api/training/history?include_imported=true", headers=headers).status_code == 200
    headers["Origin"] = "https://foreign.example.test"
    assert client.get("/api/training/history?include_imported=true", headers=headers).status_code == 403


def test_import_cookie_keeps_exact_owner_even_in_local_development(imports, web, monkeypatch):
    from app.routes.auth import router
    from app.routes.dataset_imports import get_import_user
    from app.models.user import Usuario
    from app.services.auth import hash_password
    http, service, application, sessions = imports
    application.include_router(router)
    application.dependency_overrides.pop(get_import_user)
    monkeypatch.setenv("FAMA_ENV", "development")
    monkeypatch.setenv("FAMA_IMPORT_DEV_MODE", "1")
    monkeypatch.setenv("FAMA_IMPORT_DEV_FRONTEND_IP", "127.0.0.1")
    # Use a verified local transport peer, never a forwarded header.
    from fastapi.testclient import TestClient
    local = TestClient(application, client=("127.0.0.1", 50000))
    with sessions() as db:
        for index in (1, 2):
            db.add(Usuario(id=index, email=f"user{index}@example.test", password_hash=hash_password(PASSWORD),
                           nombre_completo=f"User {index}", rol="administrador", activo=True))
        db.commit()
    try:
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
    finally:
        local.close()


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
    assert client.get("/api/auth/web/me").json()["id"] == 1


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
            assert client.get("/api/auth/web/me").status_code == 200
        clock[0] = 1010
    response = client.get("/api/auth/web/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Sesión requerida o expirada."}
    assert client.get("/api/training/history?include_imported=true").status_code == 401


def test_suspended_user_cannot_login_or_use_existing_session(client, web, test_db):
    from app.models.user import Usuario
    assert login(client).status_code == 200
    test_db.get(Usuario, 1).activo = False
    test_db.commit()
    assert client.get("/api/auth/web/me").status_code == 401
    assert client.get("/api/training/history?include_imported=true").status_code == 401
    response = login(client)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_cross_origin_writes_do_not_revoke_or_replace_session(client, web):
    assert login(client).status_code == 200
    original = client.cookies.get("fama_session_dev")
    for headers in ({}, {"Origin": "https://foreign.example.test"}):
        response = client.post("/api/auth/web/login", headers=headers,
                               json={"email": "user2@example.test", "password": PASSWORD})
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert client.post("/api/auth/web/logout", headers=headers).status_code == 403
        assert client.cookies.get("fama_session_dev") == original
        assert client.get("/api/auth/web/me").json()["id"] == 1


def test_login_rotation_revokes_previous_browser_session(client, web):
    assert login(client).status_code == 200
    original = client.cookies.get("fama_session_dev")
    assert login(client, 2).status_code == 200
    assert client.get("/api/auth/web/me").json()["id"] == 2
    client.cookies.clear()
    client.cookies.set("fama_session_dev", original)
    assert client.get("/api/auth/web/me").status_code == 401


def test_web_login_limits_and_no_store_errors(client, web):
    for _ in range(5):
        response = client.post("/api/auth/web/login", headers={"Origin": ORIGIN},
                               json={"email": "user1@example.test", "password": "wrong"})
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
    response = login(client)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/auth/web/me").status_code == 401
