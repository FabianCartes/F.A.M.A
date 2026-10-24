"""CLI de operador contra PostgreSQL efímero; nunca utiliza backend/.env."""
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture
def database_url():
    address = os.environ.get("FAMA_TEST_POSTGRES_URL")
    if not address:
        pytest.skip("Requiere PostgreSQL aislado mediante FAMA_TEST_POSTGRES_URL")
    url = make_url(address).set(drivername="postgresql+psycopg2")
    name = "fama_stage1_" + uuid.uuid4().hex
    operator = create_engine(url, isolation_level="AUTOCOMMIT")
    with operator.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with operator.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        operator.dispose()


def migrate(url, *arguments):
    environment = dict(os.environ, DATABASE_URL=url, PYTHON_DOTENV_DISABLED="1")
    environment.pop("DATABASE_URL_FILE", None)
    result = subprocess.run(
        [sys.executable, "-m", "app.schema", *arguments],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=30,
    )
    return result, json.loads(result.stdout) if result.stdout.strip() else {}


def test_operator_cli_rejects_unsupported_database_before_creating_files(tmp_path):
    target = tmp_path / "must-not-be-created.sqlite"
    result, report = migrate("sqlite:///" + target.as_posix(), "upgrade", "--apply")
    assert result.returncode == 1
    assert report == {"code": "database_unsupported", "revision": None}
    assert not target.exists()


def test_autonomy_upgrade_from_access_preserves_data_and_does_not_invent_legacy_authorship(database_url):
    from sqlalchemy import inspect
    result, report = migrate(database_url, "upgrade", "--apply", "--revision", "0002_access")
    assert result.returncode == 0, result.stderr
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO prediccion (id_prediccion, ruta_audio_prueba, etiqueta_predicha, "
                                "dataset_name, confianza, fecha_prediccion) VALUES (901, 'raw_audios/synthetic.wav', 'Chucao', 'Aves', .8, now())"))
        connection.execute(text("INSERT INTO retroalimentacion (id_retroalimentacion, id_prediccion, id_usuario, "
                                "fue_correcta, procesado, fecha_retroalimentacion) VALUES (901, 901, 1, true, true, now())"))
        connection.execute(text("INSERT INTO feedback_sync (id_retroalimentacion, dataset_name, storage_class, class_label, "
                                "object_key, local_relative_path, sha256, status, attempts) VALUES "
                                "(901, 'Aves', 'Chucao', 'Chucao', 'datasets/Aves/Chucao/feedback_901.wav', "
                                "'Aves/Chucao/feedback_901.wav', :digest, 'pending', 0)"), {'digest': 'a' * 64})
    result, report = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 0, result.stderr
    assert report == {"code": "schema_current", "revision": "0004_integration"}
    with engine.connect() as connection:
        assert 'solicitud_dataset' in inspect(connection).get_table_names()
        row = connection.execute(text("SELECT incorporated_by, incorporated_at, status FROM feedback_sync WHERE id_retroalimentacion=901")).one()
        assert tuple(row) == (None, None, 'pending')
    engine.dispose()


def test_empty_database_is_migrated_explicitly_and_repeated_upgrade_is_safe(database_url):
    result, report = migrate(database_url, "status")
    assert result.returncode == 0, result.stderr
    assert report == {"code": "schema_empty", "revision": None}

    result, report = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 0, result.stderr
    assert report == {"code": "schema_current", "revision": "0004_integration"}
    result, report = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 0, result.stderr
    assert report["code"] == "schema_current"


@pytest.mark.parametrize("replacement", [None, "rol IN ('Administrador', 'Investigador')"])
def test_revision_does_not_hide_a_missing_or_modified_role_constraint(database_url, replacement):
    result, _ = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 0
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE usuario DROP CONSTRAINT chk_usuario_rol"))
        if replacement:
            connection.execute(text(f"ALTER TABLE usuario ADD CONSTRAINT chk_usuario_rol CHECK ({replacement})"))
    engine.dispose()

    result, report = migrate(database_url, "status")
    assert result.returncode == 1
    assert report == {"code": "schema_incompatible", "revision": "0004_integration"}
    result, report = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 1
    assert report["code"] == "schema_incompatible"


