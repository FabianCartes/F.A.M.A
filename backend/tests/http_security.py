"""Synthetic HTTP credentials and explicit legacy business-test identity."""
import weakref
import pytest

_COOKIE_HEADERS = weakref.WeakKeyDictionary()
COOKIE_ORIGIN = "http://localhost:3000"
COOKIE_PASSWORD = "SyntheticCookiePassword2026!"
from contextlib import contextmanager

from app.models.user import Usuario
from app.services.web_sessions import current_web_user


def configure_access_limits(monkeypatch):
    """Explicit synthetic configuration; keep production defaults under test."""
    monkeypatch.setenv("FAMA_RATE_LIMIT_KEY", "synthetic-access-limit-key-not-for-deployment-2026")
    monkeypatch.delenv("FAMA_ACCESS_LIMITS_JSON", raising=False)


def configure_cookie_sessions(monkeypatch):
    """Pin synthetic configuration; do not relax production origin or quotas."""
    configure_access_limits(monkeypatch)
    monkeypatch.setenv("FAMA_WEB_ORIGIN", COOKIE_ORIGIN)
    monkeypatch.setenv("FAMA_ALLOW_INSECURE_LOOPBACK", "1")


@pytest.fixture(autouse=True)
def cookie_security(monkeypatch):
    configure_cookie_sessions(monkeypatch)


def cookie_headers(sessions, user_id):
    """Log in a seeded user through canonical HTTP, returning an explicit cookie.

    A private router-only client prevents implicit cookies from contaminating
    anonymous cases. Each principal logs in once per synthetic database; every
    resource request still validates the real persisted, revocable session.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routes.auth import router
    from app.services.auth import hash_password
    from app.models.access_quota import CuotaAcceso
    from app.models.security_audit import EventoSeguridad
    from app.models.web_session import SesionWeb

    cache = _COOKIE_HEADERS.setdefault(sessions, {})
    if user_id in cache:
        return dict(cache[user_id])
    # Fixtures built from ORM metadata or Alembic already hold these tables; the
    # synthetic ones that omit them only need them present, never migrated.
    for table in (SesionWeb.__table__, CuotaAcceso.__table__, EventoSeguridad.__table__):
        table.create(sessions.kw["bind"], checkfirst=True)
    with sessions() as db:
        user = db.get(Usuario, int(user_id))
        if user is None or user.id <= 0 or not user.activo:
            return {"Origin": COOKIE_ORIGIN, "Cookie": "fama_session_dev=" + "x" * 43}
        email = user.email
        user.password_hash = hash_password(COOKIE_PASSWORD)
        db.commit()

    app = FastAPI()
    app.include_router(router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app, base_url=COOKIE_ORIGIN) as client:
        response = client.post("/api/auth/login", headers={"Origin": COOKIE_ORIGIN},
                               json={"email": email, "password": COOKIE_PASSWORD})
        assert response.status_code == 200, response.text
        assert set(response.json()) == {"user"}
        assert response.json()["user"]["id"] == int(user_id)
        credential = {"Origin": COOKIE_ORIGIN,
                      "Cookie": "fama_session_dev=" + client.cookies["fama_session_dev"]}
    cache[user_id] = credential
    return dict(credential)


@contextmanager
def administrator_http(app):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[current_web_user] = lambda: Usuario(
        id=1, email="synthetic-admin@example.test", nombre_completo="Synthetic admin",
        password_hash="not-used-by-this-fixture", rol="administrador", activo=True,
    )
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
