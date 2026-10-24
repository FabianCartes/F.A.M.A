"""Permisos diarios mediante el script SQL del operador y sesiones reales."""
from pathlib import Path
import json
import os
import subprocess
import sys

import psycopg2
import pytest

from app.schema import check_schema, upgrade_schema
from tests.test_preparacion_roles_pruebas import PASSWORD, connection, isolated_server, prepare


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "permisos_tablas_pruebas.sql"


@pytest.fixture
def migrated_database(isolated_server):
    admin, operator = isolated_server
    prepare(operator)
    with connection(admin.set(database="fama_pruebas")) as database, database.cursor() as cursor:
        for name in ("fama_migrador", "fama_app"):
            cursor.execute(f"ALTER ROLE {name} PASSWORD %s", (PASSWORD,))
    migrator = operator.set(username="fama_migrador", password=PASSWORD)
    runtime = operator.set(username="fama_app", password=PASSWORD)
    assert upgrade_schema(migrator.render_as_string(hide_password=False)).code == "schema_current"
    return admin, migrator, runtime


def grant(address):
    with connection(address) as database, database.cursor() as cursor:
        cursor.execute(SCRIPT.read_text(encoding="utf-8"))
        return cursor.fetchone()


def test_aplicacion_opera_datos_y_secuencias_sin_poder_migrar(migrated_database):
    _, migrator, runtime = migrated_database
    assert grant(migrator) == ("runtime_permissions_ready",)
    assert check_schema(runtime.render_as_string(hide_password=False)).code == "schema_current"
    with connection(runtime) as database, database.cursor() as cursor:
        cursor.execute("""INSERT INTO public.usuario
            (correo_electronico, hash_contrasena, rol, nombre_completo, activo, fecha_creacion)
            VALUES ('prueba@fama.test', 'hash_sintetico', 'investigador', 'Prueba SQL', true, now())
            RETURNING id_usuario""")
        identifier = cursor.fetchone()[0]
        assert identifier > 0
        cursor.execute("UPDATE public.usuario SET nombre_completo='Actualizado' WHERE id_usuario=%s", (identifier,))
        assert grant(migrator) == ("runtime_permissions_ready",)
        cursor.execute("SELECT nombre_completo FROM public.usuario WHERE id_usuario=%s", (identifier,))
        assert cursor.fetchone() == ("Actualizado",)
        cursor.execute("DELETE FROM public.usuario WHERE id_usuario=%s RETURNING id_usuario", (identifier,))
        assert cursor.fetchone() == (identifier,)
        for statement in (
            "CREATE TABLE public.no_permitida (id integer)",
            "ALTER TABLE public.usuario ADD COLUMN no_permitida integer",
            "TRUNCATE public.cuota_acceso",
            "UPDATE public.alembic_version SET version_num='alterada'",
            "DELETE FROM public.alembic_version",
        ):
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute(statement)


def test_operator_autonomy_command_prompts_without_persisting_password_and_is_repeatable(migrated_database):
    _, migrator, runtime = migrated_database
    for _ in range(2):
        result = subprocess.run([sys.executable, '-m', 'scripts.actualizar_autonomia_pruebas',
                                 '--apply', '--password-stdin', '--port', str(migrator.port)], input=PASSWORD + '\n',
                                cwd=SCRIPT.parents[1], env=dict(os.environ, PYTHON_DOTENV_DISABLED='1'),
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {'code': 'autonomy_update_ready', 'revision': '0004_integration'}
        assert PASSWORD not in result.stdout + result.stderr
    with connection(runtime) as database, database.cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(current_user, 'solicitud_dataset', 'INSERT'), "
                       "has_table_privilege(current_user, 'alembic_version', 'UPDATE')")
        assert cursor.fetchone() == (True, False)


@pytest.mark.parametrize("wrong_database", [True, False])
def test_rechaza_destino_o_identidad_antes_de_conceder_permisos(migrated_database, wrong_database):
    admin, _, runtime = migrated_database
    address = admin if wrong_database else admin.set(database="fama_pruebas")
    with pytest.raises(psycopg2.errors.InvalidParameterValue):
        grant(address)
    with connection(runtime) as database, database.cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(current_user, 'public.usuario', 'SELECT')")
        assert cursor.fetchone() == (False,)


@pytest.mark.parametrize("revision", ["0001_core", "desconocida"])
def test_rechaza_revision_distinta_sin_conceder_permisos(migrated_database, revision):
    _, migrator, runtime = migrated_database
    with connection(migrator) as database, database.cursor() as cursor:
        cursor.execute("UPDATE public.alembic_version SET version_num=%s", (revision,))
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        grant(migrator)
    with connection(runtime) as database, database.cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(current_user, 'public.usuario', 'SELECT')")
        assert cursor.fetchone() == (False,)


def test_normaliza_permisos_directos_anteriores_sin_alterar_la_revision(migrated_database):
    _, migrator, runtime = migrated_database
    with connection(migrator) as database, database.cursor() as cursor:
        cursor.execute("GRANT ALL PRIVILEGES ON public.usuario, public.alembic_version TO fama_app WITH GRANT OPTION")
        cursor.execute("GRANT ALL PRIVILEGES ON SEQUENCE public.usuario_id_usuario_seq TO fama_app")
    assert grant(migrator) == ("runtime_permissions_ready",)
    with connection(runtime) as database, database.cursor() as cursor:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("UPDATE public.alembic_version SET version_num='alterada'")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("SELECT setval('public.usuario_id_usuario_seq', 10, true)")
        cursor.execute("""SELECT
            has_table_privilege(current_user, 'public.usuario', 'TRUNCATE'),
            has_table_privilege(current_user, 'public.usuario', 'SELECT WITH GRANT OPTION'),
            has_table_privilege(current_user, 'public.usuario', 'TRIGGER')""")
        assert cursor.fetchone() == (False, False, False)
        cursor.execute("SELECT version_num FROM public.alembic_version")
        assert cursor.fetchone() == ("0004_integration",)


@pytest.mark.parametrize("change", ["owner", "missing"])
def test_tabla_ajena_o_ausente_aborta_sin_permisos_parciales(migrated_database, change):
    admin, migrator, runtime = migrated_database
    with connection(migrator) as database, database.cursor() as cursor:
        cursor.execute("INSERT INTO public.cuota_acceso VALUES ('conservar', 3, 100)")
    with connection(admin.set(database="fama_pruebas")) as database, database.cursor() as cursor:
        cursor.execute("ALTER TABLE public.usuario OWNER TO postgres" if change == "owner"
                       else "DROP TABLE public.usuario CASCADE")
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        grant(migrator)
    with connection(runtime) as database, database.cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(current_user, 'public.cuota_acceso', 'SELECT')")
        assert cursor.fetchone() == (False,)
    with connection(migrator) as database, database.cursor() as cursor:
        cursor.execute("SELECT intentos FROM public.cuota_acceso WHERE clave_hash='conservar'")
        assert cursor.fetchone() == (3,)
