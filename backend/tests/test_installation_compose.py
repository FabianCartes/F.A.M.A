"""Configuración pública de Compose, copiada y sin credenciales del operador."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_compose_has_no_personal_cloud_defaults_and_transmits_web_settings(tmp_path):
    docker = shutil.which("docker") or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if not Path(docker).is_file():
        pytest.skip("Requiere Docker CLI; no utiliza Docker Engine")
    source = Path(__file__).resolve().parents[2]
    shutil.copy2(source / "docker-compose.yml", tmp_path / "compose.yml")
    (tmp_path / "empty.env").write_text("")
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PROGRAMFILES", "PROGRAMDATA"}}
    environment.update(HOST_UID="1000", HOST_GID="1000", DOCKER_CONFIG=str(tmp_path / "docker-config"),
                       FAMA_WEB_ORIGIN="https://fama.test", FAMA_RATE_LIMIT_KEY="synthetic-test-key-" * 3)
    result = subprocess.run([docker, "compose", "--env-file", str(tmp_path / "empty.env"),
                             "-f", str(tmp_path / "compose.yml"), "config", "--format", "json"],
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    backend = json.loads(result.stdout)["services"]["backend"]
    assert backend["environment"]["GCS_BUCKET_NAME"] == ""
    assert backend["environment"]["GOOGLE_APPLICATION_CREDENTIALS"] == ""
    assert backend["environment"]["GCP_KEY_PATH"] == ""
    assert backend["environment"]["FAMA_WEB_ORIGIN"] == "https://fama.test"
    assert backend["environment"]["FAMA_RATE_LIMIT_KEY"] == "synthetic-test-key-" * 3
    assert "proyectotesis-fama" not in json.dumps(backend["volumes"])


def test_cloud_variant_replaces_local_dependencies_and_keeps_sql_private(tmp_path):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Requiere Docker CLI")
    source = Path(__file__).resolve().parents[2]
    for name in ("docker-compose.yml", "docker-compose.cloud.yml"):
        shutil.copy2(source / name, tmp_path / name)
    empty = tmp_path / "empty.env"
    empty.write_text("")
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PROGRAMFILES", "PROGRAMDATA"}}
    environment.update(
        HOST_UID="10001", HOST_GID="10001", DOCKER_CONFIG=str(tmp_path / "docker-config"),
        FAMA_CREDENTIALS_DIR=str(tmp_path / "credentials"),
        FAMA_INSTALLATION_DIR=str(tmp_path / "installation"),
        FAMA_RUNTIME_DIR=str(tmp_path / "runtime"),
        FAMA_CLOUD_SQL_CONNECTION_NAME="synthetic-project:us-central1:synthetic-instance",
        DATABASE_URL="postgresql://synthetic:MustNotBeUsed@db:5432/old",
    )
    arguments = [docker, "compose", "--env-file", str(empty), "-f", str(tmp_path / "docker-compose.yml"),
                 "-f", str(tmp_path / "docker-compose.cloud.yml"), "config", "--format", "json"]
    result = subprocess.run(arguments, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert "db" not in services
    backend, proxy = services["backend"], services["cloud-sql-proxy"]
    assert set(backend["depends_on"]) == {"cloud-sql-proxy"}
    assert backend["depends_on"]["cloud-sql-proxy"]["condition"] == "service_healthy"
    assert "DATABASE_URL" not in backend["environment"]
    assert backend["environment"]["FAMA_CONFIG_DIR"] == "/run/fama/installation/docker"
    assert backend["environment"]["PYTHON_DOTENV_DISABLED"] == "1"
    assert backend['environment']['FAMA_RUNTIME_DIR'] == '/var/lib/fama'
    targets = {volume['target'] for volume in backend['volumes']}
    assert '/var/lib/fama' in targets
    assert '/app/data' not in targets and '/app/checkpoints' not in targets
    assert not proxy.get("ports")
    assert "--run-connection-test" in proxy["command"]
    assert "synthetic-project:us-central1:synthetic-instance" in proxy["command"]
    assert "MustNotBeUsed" not in json.dumps(services)
    chosen_runtime = environment.pop('FAMA_RUNTIME_DIR')
    no_runtime = subprocess.run(arguments, env=environment, capture_output=True, text=True, timeout=30)
    assert no_runtime.returncode != 0
    environment['FAMA_RUNTIME_DIR'] = chosen_runtime
    del environment["FAMA_CLOUD_SQL_CONNECTION_NAME"]
    missing = subprocess.run(arguments, env=environment, capture_output=True, text=True, timeout=30)
    assert missing.returncode != 0
