"""Rejected authentication never changes persisted accounts."""
import hashlib

import pytest
from fastapi import HTTPException

from app.services.auth import ensure_authentication_configured, AuthenticationConfigurationError
from app.services import auth
from tests.test_auth_service import db_session


def test_rejected_login_and_existing_account_bootstrap_preserve_database(db_session, monkeypatch):
    auth.create_user(
        db_session, "probe@example.test", "SyntheticPassword2026!",
        "Synthetic researcher",
    )

    def fingerprint():
        connection = db_session.connection().connection.driver_connection
        return hashlib.sha256(connection.serialize()).hexdigest()

    before = fingerprint()

    for key in (None, "", " " * 32, "x" * 31, "fama_bioacoustic_secret_key_mlops_2026"):
        monkeypatch.setattr(auth, "SECRET_KEY", key)
        with pytest.raises(AuthenticationConfigurationError):
            ensure_authentication_configured()
        assert fingerprint() == before

    monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "replacement@example.test")
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "ReplacementPassword2026!")
    assert auth.seed_initial_admin(db_session) is None
    assert fingerprint() == before
