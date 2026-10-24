"""Public SQL operator script on an exclusive PostgreSQL 16 laboratory."""
from contextlib import closing
import os
from pathlib import Path

import psycopg2
from psycopg2 import sql
import pytest
from sqlalchemy.engine import make_url


SCRIPT=Path(__file__).resolve().parents[1]/'scripts/preparar_roles_oficial.sql'
OFFICIAL=('fama_oficial_app','fama_oficial_migrador')


def connect(url, database):
    address=url.set(database=database)
    return psycopg2.connect(**address.translate_connect_args(username='user',database='dbname'),
                            **address.query,connect_timeout=5)


@pytest.fixture
def laboratory():
    reference=os.environ.get('FAMA_TEST_OFFICIAL_ROLES_ADMIN_URL_FILE')
    if not reference:
        pytest.skip('Requires an explicitly selected exclusive PostgreSQL laboratory')
    address=make_url(Path(reference).read_text(encoding='utf-8'))
    assert address.host=='127.0.0.1' and address.database=='postgres' and address.port not in (5432,5433)
    with closing(connect(address,'postgres')) as admin:
        admin.autocommit=True
        with admin.cursor() as cursor:
            cursor.execute('SHOW server_version_num')
            assert 160000<=int(cursor.fetchone()[0])<170000
            cursor.execute("SELECT datname FROM pg_database WHERE datname NOT IN ('postgres','template0','template1')")
            assert cursor.fetchall()==[]
            for name in ('fama_oficial','fama_pruebas'):
                cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
            for name in ('fama_app','fama_migrador'):
                cursor.execute(sql.SQL('CREATE ROLE {} LOGIN NOCREATEDB NOCREATEROLE').format(sql.Identifier(name)))
    with connect(address,'fama_pruebas') as decoy, decoy.cursor() as cursor:
        cursor.execute('CREATE TABLE preservado(id integer PRIMARY KEY); INSERT INTO preservado VALUES (42)')
    try:
        yield address
    finally:
        with closing(connect(address,'postgres')) as admin:
            admin.autocommit=True
            with admin.cursor() as cursor:
                for name in ('fama_oficial','fama_pruebas'):
                    cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                for name in (*OFFICIAL,'fama_app','fama_migrador','official_preparer'):
                    cursor.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(name)))


def execute_script(address,database='fama_oficial'):
    with connect(address,database) as connection, connection.cursor() as cursor:
        cursor.execute(SCRIPT.read_text(encoding='utf-8'))


def test_operator_prepares_only_official_roles_and_restricts_daily_ddl(laboratory):
    execute_script(laboratory)
    with connect(laboratory,'fama_oficial') as connection, connection.cursor() as cursor:
        cursor.execute("SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
                       "FROM pg_roles WHERE rolname IN ('fama_oficial_app','fama_oficial_migrador') ORDER BY rolname")
        assert cursor.fetchall()==[(OFFICIAL[0],True,False,False,False,False,False),
                                   (OFFICIAL[1],True,False,False,False,False,False)]
        for role,can_create in ((OFFICIAL[0],False),(OFFICIAL[1],True)):
            cursor.execute("SELECT has_database_privilege(%s,'fama_oficial','CONNECT'),"
                           "has_database_privilege(%s,'fama_oficial','TEMPORARY'),"
                           "has_schema_privilege(%s,'public','USAGE'),has_schema_privilege(%s,'public','CREATE')",
                           (role,role,role,role))
            assert cursor.fetchone()==(True,False,True,can_create)
        for role in ('fama_app','fama_migrador'):
            cursor.execute("SELECT has_database_privilege(%s,'fama_oficial','CONNECT')",(role,))
            assert cursor.fetchone()==(False,)
        cursor.execute('SET ROLE fama_oficial_migrador; CREATE TABLE migration_probe(id integer)')
        cursor.execute('RESET ROLE; SET ROLE fama_oficial_app')
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute('CREATE TABLE forbidden(id integer)')
    with connect(laboratory,'fama_pruebas') as connection, connection.cursor() as cursor:
        cursor.execute('SELECT id FROM preservado')
        assert cursor.fetchall()==[(42,)]


@pytest.mark.parametrize('existing',[
    'CREATE TABLE public.existing_table(id integer)',
    'CREATE FUNCTION public.existing_function() RETURNS integer LANGUAGE sql AS $$ SELECT 1 $$',
    "CREATE TYPE public.existing_type AS ENUM ('known')",
    'CREATE SCHEMA existing_schema',
])
def test_operator_preserves_nonempty_databases_without_tables(laboratory,existing):
    with connect(laboratory,'fama_oficial') as connection, connection.cursor() as cursor:
        cursor.execute(existing)
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        execute_script(laboratory)
    with connect(laboratory,'fama_oficial') as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'fama_oficial_%'")
        assert cursor.fetchone()==(0,)
        cursor.execute("SELECT has_database_privilege('fama_app','fama_oficial','CONNECT')")
        assert cursor.fetchone()==(True,)


def test_wrong_database_preserves_test_data_and_creates_no_official_identity(laboratory):
    with pytest.raises(psycopg2.errors.InvalidParameterValue):
        execute_script(laboratory,'fama_pruebas')
    with connect(laboratory,'fama_pruebas') as connection, connection.cursor() as cursor:
        cursor.execute('SELECT id FROM preservado')
        assert cursor.fetchall()==[(42,)]
        cursor.execute("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'fama_oficial_%'")
        assert cursor.fetchone()==(0,)


def test_existing_identity_is_not_overwritten_or_completed_implicitly(laboratory):
    with connect(laboratory,'fama_oficial') as connection, connection.cursor() as cursor:
        cursor.execute('CREATE ROLE fama_oficial_app NOLOGIN CREATEDB')
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        execute_script(laboratory)
    with connect(laboratory,'fama_oficial') as connection, connection.cursor() as cursor:
        cursor.execute("SELECT rolname,rolcanlogin,rolcreatedb FROM pg_roles WHERE rolname LIKE 'fama_oficial_%'")
        assert cursor.fetchall()==[(OFFICIAL[0],False,True)]
        cursor.execute("SELECT has_database_privilege('fama_app','fama_oficial','CONNECT')")
        assert cursor.fetchone()==(True,)


def test_database_owner_with_createrole_can_prepare_without_being_superuser(laboratory):
    with connect(laboratory,'postgres') as connection, connection.cursor() as cursor:
        cursor.execute('CREATE ROLE official_preparer LOGIN CREATEROLE NOSUPERUSER')
        cursor.execute('ALTER DATABASE fama_oficial OWNER TO official_preparer')
    with connect(laboratory,'fama_oficial') as connection, connection.cursor() as cursor:
        cursor.execute('SET ROLE official_preparer')
        cursor.execute(SCRIPT.read_text(encoding='utf-8'))
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone()==(False,)
        cursor.execute("SELECT has_schema_privilege('fama_oficial_app','public','CREATE'),"
                       "has_schema_privilege('fama_oficial_migrador','public','CREATE')")
        assert cursor.fetchone()==(False,True)
