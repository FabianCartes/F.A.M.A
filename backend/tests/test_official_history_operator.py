"""Official operator CLI with real SQL and hidden terminal input at its external seam."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import text

from tests.test_history_transfer import history
from tests.test_official_schema_preparation import official, prepare


@pytest.fixture
def official_history(history, official, tmp_path):
    result, _ = prepare(official)
    assert result.returncode == 0, result.stdout + result.stderr
    reference = tmp_path / 'selected-source.env'
    reference.write_text('DATABASE_URL=' + history[0].url.render_as_string(hide_password=False) + '\n', encoding='utf-8')
    return history, official, reference


def operator(selected, operation='plan', *arguments, password='SyntheticMigrator2026!', interactive=True, cancel=False, warning=False):
    history, official, reference = selected
    program = '''
import getpass,json,runpy,sys
from unittest.mock import patch
data=json.loads(sys.stdin.readline())
effect=getpass.GetPassWarning if data['warning'] else EOFError if data['cancel'] else None
with patch('sys.stdin.isatty',return_value=data['interactive']),patch('getpass.getpass',return_value=data['password'],side_effect=effect):
    runpy.run_module('scripts.trasladar_historia_oficial',run_name='__main__')
'''
    environment = {k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment.update(PYTHONUTF8='1', PYTHON_DOTENV_DISABLED='1',
                       DATABASE_URL='postgresql://wrong:NeverExposeThis@127.0.0.1:1/wrong',
                       PGSERVICE='missing-inherited-service', PGHOSTADDR='127.0.0.2')
    result = subprocess.run([sys.executable, '-c', program, '--config-dir', str(official[0]),
        '--source-env-file', str(reference), operation, *arguments],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        input=json.dumps({'password':password,'interactive':interactive,'cancel':cancel,'warning':warning})+'\n',
        capture_output=True, text=True, encoding='utf-8', timeout=30)
    return result, json.loads(result.stdout) if result.stdout.strip() else {}


def apply(selected, digest, **options):
    selected[0][0].dispose()
    return operator(selected, 'apply', '--apply', '--confirm-source', selected[0][0].url.database,
                    '--confirm-target', 'fama_oficial', '--expect-digest', digest, **options)


def test_operator_previews_and_copies_to_official_using_an_unsaved_hidden_password(official_history):
    result, plan = operator(official_history, interactive=False, cancel=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert plan['code'] == 'history_transfer_ready'
    assert plan['target_database'] == 'fama_oficial'
    result, report = apply(official_history, plan['digest'])
    assert result.returncode == 0, result.stdout + result.stderr
    assert report['code'] == 'history_transferred'
    assert report['migrator_password_saved'] is False
    with official_history[1][1].connect() as connection:
        assert connection.scalar(text('SELECT id_usuario FROM usuario')) == 9
        assert connection.scalar(text('SELECT id_prediccion FROM prediccion')) == 111
    for file in official_history[1][0].parent.rglob('*'):
        if file.is_file():
            assert b'SyntheticMigrator2026!' not in file.read_bytes()
    assert 'NeverExposeThis' not in result.stdout + result.stderr
    assert 'SyntheticMigrator2026!' not in result.stdout + result.stderr


@pytest.mark.parametrize('options,code', [
    ({'password':''}, 'official_history_password_required'),
    ({'password':'RejectedSyntheticPassword!'}, 'official_history_authentication_failed'),
    ({'interactive':False}, 'official_history_terminal_required'),
    ({'warning':True}, 'official_history_terminal_required'),
    ({'cancel':True}, 'official_history_cancelled'),
])
def test_failed_or_nonhidden_password_input_keeps_official_empty(official_history, options, code):
    _, plan = operator(official_history)
    result, report = apply(official_history, plan['digest'], **options)
    assert result.returncode == 1
    assert report == {'code':code}
    with official_history[1][1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM usuario')) == 0
    assert 'RejectedSyntheticPassword!' not in result.stdout + result.stderr


def test_changed_history_and_repeated_transfer_are_rejected_without_overwriting(official_history):
    _, old = operator(official_history)
    with official_history[0][0].begin() as connection:
        connection.execute(text("UPDATE usuario SET nombre_completo='Updated history'"))
    result, report = apply(official_history, old['digest'])
    assert result.returncode == 1
    assert report == {'code':'history_source_changed'}
    _, current = operator(official_history)
    assert apply(official_history, current['digest'])[0].returncode == 0
    result, report = apply(official_history, current['digest'])
    assert result.returncode == 1
    assert report == {'code':'history_target_not_empty'}
    with official_history[1][1].connect() as connection:
        assert connection.scalar(text('SELECT nombre_completo FROM usuario')) == 'Updated history'
        assert connection.scalar(text('SELECT count(*) FROM usuario')) == 1


def test_completed_official_profile_is_not_reopened_for_transfer(official_history):
    from app.configuration import InstallationStore
    store = InstallationStore(official_history[1][0])
    current = store.read()
    store.save(values=current['values'], completed=True)
    result, report = operator(official_history)
    assert result.returncode == 1
    assert report == {'code':'official_history_configuration_invalid'}


def test_other_source_clients_block_copy_and_are_not_terminated(official_history):
    _, plan = operator(official_history)
    with official_history[0][0].connect() as other:
        other.execute(text('SELECT 1'))
        result, report = apply(official_history, plan['digest'])
        assert result.returncode == 1
        assert report == {'code':'official_history_source_busy'}
        assert other.scalar(text('SELECT 42')) == 42
    with official_history[1][1].connect() as target:
        assert target.scalar(text('SELECT count(*) FROM usuario')) == 0


def test_source_routing_query_is_rejected_before_opening_a_connection(official_history):
    _, plan = operator(official_history)
    changed = official_history[0][0].url.set(query={'hostaddr':'127.0.0.2'})
    official_history[2].write_text('DATABASE_URL=' + changed.render_as_string(hide_password=False) + '\n', encoding='utf-8')
    result, report = apply(official_history, plan['digest'])
    assert result.returncode == 1
    assert report == {'code':'official_history_configuration_invalid'}
