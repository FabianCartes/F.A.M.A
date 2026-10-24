"""Diagnóstico público sin cargar ML, con servicios sintéticos o PostgreSQL aislado."""
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url


def test_reports_missing_sql_and_storage_independently_without_importing_ml():
    source = Path(__file__).resolve().parents[1]
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP"}}
    result = subprocess.run(
        [sys.executable, "-c", "import json,sys; from app.connections import diagnose; "
         "from app.configuration import load_configuration; "
         "print(json.dumps(diagnose(load_configuration({})))); assert 'torch' not in sys.modules"],
        cwd=source, env=environment, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "database": {"ok": False, "code": "database_configuration_missing"},
        "storage": {"ok": False, "code": "storage_configuration_missing"},
    }


@pytest.fixture
def postgres_url():
    address = os.environ.get("FAMA_TEST_POSTGRES_URL")
    if not address:
        pytest.skip("Requiere PostgreSQL local aislado mediante FAMA_TEST_POSTGRES_URL")
    parsed = make_url(address)
    assert parsed.host in {"127.0.0.1", "localhost"}
    return address


def test_sql_ping_works_on_empty_database_without_creating_tables(postgres_url, capsys):
    from app.configuration import load_configuration
    from app.connections import diagnose

    engine = create_engine(postgres_url)
    try:
        before = inspect(engine).get_table_names()
        report = diagnose(load_configuration({"DATABASE_URL": postgres_url}))
        assert report["database"] == {"ok": True, "code": "database_connected"}
        assert report["storage"]["code"] == "storage_configuration_missing"
        assert inspect(engine).get_table_names() == before
        assert capsys.readouterr().out == ""
    finally:
        engine.dispose()


def test_sql_auth_failure_does_not_hide_successful_storage_check(postgres_url, monkeypatch):
    from google.auth.credentials import AnonymousCredentials
    from app.configuration import load_configuration
    from app.connections import diagnose

    monkeypatch.setattr("google.auth.default", lambda **kwargs: (AnonymousCredentials(), "synthetic-project"))
    monkeypatch.setattr("google.cloud.storage.Client", lambda **kwargs: nullcontext(
        SimpleNamespace(list_blobs=lambda *args, **kwargs: iter(()))))
    password = "SyntheticWrongPasswordMustNotAppear"
    address = make_url(postgres_url).set(password=password).render_as_string(hide_password=False)
    report = diagnose(load_configuration({"DATABASE_URL": address, "GCS_BUCKET_NAME": "synthetic-bucket"}))
    assert report == {
        "database": {"ok": False, "code": "database_authentication_failed"},
        "storage": {"ok": True, "code": "storage_read_connected"},
    }
    assert password not in json.dumps(report)


def test_diagnostic_resolves_relative_credential_alias_without_changing_process_configuration(tmp_path, monkeypatch):
    from google.auth.credentials import AnonymousCredentials
    from app.configuration import load_configuration
    from app.connections import diagnose

    monkeypatch.chdir(tmp_path)
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}")
    def load(path, **kwargs):
        assert Path(path).is_absolute()
        assert Path(path) == credentials
        return AnonymousCredentials(), "synthetic-project"
    monkeypatch.setattr("google.auth.load_credentials_from_file", load)
    monkeypatch.setattr("google.cloud.storage.Client", lambda **kwargs: nullcontext(
        SimpleNamespace(list_blobs=lambda *args, **kwargs: iter(()))))
    previous = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    report = diagnose(load_configuration({"GCS_BUCKET_NAME": "synthetic-bucket", "GCP_KEY_PATH": "credentials.json"}))
    assert report["storage"] == {"ok": True, "code": "storage_read_connected"}
    assert os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") == previous


def test_storage_permission_error_is_sanitized_and_sql_status_remains_visible(monkeypatch):
    from google.api_core.exceptions import Forbidden
    from google.auth.credentials import AnonymousCredentials
    from app.configuration import load_configuration
    from app.connections import diagnose

    monkeypatch.setattr("google.auth.default", lambda **kwargs: (AnonymousCredentials(), "synthetic-project"))
    def deny(*args, **kwargs):
        raise Forbidden("SyntheticSensitiveContentMustNotAppear")
    monkeypatch.setattr("google.cloud.storage.Client", lambda **kwargs: nullcontext(SimpleNamespace(list_blobs=deny)))
    report = diagnose(load_configuration({"GCS_BUCKET_NAME": "synthetic-bucket"}))
    assert report == {
        "database": {"ok": False, "code": "database_configuration_missing"},
        "storage": {"ok": False, "code": "storage_forbidden"},
    }
    assert "SyntheticSensitiveContentMustNotAppear" not in json.dumps(report)


def test_non_postgres_url_is_rejected_before_creating_a_database(tmp_path):
    from app.configuration import load_configuration
    from app.connections import diagnose

    target = tmp_path / "not_created.sqlite"
    report = diagnose(load_configuration({"DATABASE_URL": "sqlite:///" + target.as_posix()}))
    assert report["database"] == {"ok": False, "code": "database_unsupported"}
    assert not target.exists()