def test_known_upgrade_preserves_an_existing_account(database_url):
    from sqlalchemy.orm import Session
    from app.services.auth import create_user, get_user_by_email, verify_password

    result, report = migrate(database_url, "upgrade", "--apply", "--revision", "0001_core")
    assert result.returncode == 0, result.stderr
    assert report == {"code": "schema_outdated", "revision": "0001_core"}
    engine = create_engine(database_url)
    try:
        with Session(engine) as db:
            existing = create_user(db, "continuidad@fama.test", "TemporalStage12026!", "Cuenta conservada")
            user_id = existing.id
        result, report = migrate(database_url, "upgrade", "--apply")
        assert result.returncode == 0, result.stderr
        assert report["code"] == "schema_current"
        with Session(engine) as db:
            existing = get_user_by_email(db, "continuidad@fama.test")
            assert existing.id == user_id
            assert existing.nombre_completo == "Cuenta conservada"
            assert verify_password("TemporalStage12026!", existing.password_hash)
    finally:
        engine.dispose()


@pytest.mark.parametrize("unknown_object", ["TABLE ajeno (id INTEGER)", "VIEW ajeno AS SELECT 1 AS id"])
def test_unversioned_nonempty_schema_requires_controlled_adoption(database_url, unknown_object):
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE " + unknown_object))
    engine.dispose()
    result, report = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 1
    assert report == {"code": "schema_incompatible", "revision": None}
    result, report = migrate(database_url, "status")
    assert result.returncode == 1
    assert report == {"code": "schema_incompatible", "revision": None}


def test_upgrade_requires_explicit_apply_and_never_uses_dotenv(database_url):
    result, _ = migrate(database_url, "upgrade")
    assert result.returncode == 2
    result, report = migrate(database_url, "status")
    assert report["code"] == "schema_empty"
    environment = dict(os.environ, PYTHON_DOTENV_DISABLED="0")
    environment.pop("DATABASE_URL", None)
    result = subprocess.run([sys.executable, "-m", "app.schema", "status"],
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"code": "database_configuration_missing", "revision": None}


def test_daily_account_operations_work_without_schema_creation_privileges(database_url):
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.orm import Session
    from app.services.auth import create_user, get_user_by_email

    result, _ = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 0
    role = "fama_runtime_" + uuid.uuid4().hex
    operator = create_engine(database_url)
    runtime = None
    try:
        with operator.begin() as connection:
            connection.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'SyntheticPermissionCheck2026'"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"))
            connection.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))
        runtime = create_engine(make_url(database_url).set(username=role, password="SyntheticPermissionCheck2026"))
        with Session(runtime) as db:
            create_user(db, "sin-ddl@fama.test", "TemporalStage12026!", "Sin permiso DDL")
        with Session(runtime) as db:
            assert get_user_by_email(db, "sin-ddl@fama.test").nombre_completo == "Sin permiso DDL"
        with pytest.raises(ProgrammingError):
            with runtime.begin() as connection:
                connection.execute(text("CREATE TABLE prohibida (id INTEGER)"))
    finally:
        if runtime is not None:
            runtime.dispose()
        with operator.begin() as connection:
            connection.execute(text(f"DROP OWNED BY {role}"))
            connection.execute(text(f"DROP ROLE {role}"))
        operator.dispose()


