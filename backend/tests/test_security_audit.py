"""Security audit/maintenance contracts through HTTP with a temporary database."""
from fastapi.testclient import TestClient

from tests.test_account_management import accounts
from tests.test_web_sessions import login, ORIGIN, PASSWORD
from urllib.parse import urlsplit, parse_qs
import pytest
from app.models.dataset import ConjuntoDatos
from app.routes.access import router as access_router


@pytest.fixture(autouse=True)
def audit_configuration(monkeypatch):
    monkeypatch.delenv("FAMA_AUDIT_RETENTION_DAYS", raising=False)


def test_audit_is_administrative_and_records_login_without_request_secrets(accounts):
    client, _ = accounts
    assert client.get("/api/security/audit").status_code == 401
    assert login(client).status_code == 200
    assert client.get("/api/security/audit").status_code == 403
    response = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
        "email": "private-unregistered@example.test", "password": "NeverLogThisPassword!",
    })
    assert response.status_code == 401
    assert login(client, "administrador").status_code == 200
    response = client.get("/api/security/audit?limit=2")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert [(event["action"], event["outcome"]) for event in response.json()["events"]] == [
        ("session.login", "success"), ("session.login", "denied"),
    ]
    assert response.json()["events"][0]["actor_id"] == 1
    assert response.json()["events"][1]["actor_id"] is None
    assert response.json()["next_before_id"] is not None
    for secret in (PASSWORD, "NeverLogThisPassword!", "private-unregistered@example.test", ORIGIN):
        assert secret not in response.text


def test_account_changes_and_recovery_record_ids_not_personal_values(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    created = client.post("/api/auth/register", headers={"Origin": ORIGIN}, json={
        "email": "private-created@example.test", "password": PASSWORD, "nombre_completo": "NeverLogThisName",
    })
    assert created.status_code == 201
    identifier = created.json()["id"]
    for changes in ({"nombre_completo": "NeverLogUpdatedName", "rol": "administrador"},
                    {"activo": False}, {"activo": True}):
        assert client.patch(f"/api/users/{identifier}", headers={"Origin": ORIGIN}, json=changes).status_code == 200
    issued = client.post(f"/api/users/{identifier}/password-reset", headers={"Origin": ORIGIN})
    assert issued.status_code == 200
    token = parse_qs(urlsplit(issued.json()["reset_url"]).fragment)["token"][0]
    assert client.post("/api/auth/reset-password", headers={"Origin": ORIGIN}, json={
        "token": token, "new_password": "NeverLogRecoveredPassword!",
    }).status_code == 204
    with TestClient(client.app, base_url=ORIGIN) as researcher:
        assert login(researcher).status_code == 200
        assert researcher.post("/api/auth/change-password", headers={"Origin": ORIGIN}, json={
            "current_password": PASSWORD, "new_password": "NeverLogNewPassword!",
        }).status_code == 204
    response = client.get("/api/security/audit?limit=100")
    events = response.json()["events"]
    actions = {event["action"] for event in events}
    assert {"account.created", "account.name_updated", "account.role_changed", "account.suspended",
            "account.reactivated", "account.recovery_issued", "account.password_reset", "account.password_changed"} <= actions
    reset = next(event for event in events if event["action"] == "account.password_reset")
    assert reset["actor_id"] is None and reset["subject_user_id"] == identifier
    changed = next(event for event in events if event["action"] == "account.password_changed")
    assert changed["actor_id"] == 2 and changed["subject_user_id"] == 2
    for secret in (token, issued.json()["reset_url"], PASSWORD, "NeverLogThisName", "NeverLogUpdatedName",
                   "private-created@example.test", "NeverLogRecoveredPassword!", "NeverLogNewPassword!"):
        assert secret not in response.text


def test_admitted_denials_are_recorded_but_quota_rejections_do_not_add_a_row(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    assert client.patch("/api/users/1", headers={"Origin": ORIGIN}, json={"rol": "investigador"}).status_code == 409
    assert client.post("/api/auth/reset-password", headers={"Origin": ORIGIN}, json={
        "token": "a" * 43, "new_password": "NeverLogThisResetPassword!",
    }).status_code == 400
    with TestClient(client.app, base_url=ORIGIN) as researcher:
        assert login(researcher).status_code == 200
        assert researcher.post("/api/auth/change-password", headers={"Origin": ORIGIN}, json={
            "current_password": "wrong", "new_password": "NeverLogNewPassword!",
        }).status_code == 400
    events = client.get("/api/security/audit?limit=100").json()["events"]
    assert {event["action"] for event in events if event["outcome"] == "denied"} == {
        "account.role_changed", "account.password_reset", "account.password_changed",
    }
    for _ in range(5):
        assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
            "email": "unknown@example.test", "password": "wrong",
        }).status_code == 401
    before = client.get("/api/security/audit?limit=100").json()
    assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
        "email": "unknown@example.test", "password": "wrong",
    }).status_code == 429
    assert client.get("/api/security/audit?limit=100").json() == before


