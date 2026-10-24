"""Persistent admission quotas at the agreed login/recovery HTTP interfaces."""
import pytest
from urllib.parse import urlsplit, parse_qs
import json

from tests.test_account_management import accounts
from tests.test_web_sessions import ORIGIN, PASSWORD, login

TEST_LIMIT_KEY = "synthetic-access-limit-key-not-for-deployment-2026"


@pytest.fixture(autouse=True)
def limit_configuration(monkeypatch):
    monkeypatch.setenv("FAMA_RATE_LIMIT_KEY", TEST_LIMIT_KEY)
    monkeypatch.delenv("FAMA_ACCESS_LIMITS_JSON", raising=False)


def test_login_rejects_sixth_normalized_account_attempt_without_issuing_cookie(accounts):
    client, _ = accounts
    for email in ("investigador@example.test", "INVESTIGADOR@example.test", " investigador@example.test ",
                  "investigador@example.test", "investigador@example.test"):
        response = client.post("/api/auth/login", headers={"Origin": ORIGIN},
                               json={"email": email, "password": "wrong"})
        assert response.status_code == 401
    response = login(client)
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 120
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert "investigador@example.test" not in response.text
    assert PASSWORD not in response.text


def test_login_peer_limit_cannot_be_evaded_with_forwarded_headers(accounts):
    client, _ = accounts
    for index in range(60):
        response = client.post("/api/auth/login", headers={"Origin": ORIGIN,
                               "X-Forwarded-For": f"203.0.113.{index + 1}"},
                               json={"email": f"unknown-{index}@example.test", "password": "wrong"})
        assert response.status_code == 401
    response = client.post("/api/auth/login", headers={"Origin": ORIGIN, "X-Forwarded-For": "198.51.100.1"},
                           json={"email": "another@example.test", "password": "wrong"})
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60


def test_recovery_target_limit_does_not_replace_last_admitted_token(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    for _ in range(3):
        issued = client.post("/api/users/2/password-reset", headers={"Origin": ORIGIN})
        assert issued.status_code == 200
    token = parse_qs(urlsplit(issued.json()["reset_url"]).fragment)["token"][0]
    denied = client.post("/api/users/2/password-reset", headers={"Origin": ORIGIN})
    assert denied.status_code == 429
    assert "reset_url" not in denied.json()
    assert 1 <= int(denied.headers["retry-after"]) <= 900
    assert client.post("/api/auth/reset-password", headers={"Origin": ORIGIN}, json={
        "token": token, "new_password": "RecoveredWithLimit2026!",
    }).status_code == 204


def test_recovery_consumption_is_limited_without_treating_forwarded_headers_as_identity(accounts):
    client, _ = accounts
    for index in range(20):
        response = client.post("/api/auth/reset-password", headers={"Origin": ORIGIN,
                               "X-Forwarded-For": f"203.0.113.{index + 1}"},
                               json={"token": "a" * 43, "new_password": "NeverAppliedPassword2026!"})
        assert response.status_code == 400
    response = client.post("/api/auth/reset-password", headers={"Origin": ORIGIN},
                           json={"token": "b" * 43, "new_password": "NeverAppliedPassword2026!"})
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 900


def test_limits_can_be_configured_without_disabling_other_policies(accounts, monkeypatch):
    client, _ = accounts
    monkeypatch.setenv("FAMA_ACCESS_LIMITS_JSON", json.dumps({
        "login_account": {"limit": 2, "window_seconds": 60},
    }))
    assert login(client).status_code == 200
    assert login(client).status_code == 200
    response = login(client)
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert client.get("/api/auth/me").status_code == 200  # Throttling is not account suspension/logout.


@pytest.mark.parametrize("configuration", ["null", "[]", "{", '{"unknown": {}}',
    '{"login_account": {"limit": 0, "window_seconds": 900}}',
    '{"login_account": {"limit": true, "window_seconds": 900}}',
    '{"login_account": {"limit": 5, "window_seconds": -1}}',
    '{"login_account": {"limit": 5, "window_seconds": 900, "typo": 1}}'])
def test_invalid_limit_configuration_fails_closed(accounts, monkeypatch, configuration):
    client, _ = accounts
    monkeypatch.setenv("FAMA_ACCESS_LIMITS_JSON", configuration)
    response = login(client)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    assert response.json() == {"detail": "Límites de acceso no configurados."}


def test_login_reopens_at_120_seconds_and_rejected_attempts_do_not_extend_window(accounts, monkeypatch):
    from app.services import access_limits
    client, _ = accounts
    clock = [1800000000]
    monkeypatch.setattr(access_limits.time, "time", lambda: clock[0])
    for _ in range(5):
        assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
            "email": "investigador@example.test", "password": "wrong",
        }).status_code == 401
    denied = login(client)
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "120"
    assert "set-cookie" not in denied.headers
    clock[0] += 119
    denied = login(client)
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "1"
    assert client.get("/api/auth/me").status_code == 401
    clock[0] += 1
    assert login(client).status_code == 200


