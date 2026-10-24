"""Configuración pública del nodo, con archivos y secretos sintéticos."""
import pytest


def test_unconfigured_node_has_no_implicit_database_or_bucket():
    from app.configuration import load_configuration

    settings = load_configuration({})

    assert settings.database_url is None
    assert settings.bucket_name is None
    assert settings.installation_status == "required"
    assert "database" in settings.missing_requirements
    assert "bucket" in settings.missing_requirements


def test_completed_installation_and_secret_references_survive_restart(tmp_path):
    from app.configuration import InstallationStore, load_configuration

    secret = tmp_path / "database.secret"
    secret.write_text("postgresql://operador:prueba-secreta@localhost/fama_prueba\n")
    directory = tmp_path / "node"
    store = InstallationStore(directory)
    store.save({"DATABASE_URL_FILE": str(secret), "GCS_BUCKET_NAME": "bucket-pruebas"}, completed=True)

    restarted = load_configuration({"FAMA_CONFIG_DIR": str(directory)})
    assert restarted.installation_status == "completed"
    assert restarted.database_url == "postgresql://operador:prueba-secreta@localhost/fama_prueba"
    assert restarted.bucket_name == "bucket-pruebas"
    assert "prueba-secreta" not in repr(restarted)
    assert "prueba-secreta" not in (directory / "installation.json").read_text()
    with pytest.raises(ValueError):
        store.save({}, completed=False)


def test_incomplete_security_blocks_readiness_without_reopening_completed_installation(tmp_path):
    from app.configuration import InstallationStore, load_configuration

    InstallationStore(tmp_path).save({"GCS_BUCKET_NAME": "bucket-pruebas"}, completed=True)
    settings = load_configuration({"FAMA_CONFIG_DIR": str(tmp_path), "DATABASE_URL": "sqlite://"})
    assert settings.installation_status == "completed"
    assert set(settings.missing_requirements) == {"web_origin", "jwt_key", "rate_limit_key"}


def test_storage_requires_an_explicit_bucket_before_contacting_google():
    from unittest.mock import patch
    from app.configuration import activate_configuration, get_configuration, load_configuration, ConfigurationError

    previous = get_configuration()
    activate_configuration(load_configuration({}))
    from app.services.storage import upload_audio_to_gcp_sync
    try:
        with patch("google.cloud.storage.Client", side_effect=AssertionError("No cloud call expected")):
            with pytest.raises(ConfigurationError, match="storage_configuration_missing"):
                upload_audio_to_gcp_sync(b"synthetic", "test.wav")
    finally:
        activate_configuration(previous)


def test_ingestion_without_bucket_reports_configuration_before_contacting_google(tmp_path):
    from unittest.mock import patch
    from app.configuration import activate_configuration, get_configuration, load_configuration
    from app.services.ingestion import IngestionService

    previous = get_configuration()
    activate_configuration(load_configuration({}))
    try:
        service = IngestionService(local_base_dir=tmp_path / "raw", local_processed_dir=tmp_path / "processed")
        with patch("google.cloud.storage.Client", side_effect=AssertionError("Unexpected cloud call")):
            status = service.get_storage_status()
        assert status["connected"] is False
        assert status["error"] == "storage_configuration_missing"
    finally:
        activate_configuration(previous)


@pytest.mark.parametrize("key", ["JWT_SECRET_KEY", "FAMA_RATE_LIMIT_KEY"])
def test_whitespace_is_not_a_configured_security_key(key):
    from app.configuration import load_configuration

    configuration = load_configuration({key: " " * 40})
    assert ("jwt_key" if key == "JWT_SECRET_KEY" else "rate_limit_key") in configuration.missing_requirements


def test_resolved_secret_can_be_inherited_without_making_child_configuration_ambiguous(tmp_path):
    from app.configuration import load_configuration, ConfigurationError

    secret = tmp_path / "database.secret"
    secret.write_text("postgresql://synthetic:password@localhost/test")
    environment = {"DATABASE_URL_FILE": str(secret), "DATABASE_URL": secret.read_text()}
    assert load_configuration(environment).database_url == secret.read_text()
    environment["DATABASE_URL"] = "postgresql://different:password@localhost/test"
    with pytest.raises(ConfigurationError, match="secret_source_ambiguous"):
        load_configuration(environment)


def test_google_project_is_part_of_persisted_runtime_configuration(tmp_path):
    from app.configuration import InstallationStore, load_configuration

    InstallationStore(tmp_path).save({"GOOGLE_CLOUD_PROJECT": "synthetic-project"})
    assert load_configuration({"FAMA_CONFIG_DIR": str(tmp_path)}).values["GOOGLE_CLOUD_PROJECT"] == "synthetic-project"


def test_declared_ensemble_default_survives_installation_restart(tmp_path):
    import json
    from app.configuration import InstallationStore, load_configuration

    declaration = json.dumps({"version": 1, "enabled": ["chilean-birds-ensemble"],
                              "default": "chilean-birds-ensemble"})
    InstallationStore(tmp_path).save({"FAMA_ENSEMBLES_JSON": declaration})

    restarted = load_configuration({"FAMA_CONFIG_DIR": str(tmp_path)})
    assert restarted.values["FAMA_ENSEMBLES_JSON"] == declaration


@pytest.mark.parametrize("declaration", [
    "invalid-json", "null", "[]", "{}",
    '{"version":true,"enabled":[],"default":null}',
    '{"version":1,"enabled":["unknown"],"default":"unknown"}',
    '{"version":1,"enabled":["chilean-birds-ensemble","chilean-birds-ensemble"],"default":null}',
    '{"version":1,"enabled":[],"default":"chilean-birds-ensemble"}',
    '{"version":1,"enabled":[1],"default":null}',
    '{"version":1,"enabled":[],"default":null,"extra":true}',
])
def test_invalid_ensemble_declaration_preserves_installation(tmp_path, declaration):
    from app.configuration import ConfigurationError, InstallationStore, load_configuration

    store = InstallationStore(tmp_path)
    store.save({"GCS_BUCKET_NAME": "synthetic-bucket"})
    original = store.path.read_bytes()
    with pytest.raises(ConfigurationError):
        store.save({"FAMA_ENSEMBLES_JSON": declaration})
    assert store.path.read_bytes() == original
    with pytest.raises(ConfigurationError):
        load_configuration({"FAMA_ENSEMBLES_JSON": declaration})


def test_explicit_activation_can_replace_inherited_application_settings(monkeypatch):
    from app.configuration import activate_configuration, get_configuration, load_configuration

    previous = get_configuration()
    monkeypatch.setenv("DATABASE_URL", "postgresql://old:synthetic@127.0.0.1/old")
    monkeypatch.setenv("GCP_KEY_PATH", "old-synthetic-credentials.json")
    monkeypatch.setenv("FAMA_SESSION_IDLE_SECONDS", "9999")
    try:
        activate_configuration(load_configuration({"GCS_BUCKET_NAME": "selected-test-bucket"}), replace_environment=True)
        assert "DATABASE_URL" not in __import__("os").environ
        assert "GCP_KEY_PATH" not in __import__("os").environ
        assert "FAMA_SESSION_IDLE_SECONDS" not in __import__("os").environ
        assert get_configuration().bucket_name == "selected-test-bucket"
    finally:
        activate_configuration(previous)
