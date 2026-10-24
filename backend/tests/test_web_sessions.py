"""Web authentication contracts; no production lifespan, credentials or assets."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.user import Usuario
from app.routes.auth import router
from app.services.auth import hash_password
from app.services import web_sessions
from tests.http_security import configure_access_limits


ORIGIN = "https://fama.example.test"
PASSWORD = "SyntheticPassword2026!"


@pytest.fixture
def web(monkeypatch):
    configure_access_limits(monkeypatch)
    monkeypatch.setenv("FAMA_WEB_ORIGIN", ORIGIN)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
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
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        yield client, sessions
    engine.dispose()


def login(client, role="investigador"):
    return client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
        "email": f"{role}@example.test", "password": PASSWORD,
    })


def test_login_uses_opaque_secure_cookie_not_bearer_token(web):
    client, _ = web
    response = login(client)
    assert response.status_code == 200
    assert set(response.json()) == {"user"}
    cookie = response.headers["set-cookie"]
    assert "__Host-fama_session=" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert "Path=/" in cookie and "Domain=" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/auth/me").json()["email"] == "investigador@example.test"


def test_only_current_administrator_can_create_accounts(web):
    client, sessions = web
    payload = {"email": "new@example.test", "password": PASSWORD,
               "nombre_completo": "New researcher", "rol": "administrador"}
    def register():
        return client.post("/api/auth/register", headers={"Origin": ORIGIN}, json=payload)

    assert register().status_code == 401
    assert login(client).status_code == 200
    assert register().status_code == 403
    assert login(client, "administrador").status_code == 200
    assert register().status_code == 201
    # Roles are read from the database, never trusted from a stale cookie.
    with sessions() as db:
        db.get(Usuario, 1).rol = "investigador"
        db.commit()
    payload["email"] = "another@example.test"
    assert register().status_code == 403


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example.test", ORIGIN + ".evil.test"])
def test_login_requires_exact_trusted_origin(web, origin):
    client, _ = web
    headers = {} if origin is None else {"Origin": origin}
    response = client.post("/api/auth/login", headers=headers, json={
        "email": "investigador@example.test", "password": PASSWORD,
    })
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


def test_registration_rejects_cross_origin_even_with_valid_session(web):
    client, _ = web
    assert login(client, "administrador").status_code == 200
    response = client.post("/api/auth/register", headers={"Origin": "https://evil.example.test"}, json={
        "email": "csrf@example.test", "password": PASSWORD, "nombre_completo": "CSRF account",
    })
    assert response.status_code == 403


def test_logout_revokes_stolen_cookie_and_requires_trusted_origin(web):
    client, _ = web
    assert login(client).status_code == 200
    stolen = client.cookies.get("__Host-fama_session")
    assert client.post("/api/auth/logout").status_code == 403
    assert client.get("/api/auth/me").status_code == 200
    response = client.post("/api/auth/logout", headers={"Origin": ORIGIN})
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    client.cookies.set("__Host-fama_session", stolen)
    assert client.get("/api/auth/me").status_code == 401


def test_successful_login_rotates_and_revokes_previous_browser_session(web):
    client, _ = web
    assert login(client).status_code == 200
    previous = client.cookies.get("__Host-fama_session")
    assert login(client, "administrador").status_code == 200
    assert client.cookies.get("__Host-fama_session") != previous
    assert client.get("/api/auth/me").json()["rol"] == "administrador"
    client.cookies.clear()
    client.cookies.set("__Host-fama_session", previous)
    assert client.get("/api/auth/me").status_code == 401


def test_idle_boundary_and_absolute_lifetime_are_not_extended(web, monkeypatch):
    client, _ = web
    clock = [1800000000]
    monkeypatch.setattr(web_sessions.time, "time", lambda: clock[0])
    assert login(client).status_code == 200
    for delta in range(1700, 28800, 1700):
        clock[0] = 1800000000 + delta
        assert client.get("/api/auth/me").status_code == 200
    clock[0] = 1800000000 + 28800
    assert client.get("/api/auth/me").status_code == 401
    assert login(client).status_code == 200
    clock[0] += 1800
    assert client.get("/api/auth/me").status_code == 401


def test_disabled_account_is_rejected_on_the_next_request(web):
    client, sessions = web
    assert login(client).status_code == 200
    with sessions() as db:
        db.get(Usuario, 2).activo = False
        db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_bearer_jwt_never_grants_web_access(web, monkeypatch):
    from app.services import auth
    client, _ = web
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-jwt-key-not-used-for-web-sessions")
    token = auth.create_access_token({"sub": "1", "rol": "administrador"})
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_missing_origin_configuration_fails_closed(web, monkeypatch):
    client, _ = web
    monkeypatch.delenv("FAMA_WEB_ORIGIN")
    assert login(client).status_code == 503
    assert "set-cookie" not in login(client).headers


def test_all_auth_responses_including_failures_are_not_cacheable(web):
    client, _ = web
    for response in (client.get("/api/auth/me"), client.post("/api/auth/login", json={}),
                     client.post("/api/auth/logout")):
        assert response.headers.get("cache-control") == "no-store"


def test_database_outage_fails_closed_without_sql_or_session_cookie(web):
    client, sessions = web
    assert login(client).status_code == 200
    engine = sessions.kw["bind"]

    def unavailable(*args):
        raise OperationalError("SELECT sensitive_schema", {"password": PASSWORD}, RuntimeError("private host"))

    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        for response in (client.get("/api/auth/me"), login(client),
                         client.post("/api/auth/logout", headers={"Origin": ORIGIN})):
            assert response.status_code == 503
            assert "set-cookie" not in response.headers
            assert response.headers["cache-control"] == "no-store"
            for secret in ("SELECT", PASSWORD, "private host"):
                assert secret not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)


@pytest.mark.parametrize("origin", ["https://fama.example.test/", "https://u:p@fama.example.test",
                                   "https://fama.example.test:99999", "http://fama.example.test",
                                   "https://fama.example.test?x=1", "https://fama.example.test#x"])
def test_unsafe_origin_configuration_never_issues_cookie(web, monkeypatch, origin):
    client, _ = web
    monkeypatch.setenv("FAMA_WEB_ORIGIN", origin)
    assert login(client).status_code == 503


@pytest.mark.parametrize("maximum,idle", [("0", "1800"), ("28800", "0"), ("100", "101"),
                                       ("many", "1800"), ("2678401", "1800")])
def test_invalid_durations_fail_closed(web, monkeypatch, maximum, idle):
    client, _ = web
    monkeypatch.setenv("FAMA_SESSION_MAX_AGE_SECONDS", maximum)
    monkeypatch.setenv("FAMA_SESSION_IDLE_SECONDS", idle)
    assert login(client).status_code == 503


@pytest.mark.parametrize("field,value", [("email", "not-an-email"), ("email", "a" * 151 + "@test"),
                                       ("password", "short"), ("password", "x" * 1025),
                                       ("nombre_completo", "x" * 151)])
def test_invalid_account_fields_are_rejected_without_echoing_secrets(web, field, value):
    client, _ = web
    assert login(client, "administrador").status_code == 200
    payload = {"email": "valid@example.test", "password": PASSWORD,
               "nombre_completo": "Synthetic researcher"}
    payload[field] = value
    response = client.post("/api/auth/register", headers={"Origin": ORIGIN}, json=payload)
    assert response.status_code == 422
    assert value not in response.text
    assert PASSWORD not in response.text


def test_failed_login_commit_does_not_issue_a_session_after_rollback(web):
    client, sessions = web
    commits = [0]

    def fail_once(session):
        commits[0] += 1
        # Quota reservation commits first; reject the actual session transaction.
        if commits[0] == 2:
            raise OperationalError("private statement", {}, RuntimeError("private database"))

    event.listen(sessions.class_, "before_commit", fail_once)
    try:
        response = login(client)
        assert response.status_code == 503
        assert "set-cookie" not in response.headers
        assert client.get("/api/auth/me").status_code == 401
    finally:
        event.remove(sessions.class_, "before_commit", fail_once)
