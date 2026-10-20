"""Public Compose configuration with synthetic inputs; no daemon or services."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import io
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import pytest


ROOT = Path(__file__).resolve().parents[1]


def isolated_environment(tmp_path):
    config = tmp_path / "docker-client"
    config.mkdir(exist_ok=True)
    # Explicit dummy auth also prevents automatic OS credential-store discovery.
    client_configuration = {"auths": {"fixture.invalid": {"auth": "ZmFrZTpmYWtl"}}}
    executable = shutil.which("docker")
    if executable:
        plugins = Path(executable).resolve().parent.parent / "cli-plugins"
        if plugins.is_dir():
            # Discover installed plugins without reading the user's Docker config.
            client_configuration["cliPluginsExtraDirs"] = [str(plugins)]
    (config / "config.json").write_text(json.dumps(client_configuration))
    return {
        key: os.environ[key] for key in ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR")
        if key in os.environ
    } | {"DOCKER_CONFIG": str(config), "NO_PROXY": "127.0.0.1,localhost"}


def test_compose_forwards_explicit_authentication_settings(tmp_path):
    compose = tmp_path / "compose.yml"
    compose.write_bytes((ROOT / "docker-compose.yml").read_bytes())
    environment_file = tmp_path / "empty.env"
    environment_file.write_text("")
    authentication = {
        "JWT_SECRET_KEY": "synthetic-compose-key-not-a-real-signing-secret",
        "ADMIN_INITIAL_EMAIL": "bootstrap@example.test",
        "ADMIN_INITIAL_PASSWORD": "SyntheticOperatorPassword2026!",
        "ADMIN_INITIAL_NAME": "Synthetic administrator",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "45",
    }
    environment = isolated_environment(tmp_path) | authentication | {
        "HOST_UID": "1000", "HOST_GID": "1000",
        "POSTGRES_USER": "fixture", "POSTGRES_PASSWORD": "not-a-real-db-password",
        "POSTGRES_DB": "fixture_db", "GCS_BUCKET_NAME": "fixture-bucket",
        "GOOGLE_APPLICATION_CREDENTIALS": "fixture-service-account.json",
        "GCP_KEY_PATH": "fixture-service-account.json", "XC_API_KEY": "fixture-api-key",
        "API_URL": "http://backend:8000", "NEXT_PUBLIC_API_URL": "",
    }

    result = subprocess.run(
        ["docker", "compose", "--project-name", "fama-config-test", "--env-file",
         str(environment_file), "-f", str(compose), "config", "--format", "json"],
        env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)["services"]["backend"]["environment"]
    for key, expected in authentication.items():
        assert resolved.get(key) == expected


def test_compose_does_not_fill_missing_authentication_with_shared_credentials(tmp_path):
    compose = tmp_path / "compose.yml"
    compose.write_bytes((ROOT / "docker-compose.yml").read_bytes())
    environment_file = tmp_path / "empty.env"
    environment_file.write_text("")
    environment = isolated_environment(tmp_path) | {"HOST_UID": "1000", "HOST_GID": "1000"}

    result = subprocess.run(
        ["docker", "compose", "--project-name", "fama-config-test", "--env-file",
         str(environment_file), "-f", str(compose), "config", "--format", "json"],
        env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)["services"]["backend"]["environment"]
    for key in ("JWT_SECRET_KEY", "ADMIN_INITIAL_EMAIL", "ADMIN_INITIAL_PASSWORD"):
        assert resolved[key] == ""


@pytest.mark.parametrize("overrides,expected", [
    ({}, ("67108864", "268435456")),
    ({"FAMA_UPLOAD_MAX_FILE_BYTES": "20000", "FAMA_UPLOAD_MAX_BATCH_BYTES": "30000"}, ("20000", "30000")),
])
def test_compose_preserves_configurable_upload_limits(tmp_path, overrides, expected):
    compose = tmp_path / "compose.yml"
    compose.write_bytes((ROOT / "docker-compose.yml").read_bytes())
    environment_file = tmp_path / "empty.env"
    environment_file.write_text("")
    environment = isolated_environment(tmp_path) | {"HOST_UID": "1000", "HOST_GID": "1000"} | overrides

    result = subprocess.run(
        ["docker", "compose", "--project-name", "fama-config-test", "--env-file",
         str(environment_file), "-f", str(compose), "config", "--format", "json"],
        env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)["services"]["backend"]["environment"]
    assert resolved.get("FAMA_UPLOAD_MAX_FILE_BYTES") == expected[0]
    assert resolved.get("FAMA_UPLOAD_MAX_BATCH_BYTES") == expected[1]


@pytest.mark.parametrize("credential", [
    "proyectotesis-fama-de4426cc102e.json", "custom-gcs.json", "credentials/nested-key.json",
])
def test_docker_client_excludes_declared_cloud_credentials_from_context(tmp_path, credential):
    context = tmp_path / "context"
    context.mkdir()
    (context / ".dockerignore").write_bytes((ROOT / "backend/.dockerignore").read_bytes())
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /fixture\n")
    (context / credential).parent.mkdir(parents=True, exist_ok=True)
    (context / credential).write_text("SYNTHETIC_CREDENTIAL_MUST_NOT_BE_SENT")
    (context / ".env").write_text("SYNTHETIC_ENV_MUST_NOT_BE_SENT")
    (context / "keep.py").write_text("# non-secret application source\n")
    recipe = context / "training" / "recipes" / "fixture.yaml"
    recipe.parent.mkdir(parents=True)
    recipe.write_text("model_id: fixture\n")
    received = []

    class SimulatedEngine(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def respond(self, data, content_type="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("API-Version", "1.52")
            self.send_header("OSType", "linux")
            self.send_header("Builder-Version", "1")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_HEAD(self):
            self.respond(b"OK", "text/plain")

        def do_GET(self):
            path = urlsplit(self.path).path
            if path.endswith("/_ping"):
                self.respond(b"OK", "text/plain")
            elif path.endswith("/version"):
                self.respond(json.dumps({"Version": "fixture", "ApiVersion": "1.52",
                                         "MinAPIVersion": "1.24", "Os": "linux", "Arch": "amd64"}).encode())
            else:
                self.respond(json.dumps({"OSType": "linux", "Architecture": "amd64"}).encode())

        def do_POST(self):
            if not urlsplit(self.path).path.endswith("/build"):
                self.send_error(404)
                return
            data = bytearray()
            if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                while True:
                    length = int(self.rfile.readline().split(b";", 1)[0].strip(), 16)
                    if length == 0:
                        while self.rfile.readline().strip():
                            pass
                        break
                    data.extend(self.rfile.read(length))
                    self.rfile.read(2)
            else:
                data.extend(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            received.append(bytes(data))
            # Simulate the protocol acknowledgement only. No image is constructed.
            self.respond(b'{"stream":"Successfully built synthetic-fixture\\n"}\n')

    server = ThreadingHTTPServer(("127.0.0.1", 0), SimulatedEngine)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        environment = isolated_environment(tmp_path) | {
            "DOCKER_BUILDKIT": "0", "DOCKER_API_VERSION": "1.52",
        }
        result = subprocess.run(
            ["docker", "--host", f"tcp://127.0.0.1:{server.server_port}",
             "build", "--network", "none", "--quiet", str(context)],
            env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=30,
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert len(received) == 1
    with tarfile.open(fileobj=io.BytesIO(received[0]), mode="r:*") as archive:
        files = {member.name.removeprefix("./") for member in archive.getmembers()}
    assert "keep.py" in files
    assert "training/recipes/fixture.yaml" in files
    assert ".env" not in files
    assert credential not in files
    assert b"SYNTHETIC_CREDENTIAL_MUST_NOT_BE_SENT" not in received[0]
