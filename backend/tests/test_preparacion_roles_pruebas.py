"""Script de operador en un servidor PostgreSQL local exclusivo y efímero."""
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy.engine import make_url


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preparar_roles_pruebas.sql"
PASSWORD = "SoloPruebaLocalRoles2026!"


@contextmanager
def connection(address):
    database = psycopg2.connect(
        **address.translate_connect_args(username="user", database="dbname"),
        connect_timeout=5,
        options="-c statement_timeout=15000 -c lock_timeout=3000",
    )
    database.autocommit = True
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def isolated_server():
    raw = os.environ.get("FAMA_TEST_ROLES_POSTGRES_URL")
    if not raw:
        pytest.skip("Requiere un servidor local exclusivo mediante FAMA_TEST_ROLES_POSTGRES_URL")
    admin = make_url(raw)
    assert admin.host in {"127.0.0.1", "localhost"}
    assert admin.database == "postgres" and admin.username == "postgres"
    with connection(admin) as database, database.cursor() as cursor:
        cursor.execute("CREATE ROLE fama_roles_operador LOGIN CREATEROLE PASSWORD %s", (PASSWORD,))
        cursor.execute("CREATE DATABASE fama_pruebas OWNER fama_roles_operador")
    operator = admin.set(database="fama_pruebas", username="fama_roles_operador", password=PASSWORD)
    try:
        yield admin, operator
    finally:
        with connection(admin) as database, database.cursor() as cursor:
            cursor.execute("DROP DATABASE IF EXISTS fama_pruebas WITH (FORCE)")
            for name in ("fama_app", "fama_migrador", "fama_roles_operador"):
                cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (name,))
                if cursor.fetchone()[0]:
                    cursor.execute(f"DROP OWNED BY {name}")
                    cursor.execute(f"DROP ROLE {name}")


def prepare(address):
    with connection(address) as database, database.cursor() as cursor:
        cursor.execute(SCRIPT.read_text(encoding="utf-8"))
        return cursor.fetchall()


def test_migrador_puede_migrar_y_aplicacion_no_puede_crear_tablas(isolated_server):
    admin, operator = isolated_server
    with connection(operator) as database, database.cursor() as cursor:
        cursor.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
    assert prepare(operator) == [
        ("fama_app", True, False, False, False, True, False),
        ("fama_migrador", True, False, False, False, True, True),
    ]
    for name in ("fama_app", "fama_migrador"):
        address = operator.set(username=name, password=PASSWORD)
        with pytest.raises(psycopg2.OperationalError):
            with connection(address):
                pass
        with connection(admin.set(database="fama_pruebas")) as database, database.cursor() as cursor:
            cursor.execute(f"ALTER ROLE {name} PASSWORD %s", (PASSWORD,))

    migrator = operator.set(username="fama_migrador", password=PASSWORD)
    environment = dict(os.environ, DATABASE_URL=migrator.render_as_string(hide_password=False), PYTHON_DOTENV_DISABLED="1")
    environment.pop("DATABASE_URL_FILE", None)
    result = subprocess.run(
        [sys.executable, "-m", "app.schema", "upgrade", "--apply"],
        cwd=SCRIPT.parents[1], env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"code": "schema_current", "revision": "0004_integration"}

    with connection(operator.set(username="fama_app", password=PASSWORD)) as database, database.cursor() as cursor:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("CREATE TABLE public.no_permitida (id integer)")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("CREATE SCHEMA no_permitido")


def test_rechaza_otra_base_sin_crear_roles(isolated_server):
    admin, _ = isolated_server
    with pytest.raises(psycopg2.errors.InvalidParameterValue):
        prepare(admin)
    with connection(admin) as database, database.cursor() as cursor:
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('fama_app', 'fama_migrador')")
        assert cursor.fetchall() == []


def test_rechaza_base_con_datos_y_conserva_su_contenido(isolated_server):
    _, operator = isolated_server
    with connection(operator) as database, database.cursor() as cursor:
        cursor.execute("CREATE TABLE public.historia (valor text)")
        cursor.execute("INSERT INTO public.historia VALUES ('conservar')")
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        prepare(operator)
    with connection(operator) as database, database.cursor() as cursor:
        cursor.execute("SELECT valor FROM public.historia")
        assert cursor.fetchall() == [("conservar",)]
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('fama_app', 'fama_migrador')")
        assert cursor.fetchall() == []


def test_un_rol_preexistente_aborta_todo_sin_cambiar_su_clave(isolated_server):
    admin, operator = isolated_server
    with connection(admin) as database, database.cursor() as cursor:
        cursor.execute("CREATE ROLE fama_app LOGIN CREATEDB PASSWORD %s", (PASSWORD,))
    with pytest.raises(psycopg2.errors.DuplicateObject):
        prepare(operator)
    with connection(admin) as database, database.cursor() as cursor:
        cursor.execute("SELECT rolname, rolcreatedb FROM pg_roles WHERE rolname IN ('fama_app', 'fama_migrador')")
        assert cursor.fetchall() == [("fama_app", True)]
    with connection(operator.set(username="fama_app", password=PASSWORD)) as database, database.cursor() as cursor:
        cursor.execute("SELECT current_user")
        assert cursor.fetchone() == ("fama_app",)
