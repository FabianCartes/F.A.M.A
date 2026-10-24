"""CLI de preparación del operador, con secretos sintéticos introducidos por stdin."""
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy.engine import make_url


def node(*arguments, password="", extra_environment=None):
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP"}}
    environment.update(extra_environment or {})
    # Sustituir solo la entrada del terminal: getpass de Windows no lee pipes.
    program = ("import sys,runpy; from unittest.mock import patch; "
               "secret=sys.stdin.readline().rstrip('\\n'); "
               "p=patch('getpass.getpass',return_value=secret); p.start(); "
               "runpy.run_module('app.node',run_name='__main__')")
    return subprocess.run(
        [sys.executable, "-c", program, *map(str, arguments)],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        input=password, capture_output=True, text=True, timeout=20,
    )


def test_operator_prepares_native_and_docker_references_without_exposing_password(tmp_path):
    from app.configuration import load_configuration

    credentials = tmp_path / "application_default_credentials.json"
    credentials.write_text("{}")
    target = tmp_path / "cloud configuration"
    password = "SyntheticSecret:@/%'2026"
    arguments = ["--config-dir", target, "prepare", "--project", "synthetic-project", "--bucket", "synthetic-bucket",
                 "--credentials-file", credentials, "--connection-name", "synthetic-project:us-central1:synthetic-instance",
                 "--database", "synthetic_db", "--user", "synthetic_app"]
    result = node(*arguments, password=password + "\n")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"code": "configuration_prepared"}
    assert password not in result.stdout + result.stderr
    if os.name == "nt":
        program = ("$ErrorActionPreference = 'Stop'; "
                   "$root = Get-Item -LiteralPath $env:FAMA_TEST_ACL_PATH; "
                   "$items = @($root) + @(Get-ChildItem -LiteralPath $root.FullName -Recurse -Force); "
                   "$allowed = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18'); "
                   "foreach ($item in $items) { "
                   "$acl = if ($item.PSIsContainer) { [IO.Directory]::GetAccessControl($item.FullName) } "
                   "else { [IO.File]::GetAccessControl($item.FullName) }; "
                   "if ($item.PSIsContainer -and -not $acl.AreAccessRulesProtected) { "
                   "Write-Error ('Unprotected directory: ' + $item.Name); exit 1 }; "
                   "foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) { "
                   "if ($rule.AccessControlType -eq 'Allow' -and "
                   "$rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin $allowed) { "
                   "Write-Error ('Unexpected Allow rule: ' + $item.Name); exit 2 } } }; "
                   "Write-Output 'private'")
        powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        acl = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", program],
                             env=dict(os.environ, FAMA_TEST_ACL_PATH=str(target)),
                             capture_output=True, text=True, timeout=15)
        assert acl.returncode == 0, acl.stderr
        assert acl.stdout.strip() == "private"
    else:
        assert target.stat().st_mode & 0o777 == 0o700
    native = load_configuration({"FAMA_CONFIG_DIR": str(target / "native")})
    address = make_url(native.database_url)
    assert (address.host, address.port, address.database, address.username, address.password) == (
        "127.0.0.1", 5433, "synthetic_db", "synthetic_app", password)
    assert native.missing_requirements == ()
    assert native.installation_status == "required"
    assert native.values["GOOGLE_CLOUD_PROJECT"] == "synthetic-project"
    assert password not in (target / "native/installation.json").read_text()
    docker = json.loads((target / "docker/installation.json").read_text())
    assert docker["completed"] is False
    assert docker["values"]["DATABASE_URL_FILE"] == "/run/fama/installation/secrets/database-docker"
    docker_url = make_url((target / "secrets/database-docker").read_text())
    assert (docker_url.host, docker_url.port, docker_url.password) == ("cloud-sql-proxy", 5432, password)
    repeated = node(*arguments, password="different-password\n")
    assert repeated.returncode == 1
    assert json.loads(repeated.stdout) == {"code": "configuration_directory_exists"}
    assert load_configuration({"FAMA_CONFIG_DIR": str(target / "native")}).database_url == native.database_url


def test_check_uses_only_selected_configuration_and_sanitizes_invalid_secret(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    result = node("--config-dir", selected, "check", extra_environment={
        "DATABASE_URL": "postgresql://old:MustNotAppear@127.0.0.1:1/old", "GCS_BUCKET_NAME": "old-bucket",
    })
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "database": {"ok": False, "code": "database_configuration_missing"},
        "storage": {"ok": False, "code": "storage_configuration_missing"},
    }
    from app.configuration import InstallationStore
    InstallationStore(selected).save({"DATABASE_URL_FILE": str(selected / "not-present")})
    invalid = node("--config-dir", selected, "check")
    assert invalid.returncode == 1
    assert json.loads(invalid.stdout) == {"configuration": {"ok": False, "code": "configuration_invalid"}}
    assert str(selected) not in invalid.stdout


def test_native_startup_keeps_selected_installation_closed_without_loading_ml(tmp_path):
    program = """
import json,os,sys
from fastapi.testclient import TestClient
from app.node import create_node_app
app = create_node_app(sys.argv[1])
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
    assert client.get('/api/installation/status').json() == {'status':'required'}
    assert client.get('/ready').json() == {'code':'installation_required'}
    assert client.get('/api/auth/me').status_code == 503
assert 'torch' not in sys.modules
assert 'DATABASE_URL' not in os.environ
print(json.dumps({'startup':'ok'}))
"""
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP"}}
    environment["DATABASE_URL"] = "postgresql://old:MustNotAppear@127.0.0.1:1/old"
    result = subprocess.run([sys.executable, "-c", program, str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"startup": "ok"}
