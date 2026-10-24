"""Operator CLI with real PostgreSQL; substitute only hidden terminal input."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_official_database_roles import laboratory, connect, execute_script


BACKEND=Path(__file__).resolve().parents[1]
PASSWORDS=['SyntheticMigratorOnly2026!', 'SyntheticApplicationOnly2026!']


@pytest.fixture
def access(laboratory):
    execute_script(laboratory)
    with connect(laboratory,'fama_oficial') as connection,connection.cursor() as cursor:
        cursor.execute('ALTER ROLE fama_oficial_migrador PASSWORD %s',(PASSWORDS[0],))
        cursor.execute('ALTER ROLE fama_oficial_app PASSWORD %s',(PASSWORDS[1],))
    return laboratory


def cli(address,passwords=PASSWORDS,interactive=True,cancel=False,warning=False,pg_environment=None):
    program='''
import getpass,json,runpy,sys
from unittest.mock import patch
data=json.loads(sys.stdin.readline())
with patch('sys.stdin.isatty',return_value=data['interactive']), patch(
    'getpass.getpass',side_effect=EOFError if data['cancel'] else getpass.GetPassWarning if data['warning'] else data['passwords']):
    runpy.run_module('scripts.comprobar_acceso_sql_oficial',run_name='__main__')
'''
    environment={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment.update(PYTHONUTF8='1',PYTHON_DOTENV_DISABLED='1',
                       DATABASE_URL='postgresql://wrong-user:unrelated-secret@127.0.0.1:1/other')
    environment.update(pg_environment or {})
    return subprocess.run([sys.executable,'-c',program,'--port',str(address.port)],
                          cwd=BACKEND,env=environment,
                          input=json.dumps({'passwords':passwords,'interactive':interactive,'cancel':cancel,'warning':warning})+'\n',
                          capture_output=True,text=True,encoding='utf-8',timeout=35)


def test_operator_checks_both_official_logins_and_permissions_read_only(access):
    result=cli(access)
    assert result.returncode==0,result.stderr+result.stdout
    report=json.loads(result.stdout)
    assert report['code']=='official_sql_access_verified'
    assert report['database']=='fama_oficial'
    assert [(r['user'],r['schema_create'],r['read_only']) for r in report['users']]==[
        ('fama_oficial_migrador',True,True),('fama_oficial_app',False,True)]
    for password in PASSWORDS:
        assert password not in result.stdout+result.stderr
    assert 'unrelated-secret' not in result.stdout+result.stderr
    with connect(access,'fama_oficial') as connection,connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
        assert cursor.fetchone()==(0,)


@pytest.mark.parametrize('grant',[
    'GRANT CREATE ON SCHEMA public TO fama_oficial_app',
    'ALTER ROLE fama_oficial_app CREATEDB',
    'GRANT fama_oficial_migrador TO fama_oficial_app',
])
def test_successful_login_does_not_accept_excessive_application_permissions(access,grant):
    with connect(access,'fama_oficial') as connection,connection.cursor() as cursor:
        cursor.execute(grant)
    result=cli(access)
    assert result.returncode==1,result.stdout
    assert json.loads(result.stdout)=={'code':'official_sql_permissions_invalid','user':'fama_oficial_app'}


@pytest.mark.parametrize('index',[0,1])
def test_wrong_password_is_sanitized_without_echo_or_DSN(access,index):
    passwords=list(PASSWORDS)
    passwords[index]='RejectedSyntheticSecret2026!'
    result=cli(access,passwords=passwords)
    assert result.returncode==1
    assert json.loads(result.stdout)=={'code':'official_sql_authentication_failed',
        'user':('fama_oficial_migrador','fama_oficial_app')[index]}
    assert not result.stderr
    assert all(password not in result.stdout for password in passwords)


@pytest.mark.parametrize('options,code',[
    ({'interactive':False},'official_sql_terminal_required'),
    ({'cancel':True},'official_sql_check_cancelled'),
    ({'warning':True},'official_sql_terminal_required'),
])
def test_terminal_requirements_and_cancellation_never_fall_back_to_visible_input(access,options,code):
    result=cli(access,**options)
    assert result.returncode==1
    assert json.loads(result.stdout)=={'code':code}
    assert not result.stderr


@pytest.mark.parametrize('index',[0,1])
def test_empty_password_is_rejected_without_attempting_a_blank_login(access,index):
    passwords=list(PASSWORDS)
    passwords[index]=''
    result=cli(access,passwords=passwords)
    assert result.returncode==1
    assert json.loads(result.stdout)=={'code':'official_sql_password_required',
        'user':('fama_oficial_migrador','fama_oficial_app')[index]}


def test_probe_preserves_existing_rows_and_reports_tables_without_migrating(access):
    with connect(access,'fama_oficial') as connection,connection.cursor() as cursor:
        cursor.execute('CREATE TABLE public.existing_rows(id integer); INSERT INTO public.existing_rows VALUES (42)')
    result=cli(access)
    assert result.returncode==0,result.stdout
    assert [row['public_tables'] for row in json.loads(result.stdout)['users']]==[1,1]
    with connect(access,'fama_oficial') as connection,connection.cursor() as cursor:
        cursor.execute('SELECT id FROM public.existing_rows')
        assert cursor.fetchall()==[(42,)]


def test_password_with_URI_and_shell_punctuation_is_passed_as_a_password(access):
    password="SyntheticOnly:@/%'\"$`\\2026!"
    with connect(access,'fama_oficial') as connection,connection.cursor() as cursor:
        cursor.execute('ALTER ROLE fama_oficial_app PASSWORD %s',(password,))
    result=cli(access,passwords=[PASSWORDS[0],password])
    assert result.returncode==0,result.stderr+result.stdout
    assert password not in result.stdout+result.stderr


def test_operator_check_ignores_inherited_libpq_service_and_connection_settings(access,tmp_path):
    result=cli(access,pg_environment={
        'PGSERVICE':'unrelated-service','PGSERVICEFILE':str(tmp_path/'absent-service.conf'),
        'PGHOSTADDR':'127.0.0.2','PGPORT':'1','PGDATABASE':'unrelated',
        'PGUSER':'unrelated','PGPASSWORD':'unrelated-private-value',
        'PGSSLMODE':'require','PGOPTIONS':'-c default_transaction_read_only=off'})
    assert result.returncode==0,result.stdout
    report=json.loads(result.stdout)
    assert report['database']=='fama_oficial' and all(r['read_only'] for r in report['users'])
    assert 'unrelated-private-value' not in result.stdout+result.stderr