def test_rejected_peer_reservation_does_not_spend_other_accounts_budget(accounts, monkeypatch):
    from app.services import access_limits
    client, _ = accounts
    clock = [1800000000]
    monkeypatch.setattr(access_limits.time, "time", lambda: clock[0])
    monkeypatch.setenv("FAMA_ACCESS_LIMITS_JSON", json.dumps({
        "login_peer": {"limit": 1, "window_seconds": 60},
        "login_account": {"limit": 2, "window_seconds": 900},
    }))
    def attempt(email):
        return client.post("/api/auth/login", headers={"Origin": ORIGIN},
                           json={"email": email, "password": "wrong"})
    assert attempt("first@example.test").status_code == 401
    assert attempt("second@example.test").status_code == 429
    for elapsed in (60, 120):
        clock[0] = 1800000000 + elapsed
        assert attempt("second@example.test").status_code == 401
    clock[0] = 1800000000 + 180
    assert attempt("second@example.test").status_code == 429


def test_recovery_issuer_has_a_combined_limit_across_target_accounts(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    targets = [2]
    for index in range(3):
        response = client.post("/api/auth/register", headers={"Origin": ORIGIN}, json={
            "email": f"target-{index}@example.test", "password": PASSWORD, "nombre_completo": "Target account",
        })
        assert response.status_code == 201
        targets.append(response.json()["id"])
    for target in targets[:3]:
        for _ in range(3):
            assert client.post(f"/api/users/{target}/password-reset", headers={"Origin": ORIGIN}).status_code == 200
    assert client.post(f"/api/users/{targets[3]}/password-reset", headers={"Origin": ORIGIN}).status_code == 200
    assert client.post(f"/api/users/{targets[3]}/password-reset", headers={"Origin": ORIGIN}).status_code == 429


def test_concurrent_requests_share_atomic_account_budget(accounts):
    from contextlib import ExitStack
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    client, _ = accounts
    barrier = Barrier(6)
    with ExitStack() as stack:
        browsers = [stack.enter_context(TestClient(client.app, base_url=ORIGIN)) for _ in range(6)]
        def attempt(browser):
            barrier.wait(timeout=10)
            return browser.post("/api/auth/login", headers={"Origin": ORIGIN},
                                json={"email": "unknown@example.test", "password": "wrong"}).status_code
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, browsers))
    assert sorted(results) == [401, 401, 401, 401, 401, 429]


def test_budget_survives_a_new_python_process(accounts):
    import os
    import subprocess
    import sys
    from pathlib import Path
    client, sessions = accounts
    for _ in range(5):
        assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
            "email": "restart@example.test", "password": "wrong",
        }).status_code == 401
    environment = dict(os.environ, DATABASE_URL=str(sessions.kw["bind"].url), PYTHON_DOTENV_DISABLED="1",
                       PYTHONDONTWRITEBYTECODE="1", FAMA_WEB_ORIGIN=ORIGIN)
    script = '''
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes.auth import router
app = FastAPI()
app.include_router(router)
with TestClient(app, base_url="https://fama.example.test") as client:
    result = client.post("/api/auth/login", headers={"Origin": "https://fama.example.test"},
        json={"email": "restart@example.test", "password": "wrong"})
    print(result.status_code)
'''
    result = subprocess.run([sys.executable, "-c", script], env=environment,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "429"


@pytest.mark.parametrize("key", [None, "", "short", " " * 32, "\ud800" * 32])
def test_missing_or_unsafe_hmac_key_fails_closed_without_a_cookie(accounts, monkeypatch, key):
    client, _ = accounts
    if key is None:
        monkeypatch.delenv("FAMA_RATE_LIMIT_KEY")
    else:
        monkeypatch.setenv("FAMA_RATE_LIMIT_KEY", key)
    response = login(client)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    assert response.json() == {"detail": "Límites de acceso no configurados."}


def test_bad_origin_never_spends_an_accounts_budget(accounts):
    client, _ = accounts
    payload = {"email": "unknown@example.test", "password": "wrong"}
    for _ in range(6):
        assert client.post("/api/auth/login", headers={"Origin": "https://evil.example.test"}, json=payload).status_code == 403
    for _ in range(5):
        assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json=payload).status_code == 401
    assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json=payload).status_code == 429


@pytest.mark.parametrize("email", ["\ud800", "x" * 151])
def test_invalid_account_identifiers_are_rejected_before_hashing_or_lookup(accounts, email):
    client, _ = accounts
    response = client.post("/api/auth/login", headers={"Origin": ORIGIN, "Content-Type": "application/json"},
                           content=json.dumps({"email": email, "password": "wrong"}, ensure_ascii=True))
    assert response.status_code == 422
    assert "set-cookie" not in response.headers


def test_failed_quota_write_never_issues_session_and_rolls_back_reservations(accounts):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    client, sessions = accounts
    engine = sessions.kw["bind"]
    def unavailable(*args):
        raise OperationalError("private counter statement", {}, RuntimeError("private host"))
    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        response = login(client)
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
        assert "private" not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)
    for _ in range(5):
        assert login(client).status_code == 200
    assert login(client).status_code == 429


def test_failed_quota_commit_never_falls_back_to_process_local_budget(accounts):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    client, sessions = accounts
    def unavailable(session):
        raise OperationalError("private counter commit", {}, RuntimeError("private host"))
    event.listen(sessions.class_, "before_commit", unavailable)
    try:
        response = login(client)
        assert response.status_code == 503
        assert "set-cookie" not in response.headers
    finally:
        event.remove(sessions.class_, "before_commit", unavailable)
    for _ in range(5):
        assert login(client).status_code == 200
    assert login(client).status_code == 429
