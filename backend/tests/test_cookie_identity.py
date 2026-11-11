"""Cookie-only imported identity at the public HTTP boundary."""
import base64
import hashlib
import hmac
import json
import time
import pytest

from tests.test_web_sessions import web, login


def legacy_bearer(user_id=1):
    """Independent former HS256 credential, not a production token issuer."""
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
    message = encode({"alg": "HS256", "typ": "JWT"}) + "." + encode({
        "sub": str(user_id), "exp": int(time.time()) + 3600,
    })
    signature = hmac.new(b"synthetic-legacy-key-for-migration-tests-2026", message.encode(), hashlib.sha256).digest()
    return message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def test_bearer_without_cookie_cannot_read_imported_resource(web, monkeypatch):
    from app.routes.dataset_imports import router
    from app.services import auth
    client, _ = web
    client.app.include_router(router)
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-legacy-key-for-migration-tests-2026")
    response = client.get("/api/ingestion/imports/example.zip", headers={
        "Authorization": "Bearer " + legacy_bearer(),
    })
    assert response.status_code == 401
    assert response.json() == {"detail": "Sesión requerida o expirada."}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 401


def test_expected_principal_mismatch_does_not_refresh_idle_lifetime(web, monkeypatch):
    from fastapi import Depends, Request, Response
    from app.database import get_db
    from app.routes.auth import WebAuthRoute
    from app.services import web_sessions
    client, _ = web
    clock = [1800000000]
    monkeypatch.setattr(web_sessions.time, "time", lambda: clock[0])
    def expected(request: Request, response: Response, db=Depends(get_db)):
        return {"id": web_sessions.web_identity(request, response, db, expected_user_id=1).id}
    client.app.router.route_class = WebAuthRoute
    client.app.add_api_route("/expected-principal", expected, methods=["GET"])
    assert login(client).status_code == 200  # User 2, not expected user 1.
    clock[0] += 1700
    rejected = client.get("/expected-principal")
    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "Las credenciales no corresponden a la misma sesión."}
    assert rejected.headers["cache-control"] == "no-store"
    assert "set-cookie" not in rejected.headers
    clock[0] += 100
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("path", ["/api/ingestion/imports/example.zip",
                                  "/api/inference/history?model_id=301"])
def test_imported_auth_database_errors_are_private_and_not_cacheable(web, path):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from app.routes.dataset_imports import router as imports_router
    from app.routes.prediction_history import router as history_router
    client, sessions = web
    for router in (imports_router, history_router):
        client.app.include_router(router)
    assert login(client).status_code == 200
    def unavailable(*args):
        raise OperationalError("SELECT private_schema", {}, RuntimeError("private host"))
    engine = sessions.kw["bind"]
    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        response = client.get(path)
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
        assert "SELECT" not in response.text and "private host" not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)


@pytest.mark.parametrize("password", ["", "x" * 1025])
def test_canonical_login_preserves_bounded_password_contract(web, password):
    client, _ = web
    response = client.post("/api/auth/login", headers={"Origin": "https://fama.example.test"},
                           json={"email": "investigador@example.test", "password": password})
    assert response.status_code == 422
    assert response.json() == {"detail": "Solicitud de autenticación inválida."}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 401