@pytest.fixture
def audit_access(accounts):
    client, sessions = accounts
    client.app.include_router(access_router)
    with sessions() as db:
        db.add(ConjuntoDatos(id_conjunto_datos=10, nombre="PrivateDatasetName", ruta_gcp="datasets/PrivateDatasetName"))
        db.commit()
    return client, sessions


def test_assignment_events_are_atomic_effective_changes_with_actor_and_resource_ids(audit_access):
    client, _ = audit_access
    assert login(client, "administrador").status_code == 200
    path = "/api/access/users/2/datasets/10"
    for _ in range(2):
        assert client.put(path, headers={"Origin": ORIGIN}).status_code == 200
    for _ in range(2):
        assert client.delete(path, headers={"Origin": ORIGIN}).status_code == 204
    response = client.get("/api/security/audit?limit=100")
    changes = [event for event in response.json()["events"] if event["action"].startswith("assignment.")]
    assert [event["action"] for event in changes] == ["assignment.revoked", "assignment.granted"]
    assert all((event["actor_id"], event["subject_user_id"], event["dataset_id"]) == (1, 2, 10) for event in changes)
    assert "PrivateDatasetName" not in response.text


def test_cleanup_requires_administrator_origin_and_has_a_bounded_default(accounts):
    client, _ = accounts
    assert client.post("/api/security/cleanup", headers={"Origin": ORIGIN}).status_code == 401
    assert login(client).status_code == 200
    assert client.post("/api/security/cleanup", headers={"Origin": ORIGIN}).status_code == 403
    assert login(client, "administrador").status_code == 200
    assert client.post("/api/security/cleanup").status_code == 403
    response = client.post("/api/security/cleanup", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json() == {"batch_size": 500, "deleted": {"sessions": 0, "recoveries": 0, "quotas": 0, "audit": 0},
                               "has_more": False}
    assert client.get("/api/auth/me").status_code == 200
    event = client.get("/api/security/audit?limit=1").json()["events"][0]
    assert (event["action"], event["actor_id"], event["outcome"]) == ("security.cleanup", 1, "success")


@pytest.fixture
def expired_security(accounts, monkeypatch):
    from app.services import security_audit
    client, sessions = accounts
    start = 1800000000
    clock = [start]
    monkeypatch.setattr(security_audit.time, "time", lambda: clock[0])
    monkeypatch.setenv("FAMA_AUDIT_RETENTION_DAYS", "90")
    assert login(client, "administrador").status_code == 200
    created = client.post("/api/auth/register", headers={"Origin": ORIGIN}, json={
        "email": "archived@example.test", "password": PASSWORD, "nombre_completo": "Archived account",
    })
    assert created.status_code == 201
    assert client.post(f"/api/users/{created.json()['id']}/password-reset", headers={"Origin": ORIGIN}).status_code == 200
    with TestClient(client.app, base_url=ORIGIN) as old_one, TestClient(client.app, base_url=ORIGIN) as old_two:
        for browser in (old_one, old_two):
            assert browser.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
                "email": "archived@example.test", "password": PASSWORD,
            }).status_code == 200
        assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
            "email": "old-unknown@example.test", "password": "wrong",
        }).status_code == 401
        clock[0] += 91 * 86400
        assert login(client, "administrador").status_code == 200
        with TestClient(client.app, base_url=ORIGIN) as current:
            assert login(current).status_code == 200
            issued = client.post("/api/users/2/password-reset", headers={"Origin": ORIGIN})
            assert issued.status_code == 200
            # Recovery issuance revoked the previous session, so create a fresh
            # one with the still-valid password after issuance.
            assert login(current).status_code == 200
            token = parse_qs(urlsplit(issued.json()["reset_url"]).fragment)["token"][0]
            for _ in range(5):
                assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
                    "email": "current-unknown@example.test", "password": "wrong",
                }).status_code == 401
            yield client, sessions, current, token, clock[0]


