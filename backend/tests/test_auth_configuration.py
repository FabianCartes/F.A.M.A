"""Public auth configuration contracts, without deployed credentials or DB."""
import os
import subprocess
import sys
from pathlib import Path
import pytest

from app.services import auth
from tests.test_jwt_validation import auth_client, signed_token, NOW, TEST_KEY
from tests.test_auth_service import db_session


@pytest.fixture(autouse=True)
def synthetic_bootstrap_display_name(monkeypatch):
    monkeypatch.setenv("ADMIN_INITIAL_NAME", "Synthetic administrator")


def test_missing_environment_key_cannot_issue_a_session():
    environment = dict(os.environ)
    environment.pop("JWT_SECRET_KEY", None)
    environment.update(DATABASE_URL="sqlite://", PYTHON_DOTENV_DISABLED="1",
                       PYTHONDONTWRITEBYTECODE="1")
    script = """
from app.services.auth import create_access_token
try:
    create_access_token({'sub': '1'})
except RuntimeError:
    print('authentication_not_configured')
else:
    print('session_issued')
"""

    result = subprocess.run(
        [sys.executable, "-c", script], env=environment,
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "authentication_not_configured"


def test_login_without_key_returns_503_and_never_a_session(auth_client, monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", None)

    response = auth_client.post("/api/auth/login", json={
        "email": "fixture@example.test", "password": "FixturePassword2026!",
    })

    assert response.status_code == 503
    assert set(response.json()) == {"detail"}
    assert "FixturePassword2026!" not in response.text
    monkeypatch.setattr(auth, "SECRET_KEY", TEST_KEY)
    token = auth.create_access_token({"sub": "1"})
    profile = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.status_code == 200
    assert profile.json()["ultimo_acceso"] is None


def test_profile_without_key_reports_configuration_failure_not_invalid_credentials(auth_client, monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", None)
    token = signed_token({"sub": "1", "exp": NOW.timestamp() + 60})

    response = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503
    assert "fixture@example.test" not in response.text


@pytest.mark.parametrize("key", ["", " ", "short", "fama_bioacoustic_secret_key_mlops_2026", "\ud800" * 32])
def test_unsafe_signing_key_cannot_issue_a_session(monkeypatch, key):
    monkeypatch.setattr(auth, "SECRET_KEY", key)

    with pytest.raises(auth.AuthenticationConfigurationError):
        auth.create_access_token({"sub": "1"})


def test_configured_login_issues_a_usable_session_without_echoing_secrets(auth_client, monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", TEST_KEY)

    response = auth_client.post("/api/auth/login", json={
        "email": "fixture@example.test", "password": "FixturePassword2026!",
    })

    assert response.status_code == 200
    token = response.json()["access_token"]
    assert "FixturePassword2026!" not in response.text
    assert TEST_KEY not in response.text
    profile = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.status_code == 200
    assert profile.json()["email"] == "fixture@example.test"


@pytest.mark.parametrize("missing", ["email", "password", "both"])
def test_initial_admin_requires_explicit_operator_credentials(db_session, monkeypatch, missing):
    monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "bootstrap@example.test")
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "OperatorPassword2026!")
    if missing in ("email", "both"):
        monkeypatch.delenv("ADMIN_INITIAL_EMAIL")
    if missing in ("password", "both"):
        monkeypatch.delenv("ADMIN_INITIAL_PASSWORD")

    with pytest.raises(auth.AuthenticationConfigurationError):
        auth.seed_initial_admin(db_session)

    monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "bootstrap@example.test")
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "OperatorPassword2026!")
    administrator = auth.seed_initial_admin(db_session)
    assert administrator.id == 1
    assert administrator.email == "bootstrap@example.test"
    assert administrator.rol == "administrador"


@pytest.mark.parametrize("email,password", [
    (" ", "OperatorPassword2026!"),
    ("not-an-email", "OperatorPassword2026!"),
    ("bootstrap@example.test", " "),
    ("bootstrap@example.test", "short"),
    ("bootstrap@example.test", "AdminFama2026!"),
])
def test_initial_admin_rejects_unsafe_explicit_credentials(db_session, monkeypatch, email, password):
    monkeypatch.setenv("ADMIN_INITIAL_EMAIL", email)
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", password)

    with pytest.raises(auth.AuthenticationConfigurationError):
        auth.seed_initial_admin(db_session)


def test_existing_admin_is_preserved_without_bootstrap_configuration(db_session, monkeypatch):
    monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "bootstrap@example.test")
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "OperatorPassword2026!")
    initial = auth.seed_initial_admin(db_session)
    identity, password_hash = initial.id, initial.password_hash
    monkeypatch.delenv("ADMIN_INITIAL_EMAIL")
    monkeypatch.delenv("ADMIN_INITIAL_PASSWORD")

    existing = auth.seed_initial_admin(db_session)

    assert existing.id == identity
    assert existing.email == "bootstrap@example.test"
    assert existing.password_hash == password_hash
    assert auth.verify_password("OperatorPassword2026!", existing.password_hash)
