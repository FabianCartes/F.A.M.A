"""Former JWT credentials cannot authenticate the canonical cookie HTTP API."""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services import auth
from app.database import Base, get_db
from app.models.user import Usuario
from app.routes.auth import router

TEST_KEY = "isolated-jwt-validation-key-not-a-deployment-secret"
NOW = datetime(2030, 10, 12, 12, 0, tzinfo=timezone.utc)


def signed_token(payload, header=None):
    """Independent former credential; never a production issuer."""
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
    header = {"alg": "HS256", "typ": "JWT"} if header is None else header
    message = f"{encode(header)}.{encode(payload)}"
    signature = hmac.new(TEST_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


@pytest.fixture
def auth_client(monkeypatch):
    """Router-only HTTP app: no production lifespan, model loading or cloud."""
    from tests.http_security import configure_access_limits
    configure_access_limits(monkeypatch)
    monkeypatch.setenv("FAMA_WEB_ORIGIN", "https://auth.example.test")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(Usuario(id=1, email="fixture@example.test", password_hash=auth.hash_password("FixturePassword2026!"),
                       nombre_completo="Isolated fixture", rol="investigador", activo=True))
        db.commit()
    def isolated_db():
        with sessions() as db:
            yield db
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app, base_url="https://auth.example.test", headers={"Origin": "https://auth.example.test"},
                    raise_server_exceptions=False) as client:
        yield client
    engine.dispose()


@pytest.mark.parametrize("payload", [
    {"sub": "1", "exp": NOW.timestamp()}, {"sub": "1"},
    {"sub": "2", "rol": "administrador", "exp": NOW.timestamp()},
    {"sub": "-1", "exp": NOW.timestamp()}, {"sub": True, "exp": NOW.timestamp()},
])
def test_bearer_never_authenticates_or_switches_cookie_user(auth_client, payload):
    headers = {"Authorization": "Bearer " + signed_token(payload)}
    response = auth_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Sesión requerida o expirada."}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    login = auth_client.post("/api/auth/login", json={
        "email": "fixture@example.test", "password": "FixturePassword2026!",
    })
    assert login.status_code == 200
    assert set(login.json()) == {"user"}
    assert auth_client.get("/api/auth/me", headers=headers).json()["id"] == 1
    assert auth_client.post("/api/auth/logout", headers=headers).status_code == 204
    assert auth_client.get("/api/auth/me", headers=headers).status_code == 401
