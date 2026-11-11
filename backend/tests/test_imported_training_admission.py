"""Historical authentication fixture and preserved standard HTTP queries.

Imported start admission is retired; its rejection is tested in test_api_training.
"""
import pytest
from tests.http_security import cookie_headers, cookie_security
from tests.test_api_training import client
from tests.test_training_flow import training_env


@pytest.fixture
def authenticated(training_env, monkeypatch):
    from app.models.user import Usuario
    from app.services import auth
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-t3-signing-key-not-a-production-secret-2026")
    with training_env[1]() as db:
        db.add(Usuario(id=1, email="owner@example.test", password_hash="unused",
                       nombre_completo="Owner", rol="investigador", activo=True))
        db.add(Usuario(id=2, email="foreign@example.test", password_hash="unused",
                       nombre_completo="Synthetic", rol="investigador", activo=True))
        db.commit()
    return cookie_headers(training_env[1], 2)


@pytest.mark.parametrize("path", ["datasets", "history", "progress"])
def test_legacy_queries_preserve_access_without_using_supplied_credentials(client, training_env, path):
    expected = client.get("/api/training/" + path)
    response = client.get("/api/training/" + path, headers={"Authorization": "Bearer invalid"})
    assert response.status_code == expected.status_code == 200
    assert response.json() == expected.json()
