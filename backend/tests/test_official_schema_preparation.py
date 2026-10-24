"""Official schema CLI, restricted SQL roles, real migrations; external GCS simulated."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.test_cloud_node import node


@pytest.fixture
def official(tmp_path):
    reference = os.environ.get('FAMA_TEST_HISTORY_ADMIN_URL_FILE')
    if not reference:
        pytest.skip('Requires exclusive local PostgreSQL laboratory')
    base = make_url(Path(reference).read_text())
    assert base.host == '127.0.0.1' and base.port not in (5432,5433,5434) and base.database == 'postgres'
    admin = create_engine(base,isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        connection.execute(text('CREATE DATABASE fama_oficial TEMPLATE template0'))
    operator = create_engine(base.set(database='fama_oficial'))
    try:
        with operator.begin() as connection:
            connection.exec_driver_sql((Path(__file__).resolve().parents[1]/'scripts/preparar_roles_oficial.sql').read_text())
            connection.execute(text("ALTER ROLE fama_oficial_migrador PASSWORD 'SyntheticMigrator2026!'"))
            connection.execute(text("ALTER ROLE fama_oficial_app PASSWORD 'SyntheticApplication2026!'"))
        credentials = tmp_path/'application_default_credentials.json'
        credentials.write_text('{}')
        directory = tmp_path/'official-profile'
        result = node('--config-dir',directory,'prepare','--project','proyectotesis-fama',
            '--bucket','fama-audio-records-2026','--connection-name','proyectotesis-fama:us-central1:fama-postgres-pruebas',
            '--database','fama_oficial','--user','fama_oficial_app','--credentials-file',credentials,
            '--proxy-port',base.port,'--web-origin','http://localhost:3010', password='SyntheticApplication2026!\n')
        assert result.returncode == 0,result.stdout+result.stderr
        yield directory/'native',operator
    finally:
        operator.dispose()
        with admin.connect() as connection:
            connection.execute(text('DROP DATABASE fama_oficial WITH (FORCE)'))
            connection.execute(text('DROP ROLE IF EXISTS fama_oficial_app,fama_oficial_migrador'))
        admin.dispose()


def prepare(official, *, password='SyntheticMigrator2026!', interactive=True, warning=False, cancel=False, pg_environment=None):
    program='''
import getpass,json,runpy,sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from google.auth.credentials import AnonymousCredentials
data=json.loads(sys.stdin.readline())
effect=getpass.GetPassWarning if data['warning'] else EOFError if data['cancel'] else None
with patch('sys.stdin.isatty',return_value=data['interactive']),patch('getpass.getpass',return_value=data['password'],side_effect=effect),patch(
    'google.auth.load_credentials_from_file',return_value=(AnonymousCredentials(),'proyectotesis-fama')),patch(
    'google.cloud.storage.Client',side_effect=lambda **kwargs:nullcontext(SimpleNamespace(list_blobs=lambda *a,**k:iter(())))):
    runpy.run_module('scripts.preparar_esquema_oficial',run_name='__main__')
'''
    environment={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment.update(PYTHONUTF8='1',PYTHON_DOTENV_DISABLED='1')
    environment.update(pg_environment or {})
    result=subprocess.run([sys.executable,'-c',program,'--config-dir',str(official[0]),'--apply'],
        cwd=Path(__file__).resolve().parents[1],env=environment,input=json.dumps({'password':password,'interactive':interactive,'warning':warning,'cancel':cancel})+'\n',
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    return result,json.loads(result.stdout) if result.stdout.strip() else {}


def test_operator_prepares_current_schema_and_daily_permissions_without_saving_migrator_password(official):
    result,report=prepare(official)
    assert result.returncode == 0,result.stdout+result.stderr
    assert report['code']=='official_schema_prepared'
    assert report['revision']=='0003_autonomy'
    assert report['runtime_permissions_ready'] is True
    for file in official[0].parent.rglob('*'):
        if file.is_file():
            assert b'SyntheticMigrator2026!' not in file.read_bytes()
    with official[1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM usuario'))==0
        assert connection.scalar(text("SELECT has_table_privilege('fama_oficial_app','public.usuario','INSERT')")) is True
        assert connection.scalar(text("SELECT has_table_privilege('fama_oficial_app','public.alembic_version','UPDATE')")) is False


@pytest.mark.parametrize('options,code', [
    ({'password':''},'official_schema_password_required'),
    ({'password':'RejectedSyntheticPassword!'},'official_schema_authentication_failed'),
    ({'interactive':False},'official_schema_terminal_required'),
    ({'warning':True},'official_schema_terminal_required'),
    ({'cancel':True},'official_schema_cancelled'),
])
def test_failed_or_nonhidden_input_never_creates_schema(official,options,code):
    result,report=prepare(official,**options)
    assert result.returncode==1
    assert report=={'code':code}
    assert options.get('password','UnrelatedNeverAppear') not in result.stdout+result.stderr or options.get('password')==''
    with official[1].connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'"))==0


def test_unknown_unversioned_content_is_preserved_without_stamp(official):
    with official[1].begin() as connection:
        connection.execute(text('CREATE TABLE preserved(id integer)'))
        connection.execute(text('INSERT INTO preserved VALUES(42)'))
    result,report=prepare(official)
    assert result.returncode==1
    assert report=={'code':'official_schema_not_prepared','schema_code':'schema_incompatible'}
    with official[1].connect() as connection:
        assert connection.scalar(text('SELECT id FROM preserved'))==42
        assert connection.scalar(text("SELECT to_regclass('public.alembic_version')")) is None


def test_migrator_with_unexpected_privileges_is_rejected_before_DDL(official):
    with official[1].begin() as connection:
        connection.execute(text('ALTER ROLE fama_oficial_migrador INHERIT'))
    result,report=prepare(official)
    assert result.returncode==1
    assert report=={'code':'official_schema_migrator_permissions_invalid'}


def test_inherited_libpq_routing_is_ignored(official):
    result,report=prepare(official,pg_environment={'PGSERVICE':'missing-unrelated-service','PGHOSTADDR':'127.0.0.2'})
    assert result.returncode==0,result.stdout+result.stderr
    assert report['code']=='official_schema_prepared'


def test_repeated_preparation_preserves_existing_business_rows(official):
    assert prepare(official)[0].returncode==0
    with official[1].begin() as connection:
        connection.execute(text("INSERT INTO usuario(id_usuario,correo_electronico,hash_contrasena,rol,nombre_completo,activo,fecha_creacion) "
            "VALUES(99,'preserved@fama.test','synthetic-hash','administrador','Conservar',true,now())"))
    result,report=prepare(official)
    assert result.returncode==0,result.stdout+result.stderr
    assert report['history_transferred'] is False
    with official[1].connect() as connection:
        assert connection.scalar(text('SELECT id_usuario FROM usuario'))==99
