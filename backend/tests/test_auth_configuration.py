"""Public auth configuration contracts, without deployed credentials or DB."""
import importlib.util
import pytest

from app.services import auth
from tests.test_jwt_validation import auth_client, signed_token, NOW, TEST_KEY
from tests.test_auth_service import db_session


@pytest.fixture(autouse=True)
def synthetic_bootstrap_display_name(monkeypatch):
    monkeypatch.setenv("ADMIN_INITIAL_NAME", "Synthetic administrator")


def test_missing_environment_key_cannot_issue_a_session(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    # Fresh module execution observes the missing environment key without
    # escaping the repository's original in-process isolation guard.
    spec = importlib.util.spec_from_file_location("isolated_auth_configuration", auth.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(module.AuthenticationConfigurationError):
        module.create_access_token({"sub": "1"})


def test_login_without_web_configuration_returns_503_and_never_a_session(auth_client, monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", None)
    monkeypatch.delenv("FAMA_WEB_ORIGIN")

    response = auth_client.post("/api/auth/login", json={
        "email": "fixture@example.test", "password": "FixturePassword2026!",
    })

    assert response.status_code == 503
    assert set(response.json()) == {"detail"}
    assert "FixturePassword2026!" not in response.text
    assert "set-cookie" not in response.headers


def test_profile_without_web_configuration_reports_configuration_failure(auth_client, monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", None)
    monkeypatch.delenv("FAMA_WEB_ORIGIN")
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
    assert "access_token" not in response.json()
    assert "FixturePassword2026!" not in response.text
    assert TEST_KEY not in response.text
    profile = auth_client.get("/api/auth/me")
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
