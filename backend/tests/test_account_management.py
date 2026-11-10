"""Account lifecycle through HTTP, isolated file SQLite with foreign keys."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models.user import Usuario
from app.routes.auth import router as auth_router
from app.routes.users import router as users_router
from app.routes.security import router as security_router
from app.services.auth import hash_password
from tests.test_web_sessions import ORIGIN, PASSWORD, login
from urllib.parse import urlsplit, parse_qs
from tests.http_security import configure_access_limits


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    configure_access_limits(monkeypatch)
    monkeypatch.setenv("FAMA_WEB_ORIGIN", ORIGIN)
    engine = create_engine(f"sqlite:///{tmp_path / 'accounts.sqlite'}",
                           connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    password_hash = hash_password(PASSWORD)
    with sessions() as db:
        for identifier, role in [(1, "administrador"), (2, "investigador")]:
            db.add(Usuario(id=identifier, email=f"{role}@example.test", password_hash=password_hash,
                           nombre_completo=role, rol=role, activo=True))
        db.commit()

    def isolated_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(security_router)
    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        yield client, sessions
    engine.dispose()


def test_accounts_are_administrator_only_paginated_and_never_expose_credentials(accounts):
    client, _ = accounts
    assert client.get("/api/users").status_code == 401
    assert login(client).status_code == 200
    assert client.get("/api/users").status_code == 403
    assert login(client, "administrador").status_code == 200
    response = client.get("/api/users?limit=1&offset=1")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["total"] == 2
    assert [user["id"] for user in response.json()["users"]] == [2]
    assert "password" not in response.text
    assert "token" not in response.text


@pytest.mark.parametrize("changes", [{"activo": False}, {"rol": "administrador"}])
def test_sensitive_account_changes_revoke_all_target_sessions_permanently(accounts, changes):
    client, _ = accounts
    with TestClient(client.app, base_url=ORIGIN) as target:
        assert login(target).status_code == 200
        old_cookie = target.cookies.get("__Host-fama_session")
        assert login(client, "administrador").status_code == 200
        response = client.patch("/api/users/2", headers={"Origin": ORIGIN}, json=changes)
        assert response.status_code == 200
        assert target.get("/api/auth/me").status_code == 401
        assert client.patch("/api/users/2", headers={"Origin": ORIGIN},
                            json={"activo": True, "rol": "investigador"}).status_code == 200
        assert target.cookies.get("__Host-fama_session") == old_cookie
        assert target.get("/api/auth/me").status_code == 401
        assert login(target).status_code == 200


def test_last_active_administrator_cannot_be_suspended_or_demoted(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    for changes in ({"activo": False}, {"rol": "investigador"}):
        assert client.patch("/api/users/1", headers={"Origin": ORIGIN}, json=changes).status_code == 409
        assert client.get("/api/auth/me").json()["rol"] == "administrador"
    assert client.patch("/api/users/2", headers={"Origin": ORIGIN}, json={"rol": "administrador"}).status_code == 200
    assert client.patch("/api/users/1", headers={"Origin": ORIGIN}, json={"rol": "investigador"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_changing_own_password_requires_current_password_and_revokes_every_session(accounts):
    client, _ = accounts
    assert login(client).status_code == 200
    with TestClient(client.app, base_url=ORIGIN) as other_session:
        assert login(other_session).status_code == 200
        response = client.post("/api/auth/change-password", headers={"Origin": ORIGIN},
                               json={"current_password": "wrong", "new_password": "ReplacementPassword2026!"})
        assert response.status_code == 400
        assert client.get("/api/auth/me").status_code == 200
        response = client.post("/api/auth/change-password", headers={"Origin": ORIGIN},
                               json={"current_password": PASSWORD, "new_password": "ReplacementPassword2026!"})
        assert response.status_code == 204
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert client.get("/api/auth/me").status_code == 401
        assert other_session.get("/api/auth/me").status_code == 401
    assert login(client).status_code == 401
    assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
        "email": "investigador@example.test", "password": "ReplacementPassword2026!",
    }).status_code == 200


def test_recovery_is_administrator_issued_revocable_and_single_use(accounts):
    client, _ = accounts
    path = "/api/users/2/password-reset"
    assert client.post(path, headers={"Origin": ORIGIN}).status_code == 401
    assert login(client).status_code == 200
    assert client.post(path, headers={"Origin": ORIGIN}).status_code == 403
    with TestClient(client.app, base_url=ORIGIN) as target:
        assert login(target).status_code == 200
        assert login(client, "administrador").status_code == 200
        response = client.post(path, headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["expires_in"] == 900
        url = urlsplit(response.json()["reset_url"])
        assert url.scheme + "://" + url.netloc == ORIGIN
        assert not url.query  # Token must not reach server URL logs or referrers.
        token = parse_qs(url.fragment)["token"][0]
        assert target.get("/api/auth/me").status_code == 401
        payload = {"token": token, "new_password": "RecoveredPassword2026!"}
        response = target.post("/api/auth/reset-password", headers={"Origin": ORIGIN}, json=payload)
        assert response.status_code == 204
        assert token not in response.text
        assert target.post("/api/auth/reset-password", headers={"Origin": ORIGIN}, json=payload).status_code == 400
        assert login(target).status_code == 401
        assert target.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
            "email": "investigador@example.test", "password": "RecoveredPassword2026!",
        }).status_code == 200


@pytest.mark.parametrize("mutation", ["suspend-reactivate", "role-change", "own-password"])
def test_pending_recovery_is_invalidated_by_sensitive_changes(accounts, mutation):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    issued = client.post("/api/users/2/password-reset", headers={"Origin": ORIGIN})
    token = parse_qs(urlsplit(issued.json()["reset_url"]).fragment)["token"][0]
    if mutation == "own-password":
        with TestClient(client.app, base_url=ORIGIN) as target:
            assert login(target).status_code == 200
            assert target.post("/api/auth/change-password", headers={"Origin": ORIGIN}, json={
                "current_password": PASSWORD, "new_password": "LegitimateChange2026!",
            }).status_code == 204
    elif mutation == "role-change":
        assert client.patch("/api/users/2", headers={"Origin": ORIGIN}, json={"rol": "administrador"}).status_code == 200
    else:
        for active in (False, True):
            assert client.patch("/api/users/2", headers={"Origin": ORIGIN}, json={"activo": active}).status_code == 200
    response = client.post("/api/auth/reset-password", headers={"Origin": ORIGIN},
                           json={"token": token, "new_password": "UnwantedReset2026!"})
    assert response.status_code == 400


@pytest.mark.parametrize("elapsed,expected", [(899, 204), (900, 400)])
def test_recovery_expires_at_exact_boundary_and_reissue_invalidates_previous(accounts, monkeypatch, elapsed, expected):
    from app.services import accounts as account_service
    client, _ = accounts
    clock = [1800000000]
    monkeypatch.setattr(account_service.time, "time", lambda: clock[0])
    assert login(client, "administrador").status_code == 200
    def issue():
        response = client.post("/api/users/2/password-reset", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        return parse_qs(urlsplit(response.json()["reset_url"]).fragment)["token"][0]
    previous, current = issue(), issue()
    assert current != previous
    response = client.post("/api/auth/reset-password", headers={"Origin": ORIGIN},
                           json={"token": previous, "new_password": "RecoveredPassword2026!"})
    assert response.status_code == 400
    clock[0] += elapsed
    response = client.post("/api/auth/reset-password", headers={"Origin": ORIGIN},
                           json={"token": current, "new_password": "RecoveredPassword2026!"})
    assert response.status_code == expected


def test_concurrent_self_demotion_preserves_one_active_administrator(accounts):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    assert client.patch("/api/users/2", headers={"Origin": ORIGIN}, json={"rol": "administrador"}).status_code == 200
    with TestClient(client.app, base_url=ORIGIN) as second:
        assert login(second).status_code == 200
        barrier = Barrier(2)
        def demote(browser, user_id):
            barrier.wait(timeout=10)
            return browser.patch(f"/api/users/{user_id}", headers={"Origin": ORIGIN}, json={"rol": "investigador"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(demote, client, 1)
            other = pool.submit(demote, second, 2)
            statuses = [first.result(timeout=20).status_code, other.result(timeout=20).status_code]
        assert sorted(statuses) == [200, 409]
        survivor = second if statuses[0] == 200 else client
        users = survivor.get("/api/users").json()["users"]
        assert sum(user["activo"] and user["rol"] == "administrador" for user in users) == 1


@pytest.mark.parametrize("payload", [{}, {"rol": None}, {"activo": "false"}, {"rol": "superuser"},
                                     {"nombre_completo": " "}, {"email": "stolen@example.test"},
                                     {"password_hash": "injected"}, {"nombre_completo": "x" * 151}])
def test_patch_rejects_ambiguous_or_unsupported_fields_without_echoing_input(accounts, payload):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    response = client.patch("/api/users/2", headers={"Origin": ORIGIN}, json=payload)
    assert response.status_code == 422
    assert "stolen@example.test" not in response.text
    assert "injected" not in response.text


def test_administrative_creation_rejects_blank_password_and_preserves_existing_account(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    payload = {"email": "new@example.test", "nombre_completo": "New account", "password": " " * 12}
    response = client.post("/api/auth/register", headers={"Origin": ORIGIN}, json=payload)
    assert response.status_code == 422
    assert client.get("/api/users").json()["total"] == 2
    payload["password"] = "NewAccountPassword2026!"
    assert client.post("/api/auth/register", headers={"Origin": ORIGIN}, json=payload).status_code == 201
    assert client.post("/api/auth/register", headers={"Origin": ORIGIN}, json=payload).status_code == 400
    assert client.get("/api/users").json()["total"] == 3


def test_password_change_and_concurrent_old_password_login_leave_no_old_session(accounts):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    client, _ = accounts
    assert login(client).status_code == 200
    with TestClient(client.app, base_url=ORIGIN) as old_login:
        barrier = Barrier(2)
        def change():
            barrier.wait(timeout=10)
            return client.post("/api/auth/change-password", headers={"Origin": ORIGIN}, json={
                "current_password": PASSWORD, "new_password": "NewConcurrentPassword2026!",
            })
        def authenticate():
            barrier.wait(timeout=10)
            return login(old_login)
        with ThreadPoolExecutor(max_workers=2) as pool:
            change_result = pool.submit(change)
            login_result = pool.submit(authenticate)
            assert change_result.result(timeout=20).status_code == 204
            assert login_result.result(timeout=20).status_code in (200, 401)
        assert old_login.get("/api/auth/me").status_code == 401


def test_reset_commit_failure_rolls_back_password_revocation_and_token_consumption(accounts):
    from sqlalchemy.exc import OperationalError
    client, sessions = accounts
    assert login(client, "administrador").status_code == 200
    issued = client.post("/api/users/2/password-reset", headers={"Origin": ORIGIN})
    token = parse_qs(urlsplit(issued.json()["reset_url"]).fragment)["token"][0]
    commits = [0]
    def unavailable(session):
        commits[0] += 1
        # Quota admission is durable first; fail the separate credential mutation.
        if commits[0] == 2:
            raise OperationalError("private statement", {}, RuntimeError("private backend"))
    event.listen(sessions.class_, "before_commit", unavailable)
    try:
        response = client.post("/api/auth/reset-password", headers={"Origin": ORIGIN}, json={
            "token": token, "new_password": "RecoveredAfterRetry2026!",
        })
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert token not in response.text and "private" not in response.text
        assert "set-cookie" not in response.headers
    finally:
        event.remove(sessions.class_, "before_commit", unavailable)
    with TestClient(client.app, base_url=ORIGIN) as target:
        assert login(target).status_code == 200  # Old password was not changed by a failed commit.
        assert target.post("/api/auth/reset-password", headers={"Origin": ORIGIN}, json={
            "token": token, "new_password": "RecoveredAfterRetry2026!",
        }).status_code == 204
        assert target.get("/api/auth/me").status_code == 401


def test_name_only_update_keeps_session_and_no_account_is_physically_deleted(accounts):
    client, _ = accounts
    with TestClient(client.app, base_url=ORIGIN) as target:
        assert login(target).status_code == 200
        assert login(client, "administrador").status_code == 200
        assert client.patch("/api/users/2", headers={"Origin": ORIGIN},
                            json={"nombre_completo": "  Updated researcher  "}).status_code == 200
        assert target.get("/api/auth/me").json()["nombre_completo"] == "Updated researcher"
        assert client.delete("/api/users/2", headers={"Origin": ORIGIN}).status_code == 405
        assert client.get("/api/users").json()["total"] == 2


def test_administrative_mutations_and_recovery_require_trusted_origin(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    assert client.patch("/api/users/2", json={"activo": False}).status_code == 403
    assert client.post("/api/users/2/password-reset", headers={"Origin": "https://evil.example.test"}).status_code == 403
    assert client.post("/api/auth/reset-password", json={
        "token": "a" * 43, "new_password": "RecoveryPassword2026!",
    }).status_code == 403
    assert client.post("/api/auth/change-password", json={
        "current_password": PASSWORD, "new_password": "ReplacementPassword2026!",
    }).status_code == 403


def test_recovery_cannot_activate_a_suspended_account(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    assert client.patch("/api/users/2", headers={"Origin": ORIGIN}, json={"activo": False}).status_code == 200
    assert client.post("/api/users/2/password-reset", headers={"Origin": ORIGIN}).status_code == 409


@pytest.mark.parametrize("path", ["/api/users?limit=0", "/api/users?limit=101", "/api/users?offset=-1"])
def test_account_listing_has_bounded_pagination(accounts, path):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    assert client.get(path).status_code == 422