def test_cleanup_is_bounded_repeated_and_preserves_live_sessions_recoveries_and_quotas(expired_security):
    client, _, current, token, now = expired_security
    response = client.post("/api/security/cleanup", headers={"Origin": ORIGIN}, json={"batch_size": 1})
    assert response.status_code == 200
    assert response.json()["deleted"] == {"sessions": 1, "recoveries": 1, "quotas": 1, "audit": 1}
    assert response.json()["has_more"] is True
    assert current.get("/api/auth/me").status_code == 200
    for _ in range(30):
        if not response.json()["has_more"]:
            break
        response = client.post("/api/security/cleanup", headers={"Origin": ORIGIN}, json={"batch_size": 1})
        assert response.status_code == 200
        assert all(0 <= count <= 1 for count in response.json()["deleted"].values())
    assert response.json()["has_more"] is False
    events = client.get("/api/security/audit?limit=100").json()["events"]
    assert events and all(event["occurred_at"] == now for event in events)
    assert current.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
        "email": "current-unknown@example.test", "password": "wrong",
    }).status_code == 429
    assert current.post("/api/auth/reset-password", headers={"Origin": ORIGIN}, json={
        "token": token, "new_password": "KeptByCleanupPassword2026!",
    }).status_code == 204


def test_cursor_pagination_does_not_repeat_or_lose_older_events_when_new_events_arrive(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    for _ in range(4):
        assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={
            "email": "unknown@example.test", "password": "wrong",
        }).status_code == 401
    original = client.get("/api/security/audit?limit=100").json()["events"]
    page = client.get("/api/security/audit?limit=2").json()
    seen = [event["id"] for event in page["events"]]
    assert client.patch("/api/users/2", headers={"Origin": ORIGIN}, json={"nombre_completo": "Changed name"}).status_code == 200
    while page["next_before_id"] is not None:
        page = client.get(f"/api/security/audit?limit=2&before_id={page['next_before_id']}").json()
        seen.extend(event["id"] for event in page["events"])
    assert seen == [event["id"] for event in original]
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize("operation", ["create", "suspend", "change-password", "recovery", "grant", "revoke"])
def test_audit_failure_rolls_back_sensitive_mutation_and_does_not_revoke_live_sessions(audit_access, operation):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    client, sessions = audit_access
    assert login(client, "administrador").status_code == 200
    path = "/api/access/users/2/datasets/10"
    if operation == "revoke":
        assert client.put(path, headers={"Origin": ORIGIN}).status_code == 200
    with TestClient(client.app, base_url=ORIGIN) as researcher:
        assert login(researcher).status_code == 200
        before = client.get("/api/security/audit?limit=100").json()
        engine = sessions.kw["bind"]
        def unavailable(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("INSERT INTO EVENTO_SEGURIDAD"):
                raise OperationalError("private audit statement", {}, RuntimeError("private host"))
        event.listen(engine, "before_cursor_execute", unavailable)
        try:
            if operation == "create":
                response = client.post("/api/auth/register", headers={"Origin": ORIGIN}, json={
                    "email": "never-created@example.test", "password": PASSWORD, "nombre_completo": "Never created",
                })
            elif operation == "suspend":
                response = client.patch("/api/users/2", headers={"Origin": ORIGIN}, json={"activo": False})
            elif operation == "change-password":
                response = researcher.post("/api/auth/change-password", headers={"Origin": ORIGIN}, json={
                    "current_password": PASSWORD, "new_password": "NeverCommittedPassword2026!",
                })
            elif operation == "recovery":
                response = client.post("/api/users/2/password-reset", headers={"Origin": ORIGIN})
            else:
                response = client.request("PUT" if operation == "grant" else "DELETE", path, headers={"Origin": ORIGIN})
            assert response.status_code == 503
            assert response.headers["cache-control"] == "no-store"
            assert "private" not in response.text
        finally:
            event.remove(engine, "before_cursor_execute", unavailable)
        assert researcher.get("/api/auth/me").status_code == 200
        assert login(researcher).status_code == 200
    assert client.get("/api/users").json()["total"] == 2
    assert client.get(path).json()["assigned"] is (operation == "revoke")
    after = client.get("/api/security/audit?limit=100").json()["events"]
    # Only the explicit successful re-login above is new, never a phantom mutation.
    assert after[1:] == before["events"]
    assert after[0]["action"] == "session.login"


def test_successful_login_cannot_be_issued_without_its_audit_event(accounts):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    client, sessions = accounts
    engine = sessions.kw["bind"]
    def unavailable(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO EVENTO_SEGURIDAD"):
            raise OperationalError("private audit statement", {}, RuntimeError("private host"))
    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        response = login(client, "administrador")
        assert response.status_code == 503
        assert "set-cookie" not in response.headers
        assert client.get("/api/auth/me").status_code == 401
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)
    assert login(client, "administrador").status_code == 200
    assert len(client.get("/api/security/audit").json()["events"]) == 1


def test_cleanup_and_its_audit_event_are_one_transaction(expired_security):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    client, sessions, current, _, _ = expired_security
    before = client.get("/api/security/audit?limit=100").json()
    engine = sessions.kw["bind"]
    def unavailable(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO EVENTO_SEGURIDAD"):
            raise OperationalError("private audit statement", {}, RuntimeError("private host"))
    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        response = client.post("/api/security/cleanup", headers={"Origin": ORIGIN}, json={"batch_size": 1})
        assert response.status_code == 503
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)
    assert current.get("/api/auth/me").status_code == 200
    assert client.get("/api/security/audit?limit=100").json() == before
    retry = client.post("/api/security/cleanup", headers={"Origin": ORIGIN}, json={"batch_size": 1})
    assert retry.status_code == 200
    assert retry.json()["deleted"] == {"sessions": 1, "recoveries": 1, "quotas": 1, "audit": 1}


@pytest.mark.parametrize("value", [0, -1, 1001, True, "500", None])
def test_cleanup_rejects_unbounded_or_ambiguous_batches(accounts, value):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    assert client.post("/api/security/cleanup", headers={"Origin": ORIGIN}, json={"batch_size": value}).status_code == 422


@pytest.mark.parametrize("value", ["0", "-1", "many", "3651"])
def test_invalid_retention_fails_closed_without_running_cleanup(accounts, monkeypatch, value):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    before = client.get("/api/security/audit?limit=100").json()
    monkeypatch.setenv("FAMA_AUDIT_RETENTION_DAYS", value)
    assert client.post("/api/security/cleanup", headers={"Origin": ORIGIN}).status_code == 503
    assert client.get("/api/security/audit?limit=100").json() == before


def test_concurrent_cleanup_and_quota_renewal_preserve_the_new_budget(accounts, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.services import security_audit
    client, _ = accounts
    clock = [1800000000]
    monkeypatch.setattr(security_audit.time, "time", lambda: clock[0])
    assert login(client, "administrador").status_code == 200
    payload = {"email": "renewed@example.test", "password": "wrong"}
    assert client.post("/api/auth/login", headers={"Origin": ORIGIN}, json=payload).status_code == 401
    clock[0] += 901
    with TestClient(client.app, base_url=ORIGIN) as renewal:
        barrier = Barrier(2)
        def clean():
            barrier.wait(timeout=10)
            return client.post("/api/security/cleanup", headers={"Origin": ORIGIN})
        def renew():
            barrier.wait(timeout=10)
            return renewal.post("/api/auth/login", headers={"Origin": ORIGIN}, json=payload)
        with ThreadPoolExecutor(max_workers=2) as pool:
            clean_result, renewal_result = pool.submit(clean), pool.submit(renew)
            assert clean_result.result(timeout=20).status_code == 200
            assert renewal_result.result(timeout=20).status_code == 401
        for _ in range(4):
            assert renewal.post("/api/auth/login", headers={"Origin": ORIGIN}, json=payload).status_code == 401
        assert renewal.post("/api/auth/login", headers={"Origin": ORIGIN}, json=payload).status_code == 429


def test_audit_retention_boundary_is_exact(accounts, monkeypatch):
    from app.services import security_audit
    client, _ = accounts
    start = 1800000000
    clock = [start]
    monkeypatch.setattr(security_audit.time, "time", lambda: clock[0])
    assert login(client, "administrador").status_code == 200
    clock[0] += 90 * 86400 - 1
    assert login(client, "administrador").status_code == 200
    first = client.post("/api/security/cleanup", headers={"Origin": ORIGIN})
    assert first.status_code == 200
    assert first.json()["deleted"]["audit"] == 0
    clock[0] += 1
    second = client.post("/api/security/cleanup", headers={"Origin": ORIGIN})
    assert second.status_code == 200
    assert second.json()["deleted"]["audit"] == 1
    assert all(event["occurred_at"] > start for event in client.get("/api/security/audit?limit=100").json()["events"])


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "before_id=0", "before_id=-1", f"before_id={2 ** 63}"])
def test_audit_pagination_has_bounded_validated_inputs(accounts, query):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    assert client.get(f"/api/security/audit?{query}").status_code == 422


def test_authenticated_audit_read_rejects_an_explicit_foreign_browser_origin(accounts):
    client, _ = accounts
    assert login(client, "administrador").status_code == 200
    assert client.get("/api/security/audit", headers={"Origin": "https://evil.example.test"}).status_code == 403
    assert client.get("/api/security/audit", headers={"Origin": ORIGIN}).status_code == 200