def test_migrated_node_starts_and_authenticates_without_implicit_admin_or_real_artifacts(database_url, tmp_path):
    result, _ = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 0
    source = Path(__file__).resolve().parents[1]
    isolated = tmp_path / "runtime" / "backend"
    isolated.mkdir(parents=True)

    def source_only(directory, entries):
        return [name for name in entries if name in {"__pycache__", "data", "checkpoints", ".pytest_cache"}
                or (Path(directory, name).is_file() and Path(name).suffix not in {".py", ".yaml", ".yml"})]

    for package in ("app", "poc", "ml_core", "training", "migrations"):
        shutil.copytree(source / package, isolated / package, ignore=source_only)
    for name in ("main.py", "database.py", "dataset_references.py"):
        shutil.copy2(source / name, isolated / name)
    environment = dict(os.environ, DATABASE_URL=database_url, GCS_BUCKET_NAME="isolated-unused-bucket",
                       JWT_SECRET_KEY="j" * 40, FAMA_RATE_LIMIT_KEY="r" * 40,
                       FAMA_WEB_ORIGIN="https://fama.test", PYTHONPATH=str(isolated),
                       PYTHON_DOTENV_DISABLED="1", CUDA_VISIBLE_DEVICES="-1",
                       ADMIN_INITIAL_EMAIL="must-not-be-created@fama.test", ADMIN_INITIAL_PASSWORD="TemporalStage12026!")
    for key in ("FAMA_CONFIG_DIR", "DATABASE_URL_FILE", "JWT_SECRET_KEY_FILE", "FAMA_RATE_LIMIT_KEY_FILE",
                "GOOGLE_APPLICATION_CREDENTIALS", "GCP_KEY_PATH"):
        environment.pop(key, None)
    script = '''
from fastapi.testclient import TestClient
import main
from app.database import SessionLocal
from app.services.auth import create_user
with TestClient(main.app, base_url="https://fama.test", headers={"Origin": "https://fama.test"}) as client:
    assert client.get("/ready").status_code == 200
    assert client.get("/api/installation/status").json() == {"status": "configured"}
    assert client.post("/api/auth/login", json={"email": "must-not-be-created@fama.test", "password": "TemporalStage12026!"}).status_code == 401
    with SessionLocal() as db:
        create_user(db, "admin@fama.test", "TemporaryPassword2026!", "Administrador temporal", rol="administrador")
    response = client.post("/api/auth/login", json={"email": "admin@fama.test", "password": "TemporaryPassword2026!"})
    assert response.status_code == 200, response.text
    assert client.get("/api/auth/me").json()["email"] == "admin@fama.test"
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=isolated, env=environment,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("invalid", [
    {"FAMA_WEB_ORIGIN": "http://untrusted.example"},
    {"JWT_SECRET_KEY": "fama_bioacoustic_secret_key_mlops_2026"},
    {"FAMA_ACCESS_LIMITS_JSON": '{"unknown_policy": {}}'},
])
def test_invalid_security_blocks_ml_startup_even_when_schema_is_current(database_url, invalid):
    result, _ = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 0
    environment = dict(os.environ, DATABASE_URL=database_url, GCS_BUCKET_NAME="test-bucket",
                       JWT_SECRET_KEY="j" * 40, FAMA_RATE_LIMIT_KEY="r" * 40,
                       FAMA_WEB_ORIGIN="https://fama.test", FAMA_ACCESS_LIMITS_JSON="{}",
                       PYTHON_DOTENV_DISABLED="1")
    environment.update(invalid)
    environment.pop("FAMA_CONFIG_DIR", None)
    script = '''
import sys
from importlib.abc import MetaPathFinder
class UnavailableModels(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "torch":
            raise RuntimeError("ML must not start with invalid security settings")
sys.meta_path.insert(0, UnavailableModels())
from fastapi.testclient import TestClient
import main
with TestClient(main.app) as client:
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"code": "configuration_invalid"}
    assert client.get("/api/installation/status").json() == {"status": "configured"}
'''
    result = subprocess.run([sys.executable, "-c", script], env=environment,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_dev_upgrade_preserves_access_schema_and_matches_all_runtime_models(database_url):
    import importlib
    from sqlalchemy import inspect
    from app.schema import matches_schema
    from app.database import Base
    for module in (Path(__file__).resolve().parents[1]/"app"/"models").glob("*.py"):
        if module.stem != "__init__": importlib.import_module("app.models."+module.stem)
    result, report = migrate(database_url, "upgrade", "--apply", "--revision", "0003_autonomy")
    assert result.returncode == 0, result.stderr
    assert report == {"code": "schema_outdated", "revision": "0003_autonomy"}
    result, report = migrate(database_url, "upgrade", "--apply")
    assert result.returncode == 0, result.stderr
    engine = create_engine(database_url)
    with engine.connect() as connection:
        from sqlalchemy import MetaData
        expected = MetaData()
        for table in Base.metadata.sorted_tables: table.to_metadata(expected)
        assert matches_schema(connection, expected)
        assert {"model_evaluation", "dataset_import", "sesion_web"}.issubset(inspect(connection).get_table_names())
    engine.dispose()
