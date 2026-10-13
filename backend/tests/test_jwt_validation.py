"""JWT validation at public auth seams, with isolated key and clock."""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone, timedelta

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
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_security_configuration(monkeypatch):
    class FixedClock:
        @classmethod
        def now(cls, tz):
            return NOW.astimezone(tz)

    monkeypatch.setattr(auth, "SECRET_KEY", TEST_KEY)
    monkeypatch.setattr(auth, "datetime", FixedClock)


def signed_token(payload, header=None):
    """Independent RFC-style fixture signer; never use private auth helpers."""
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    header = {"alg": "HS256", "typ": "JWT"} if header is None else header
    message = f"{encode(header)}.{encode(payload)}"
    signature = hmac.new(TEST_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def test_signed_token_without_expiration_is_rejected():
    token = signed_token({"sub": "1"})

    with pytest.raises(ValueError):
        auth.decode_access_token(token)


@pytest.mark.parametrize("header", [
    {"alg": "none"}, {"alg": "HS512"}, {"alg": 1}, {}, [],
])
def test_signed_token_cannot_declare_an_unsupported_algorithm(header):
    token = signed_token({"sub": "1", "exp": int(NOW.timestamp()) + 60}, header)

    with pytest.raises(ValueError):
        auth.decode_access_token(token)


@pytest.mark.parametrize("payload", [None, ["exp"], "exp", 42])
def test_signed_payload_must_be_a_json_object(payload):
    with pytest.raises(ValueError):
        auth.decode_access_token(signed_token(payload))


@pytest.mark.parametrize("expiration", [None, "2030", True, False, [], {}, float("nan"), float("inf")])
def test_expiration_must_be_a_finite_numeric_date(expiration):
    with pytest.raises(ValueError):
        auth.decode_access_token(signed_token({"sub": "1", "exp": expiration}))


def test_zero_lifetime_token_is_expired_at_the_exact_boundary():
    token = auth.create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=0))

    with pytest.raises(ValueError, match="expirado"):
        auth.decode_access_token(token)


def test_fractional_numeric_date_is_not_extended_to_the_next_second(monkeypatch):
    class FractionalClock:
        @classmethod
        def now(cls, tz):
            return (NOW + timedelta(milliseconds=750)).astimezone(tz)

    monkeypatch.setattr(auth, "datetime", FractionalClock)
    token = signed_token({"sub": "1", "exp": NOW.timestamp() + 0.5})

    with pytest.raises(ValueError, match="expirado"):
        auth.decode_access_token(token)


@pytest.fixture
def auth_client():
    """Router-only HTTP app: no production lifespan, model loading or cloud."""
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
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    engine.dispose()


@pytest.mark.parametrize("subject", ["not-an-id", " 1 ", "+1", "١", True, 1, 1.5, ["1"], {"id": 1}])
def test_invalid_user_subject_returns_401_instead_of_500_or_another_user(auth_client, subject):
    token = auth.create_access_token({"sub": subject})

    response = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "fixture@example.test" not in response.text


def test_non_ascii_signature_is_a_validation_error_not_a_type_error():
    token = auth.create_access_token({"sub": "1"})
    header, payload, _ = token.split(".")

    with pytest.raises(ValueError):
        auth.decode_access_token(f"{header}.{payload}.ñ")


@pytest.mark.parametrize("segment", [0, 1])
def test_signed_non_base64url_segments_are_rejected(segment):
    parts = auth.create_access_token({"sub": "1"}).split(".")
    parts[segment] += "!"
    message = ".".join(parts[:2])
    signature = hmac.new(TEST_KEY.encode(), message.encode(), hashlib.sha256).digest()
    token = message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    with pytest.raises(ValueError):
        auth.decode_access_token(token)


@pytest.mark.parametrize("subject", [str(2 ** 63), "9" * 100])
def test_user_subject_outside_database_integer_range_returns_401(auth_client, subject):
    token = auth.create_access_token({"sub": subject})

    response = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_valid_issued_token_uses_database_identity_and_role(auth_client):
    token = auth.create_access_token({"sub": "1", "rol": "administrador"})
    decoded = auth.decode_access_token(token)
    assert decoded["sub"] == "1"

    response = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "fixture@example.test"
    assert response.json()["rol"] == "investigador"
    assert "password_hash" not in response.json()
