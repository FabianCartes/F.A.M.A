"""Local operator adoption via CLI, real SQL/files, simulated external GCS only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text

from tests.test_history_transfer import history, cli, apply


@pytest.fixture
def adoption(history, tmp_path):
    result, plan = cli(history)
    assert result.returncode == 0
    assert apply(history, plan['digest'])[0].returncode == 0
    operator = history[1]
    role = 'history_runtime_' + uuid.uuid4().hex
    password = 'SyntheticDailyOnly2026!'
    with operator.begin() as connection:
        connection.execute(text(f'CREATE ROLE "{role}" LOGIN NOINHERIT PASSWORD :password'), {'password':password})
        connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        connection.execute(text(f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
        connection.execute(text(f'REVOKE ALL ON alembic_version FROM "{role}"'))
        connection.execute(text(f'GRANT SELECT ON alembic_version TO "{role}"'))
        connection.execute(text(f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))
    from app.configuration import InstallationStore, load_configuration, protect_private_directory
    directory = tmp_path / 'installation'
    directory.mkdir()
    protect_private_directory(directory)
    values = {'FAMA_WEB_ORIGIN':'http://localhost:3010', 'FAMA_ALLOW_INSECURE_LOOPBACK':'1',
              'GOOGLE_CLOUD_PROJECT':'synthetic-project', 'GCS_BUCKET_NAME':'synthetic-bucket'}
    for key, value in {'DATABASE_URL':operator.url.set(username=role,password=password).render_as_string(hide_password=False),
                       'JWT_SECRET_KEY':'synthetic-jwt-' * 5, 'FAMA_RATE_LIMIT_KEY':'synthetic-limits-' * 5}.items():
        secret = directory / key.lower()
        secret.write_text(value, encoding='utf-8')
        values[key + '_FILE'] = str(secret)
    store = InstallationStore(directory)
    store.save(values)
    from app.runtime import RuntimeDirectory
    runtime = (tmp_path / 'runtime').resolve()
    RuntimeDirectory(load_configuration({'FAMA_CONFIG_DIR':str(directory)}), str(runtime)).prepare()
    store.select_runtime(runtime)
    try:
        yield directory, history, runtime
    finally:
        with operator.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{role}"'))
            connection.execute(text(f'DROP ROLE "{role}"'))


def adopt_cli(adoption, *arguments, fail_close=False):
    directory = adoption[0]
    program = '''
import os,runpy,sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from google.auth.credentials import AnonymousCredentials
replacer=os.replace
def failing_replace(source,destination):
    if str(destination).endswith('installation.json'):
        raise OSError('synthetic local publication failure')
    return replacer(source,destination)
with patch('google.auth.default',return_value=(AnonymousCredentials(),'synthetic-project')), patch(
    'google.cloud.storage.Client',side_effect=lambda **kwargs:nullcontext(SimpleNamespace(list_blobs=lambda *a,**k:iter(())))), patch(
    'os.replace',side_effect=failing_replace if sys.argv.pop(1)=='fail' else replacer):
    runpy.run_module('app.history_adoption',run_name='__main__')
'''
    environment = {k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment['PYTHONUTF8'] = '1'
    result = subprocess.run([sys.executable,'-c',program,'fail' if fail_close else 'ok',
        '--config-dir',str(directory),'--user-id','9',*arguments],cwd=Path(__file__).resolve().parents[1],
        env=environment,capture_output=True,text=True,encoding='utf-8',timeout=25)
    return result, json.loads(result.stdout) if result.stdout.strip() else {}


def test_operator_adopts_existing_administrator_without_creating_or_resetting_it(adoption):
    directory, history, _ = adoption
    from app.configuration import InstallationStore
    with history[1].connect() as connection:
        before = connection.execute(text('SELECT * FROM usuario')).all()
    result, plan = adopt_cli(adoption)
    assert result.returncode == 0, result.stdout + result.stderr
    assert plan['code'] == 'history_adoption_ready'
    assert InstallationStore(directory).read()['completed'] is False
    result, report = adopt_cli(adoption,'--apply','--confirm-database',history[1].url.database)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report['code'] == 'history_adopted'
    assert InstallationStore(directory).read()['completed'] is True
    with history[1].connect() as connection:
        assert connection.execute(text('SELECT * FROM usuario')).all() == before
        events = connection.execute(text('SELECT action,actor_id,subject_user_id FROM evento_seguridad')).all()
        assert events == [('account.operator_adopted',None,9)]
    assert 'preserved@fama.test' not in result.stdout + result.stderr
    assert history[3]['usuario']['hash_contrasena'] not in result.stdout + result.stderr


def test_adoption_resumes_after_local_publication_failure_without_duplicate_audit(adoption):
    directory, history, _ = adoption
    from app.configuration import InstallationStore
    result, report = adopt_cli(adoption,'--apply','--confirm-database',history[1].url.database,fail_close=True)
    assert result.returncode == 1
    assert report == {'code':'history_adoption_pending'}
    assert InstallationStore(directory).read()['completed'] is False
    with history[1].connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM evento_seguridad WHERE action='account.operator_adopted'")) == 1
    result, report = adopt_cli(adoption,'--apply','--confirm-database',history[1].url.database)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report['code'] == 'history_adopted'
    with history[1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM evento_seguridad')) == 1
        assert connection.scalar(text('SELECT count(*) FROM usuario')) == 1


@pytest.mark.parametrize('change', ["activo=false", "rol='investigador'"])
def test_adoption_never_reactivates_or_promotes_a_user(adoption, change):
    with adoption[1][1].begin() as connection:
        connection.execute(text('UPDATE usuario SET ' + change))
    result, report = adopt_cli(adoption,'--apply','--confirm-database',adoption[1][1].url.database)
    assert result.returncode == 1
    assert report == {'code':'history_adoption_active_administrator_required'}
    from app.configuration import InstallationStore
    assert InstallationStore(adoption[0]).read()['completed'] is False


def test_changed_account_cannot_complete_an_older_adoption_intent(adoption):
    args = ('--apply','--confirm-database',adoption[1][1].url.database)
    assert adopt_cli(adoption,*args,fail_close=True)[1] == {'code':'history_adoption_pending'}
    with adoption[1][1].begin() as connection:
        connection.execute(text("UPDATE usuario SET hash_contrasena='changed-after-intent'"))
    result, report = adopt_cli(adoption,*args)
    assert result.returncode == 1
    assert report == {'code':'history_adoption_identity_changed'}
    from app.configuration import InstallationStore
    assert InstallationStore(adoption[0]).read()['completed'] is False


def test_completed_installation_cannot_be_reopened_by_adoption(adoption):
    args = ('--apply','--confirm-database',adoption[1][1].url.database)
    assert adopt_cli(adoption,*args)[0].returncode == 0
    result, report = adopt_cli(adoption,*args)
    assert result.returncode == 1
    assert report == {'code':'history_adoption_installation_completed'}
    with adoption[1][1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM evento_seguridad')) == 1


def test_adoption_rejects_wrong_database_confirmation(adoption):
    result, report = adopt_cli(adoption,'--apply','--confirm-database','wrong_database')
    assert result.returncode == 1
    assert report == {'code':'history_adoption_database_confirmation_required'}


def test_adoption_checks_runtime_ownership_before_finalizing(adoption):
    from app.configuration import InstallationStore,load_configuration
    from app.runtime import RuntimeDirectory
    configuration = load_configuration({'FAMA_CONFIG_DIR':str(adoption[0])})
    with RuntimeDirectory(configuration).lease():
        result, _ = adopt_cli(adoption,'--apply','--confirm-database',adoption[1][1].url.database)
    assert result.returncode == 1
    assert InstallationStore(adoption[0]).read()['completed'] is False
    with adoption[1][1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM evento_seguridad')) == 0


def test_initial_signup_intent_is_not_converted_into_history_adoption(adoption):
    (adoption[0]/'finalization.json').write_text('{}')
    result, report = adopt_cli(adoption,'--apply','--confirm-database',adoption[1][1].url.database)
    assert result.returncode == 1
    assert report == {'code':'history_adoption_initial_signup_pending'}
