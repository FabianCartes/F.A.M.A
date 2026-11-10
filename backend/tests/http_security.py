"""Explicit identity fixture for pre-existing business (not authentication) tests."""
from contextlib import contextmanager

from app.models.user import Usuario
from app.services.web_sessions import current_web_user


def configure_access_limits(monkeypatch):
    """Explicit synthetic configuration; keep production defaults under test."""
    monkeypatch.setenv("FAMA_RATE_LIMIT_KEY", "synthetic-access-limit-key-not-for-deployment-2026")
    monkeypatch.delenv("FAMA_ACCESS_LIMITS_JSON", raising=False)


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
