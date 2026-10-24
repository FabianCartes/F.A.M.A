"""Arranque público antes de disponer de servicios institucionales."""
from fastapi.testclient import TestClient
import os
from pathlib import Path
import subprocess
import sys


def test_unconfigured_backend_exposes_status_and_blocks_functional_requests():
    from app.entrypoint import create_app
    from app.configuration import load_configuration

    with TestClient(create_app(load_configuration({}))) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/installation/status").json() == {"status": "required"}
        assert client.get("/ready").status_code == 503
        response = client.post("/predict", files={"file": ("test.wav", b"unused")})
        assert response.status_code == 503
        assert response.json()["code"] == "installation_required"


def test_configured_node_with_unreachable_database_remains_configured():
    from app.entrypoint import create_app
    from app.configuration import load_configuration

    configuration = load_configuration({
        "DATABASE_URL": "postgresql://fake:secret-not-for-http@127.0.0.1:1/test",
        "GCS_BUCKET_NAME": "test-bucket", "FAMA_WEB_ORIGIN": "https://fama.test",
        "JWT_SECRET_KEY": "j" * 40, "FAMA_RATE_LIMIT_KEY": "r" * 40,
    })
    with TestClient(create_app(configuration)) as client:
        assert client.get("/api/installation/status").json() == {"status": "configured"}
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"code": "database_unavailable"}
        assert "secret-not-for-http" not in response.text


def test_uvicorn_entry_starts_without_loading_ml_or_cloud_dependencies(tmp_path):
    environment = dict(os.environ, FAMA_CONFIG_DIR=str(tmp_path), PYTHON_DOTENV_DISABLED="1")
    script = '''
import sys
from importlib.abc import MetaPathFinder
class UnavailableDependencies(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "torch" or fullname.startswith("google.cloud"):
            raise RuntimeError("Dependency unavailable before installation")
sys.meta_path.insert(0, UnavailableDependencies())
from fastapi.testclient import TestClient
import main
with TestClient(main.app) as client:
    assert client.get("/api/installation/status").json() == {"status": "required"}
    assert client.get("/ready").status_code == 503
'''
    result = subprocess.run([sys.executable, "-c", script], env=environment,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_corrupt_persistent_state_returns_unavailable_without_reopening_setup(tmp_path, monkeypatch):
    from app.entrypoint import create_app

    (tmp_path / "installation.json").write_text('{"version": 999, "secret": "must-stay-private"}')
    monkeypatch.setenv("FAMA_CONFIG_DIR", str(tmp_path))
    with TestClient(create_app()) as client:
        assert client.get("/api/installation/status").json() == {"status": "unavailable"}
        assert client.get("/ready").json() == {"code": "configuration_invalid"}
        assert "must-stay-private" not in client.get("/ready").text
