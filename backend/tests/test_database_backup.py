"""Public operator CLI against an explicitly selected disposable PostgreSQL server."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from contextlib import closing

import psycopg2
from psycopg2 import sql
import pytest
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]


def connect(url):
    address = make_url(url)
    return psycopg2.connect(**address.translate_connect_args(username='user', database='dbname'),
                            **address.query, connect_timeout=5)


def cli(profile, *arguments):
    environment = {k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment['PYTHON_DOTENV_DISABLED'] = '1'
    return subprocess.run([sys.executable, '-m', 'app.node', '--config-dir', str(profile), *map(str,arguments)],
                          cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=90)


@pytest.fixture
def databases(tmp_path):
    raw = os.environ.get('FAMA_TEST_BACKUP_ADMIN_URL_FILE')
    tools = os.environ.get('FAMA_TEST_BACKUP_PG_BIN')
    if not raw or not tools:
        pytest.skip('Requiere laboratorio PostgreSQL exclusivo y herramientas indicadas explícitamente')
    admin = make_url(Path(raw).read_text(encoding='utf-8'))
    assert admin.host == '127.0.0.1' and admin.database == 'postgres'
    assert admin.port != 5433
    prefix = 'fama_backup_test_' + uuid.uuid4().hex[:10]
    names = [prefix+'_source', prefix+'_target']
    with closing(connect(admin)) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            for name in names:
                cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
    source = admin.set(database=names[0]).render_as_string(hide_password=False)
    target = admin.set(database=names[1]).render_as_string(hide_password=False)
    from app.schema import upgrade_schema
    assert upgrade_schema(source).code == 'schema_current'
    with connect(source) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO usuario(correo_electronico,hash_contrasena,rol,nombre_completo,activo,fecha_creacion) "
                       "VALUES ('synthetic@example.test','synthetic-hash','administrador','Cuenta sintética',true,'2026-01-01 00:00:00+00')")
    from app.configuration import InstallationStore
    profile = tmp_path/'profile'
    profile.mkdir()
    secret = profile/'source-url'
    secret.write_text(source, encoding='utf-8')
    InstallationStore(profile).save({'DATABASE_URL_FILE':str(secret), 'GCS_BUCKET_NAME':'synthetic-bucket'}, completed=True)
    target_file = profile/'target-url'
    target_file.write_text(target, encoding='utf-8')
    try:
        yield {'source':source,'target':target,'profile':profile,'target_file':target_file,
               'tools':tools,'backup':tmp_path/'backup','secret':secret}
    finally:
        with closing(connect(admin)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                for name in names:
                    assert name.startswith(prefix)
                    cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def test_backup_can_be_restored_exactly_into_an_empty_separate_database(databases):
    d = databases
    result = cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools'])
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)['code'] == 'database_backup_created'
    manifest = json.loads((d['backup']/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['tables']['public.usuario']['rows'] == 1
    assert manifest['revision'] == '0004_integration'
    assert 'synthetic-hash' not in (d['backup']/'manifest.json').read_text(encoding='utf-8')
    assert not list(d['backup'].glob('.pgpass-*'))
    restored = cli(d['profile'], 'restore', '--backup', d['backup'], '--target-url-file', d['target_file'], '--pg-bin', d['tools'])
    assert restored.returncode == 0, restored.stderr + restored.stdout
    assert json.loads(restored.stdout)['code'] == 'database_restore_verified'
    from app.schema import check_schema
    assert check_schema(d['target']).code == 'schema_current'
    with connect(d['target']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT correo_electronico,hash_contrasena,rol,activo FROM usuario')
        assert cursor.fetchall() == [('synthetic@example.test','synthetic-hash','administrador',True)]
        cursor.execute("SELECT nextval('usuario_id_usuario_seq')")
        assert cursor.fetchone() == (2,)


@pytest.mark.parametrize('existing', ['table', 'schema', 'function'])
def test_restore_preserves_a_destination_with_any_existing_user_object(databases, existing):
    d = databases
    assert cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools']).returncode == 0
    statements = {'table': 'CREATE TABLE keep_me (value text)', 'schema':'CREATE SCHEMA keep_me',
                  'function': "CREATE FUNCTION keep_me() RETURNS integer LANGUAGE sql AS 'SELECT 7'"}
    with connect(d['target']) as connection, connection.cursor() as cursor:
        cursor.execute(statements[existing])
    result = cli(d['profile'], 'restore', '--backup', d['backup'], '--target-url-file', d['target_file'], '--pg-bin', d['tools'])
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'restore_target_not_empty'}
    with connect(d['target']) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.usuario')")
        assert cursor.fetchone() == (None,)
        if existing == 'function':
            cursor.execute('SELECT keep_me()')
            assert cursor.fetchone() == (7,)


def test_source_database_is_never_a_restore_destination(databases):
    d = databases
    assert cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools']).returncode == 0
    result = cli(d['profile'], 'restore', '--backup', d['backup'], '--target-url-file', d['secret'], '--pg-bin', d['tools'])
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'restore_source_forbidden'}
    with connect(d['source']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT nombre_completo FROM usuario')
        assert cursor.fetchone() == ('Cuenta sintética',)


def test_corrupted_archive_is_rejected_before_writing_to_target(databases):
    d = databases
    assert cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools']).returncode == 0
    archive = d['backup']/'database.dump'
    data = bytearray(archive.read_bytes())
    data[-1] ^= 1
    archive.write_bytes(data)
    result = cli(d['profile'], 'restore', '--backup', d['backup'], '--target-url-file', d['target_file'], '--pg-bin', d['tools'])
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'backup_integrity_mismatch'}
    with connect(d['target']) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.usuario')")
        assert cursor.fetchone() == (None,)


def test_existing_backup_directory_and_invalid_configuration_are_preserved_without_secret_output(databases):
    d = databases
    d['backup'].mkdir()
    existing = d['backup']/'keep.txt'
    existing.write_text('preserve', encoding='utf-8')
    result = cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools'])
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'backup_destination_exists'}
    assert existing.read_text() == 'preserve'
    d['secret'].write_text('invalid:NeverDiscloseThisPassword@', encoding='utf-8')
    invalid = cli(d['profile'], 'backup', '--directory', d['backup'].parent/'other', '--pg-bin', d['tools'])
    assert invalid.returncode == 1
    assert 'NeverDiscloseThisPassword' not in invalid.stdout + invalid.stderr
    assert json.loads(invalid.stdout) == {'code':'backup_configuration_invalid'}


def test_backup_waits_for_a_separate_schema_maintenance_window(databases):
    d = databases
    with connect(d['source']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(5065941)')
        result = cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools'])
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'backup_source_busy'}
    assert not d['backup'].exists()


def test_restore_recovers_the_saved_snapshot_after_the_source_has_changed(databases):
    d = databases
    assert cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools']).returncode == 0
    with connect(d['source']) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE usuario SET nombre_completo='Cambio posterior'")
    result = cli(d['profile'], 'restore', '--backup', d['backup'], '--target-url-file', d['target_file'], '--pg-bin', d['tools'])
    assert result.returncode == 0, result.stdout
    with connect(d['target']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT nombre_completo FROM usuario')
        assert cursor.fetchone() == ('Cuenta sintética',)


def test_a_restore_error_rolls_back_and_removes_its_temporary_password_file(databases):
    d = databases
    assert cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools']).returncode == 0
    restricted = 'fama_restore_limited_' + uuid.uuid4().hex[:10]
    with connect(d['target']) as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD %s').format(sql.Identifier(restricted)), ('SyntheticOnly2026!',))
    try:
        target = make_url(d['target']).set(username=restricted, password='SyntheticOnly2026!')
        d['target_file'].write_text(target.render_as_string(hide_password=False), encoding='utf-8')
        result = cli(d['profile'], 'restore', '--backup', d['backup'], '--target-url-file', d['target_file'], '--pg-bin', d['tools'])
        assert result.returncode == 1
        assert json.loads(result.stdout) == {'code':'restore_failed'}
        assert 'SyntheticOnly2026!' not in result.stdout + result.stderr
        assert not list(d['backup'].glob('.pgpass-*'))
        with connect(d['target']) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.usuario')")
            assert cursor.fetchone() == (None,)
    finally:
        with connect(d['source']) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(restricted)))


@pytest.mark.parametrize('database', ['postgres','template0','template1'])
def test_restore_refuses_system_databases_before_attempting_to_connect(databases, database):
    d = databases
    assert cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools']).returncode == 0
    forbidden = make_url(d['target']).set(database=database, port=1)
    d['target_file'].write_text(forbidden.render_as_string(hide_password=False), encoding='utf-8')
    result = cli(d['profile'], 'restore', '--backup', d['backup'], '--target-url-file', d['target_file'], '--pg-bin', d['tools'])
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'restore_target_forbidden'}


def test_restore_refuses_a_database_name_that_libpq_could_interpret_as_a_connection_string(databases):
    d = databases
    assert cli(d['profile'], 'backup', '--directory', d['backup'], '--pg-bin', d['tools']).returncode == 0
    target = make_url(d['target']).set(database='host=127.0.0.1 dbname=unintended', port=1)
    d['target_file'].write_text(target.render_as_string(hide_password=False), encoding='utf-8')
    result = cli(d['profile'], 'restore', '--backup', d['backup'], '--target-url-file', d['target_file'], '--pg-bin', d['tools'])
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'backup_configuration_invalid'}
