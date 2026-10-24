"""Recovery through the operator CLI and authenticated HTTP, on an exclusive local PG16."""
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import psycopg2
from psycopg2 import sql
import pytest
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
OLD_PASSWORD = 'BeforeRecovery2026!'
NEW_PASSWORD = 'AfterRecovery2026!'
EMAIL = 'admin@example.test'


def connect(address):
    address = make_url(address)
    return psycopg2.connect(**address.translate_connect_args(username='user', database='dbname'),
                            **address.query, connect_timeout=5)


def cli(profile, *arguments, passwords=(), email=EMAIL, interactive=True, background=False, cancel=False):
    # Substitute terminal hardware only. Application, SQL, hashes and transactions remain real.
    program = '''
import json,runpy,sys
from contextlib import ExitStack
from unittest.mock import patch
p=json.loads(sys.stdin.readline())
with ExitStack() as stack:
    stack.enter_context(patch('sys.stdin.isatty',return_value=p['interactive']))
    stack.enter_context(patch('getpass.getpass',side_effect=EOFError if p['cancel'] else p['passwords']))
    stack.enter_context(patch('builtins.input',return_value=p['email']))
    runpy.run_module('app.node',run_name='__main__')
'''
    environment = {k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment['PYTHON_DOTENV_DISABLED'] = '1'
    command = [sys.executable,'-c',program,'--config-dir',str(profile),*map(str,arguments)]
    data = json.dumps({'passwords':list(passwords),'email':email,'interactive':interactive,'cancel':cancel})+'\n'
    if background:
        process = subprocess.Popen(command,cwd=BACKEND,env=environment,text=True,
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        process.stdin.write(data)
        process.stdin.close()
        process.stdin = None
        return process
    return subprocess.run(command,cwd=BACKEND,env=environment,capture_output=True,text=True,timeout=45,input=data)


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    raw = os.environ.get('FAMA_TEST_RECOVERY_ADMIN_URL_FILE')
    if not raw:
        pytest.skip('Requiere PostgreSQL local exclusivo mediante un archivo URL privado explícito')
    admin = make_url(Path(raw).read_text(encoding='utf-8'))
    assert admin.host == '127.0.0.1' and admin.database == 'postgres' and admin.port != 5433
    name = 'fama_operator_test_' + uuid.uuid4().hex[:12]
    role = name + '_app'
    password = 'SyntheticDatabaseOnly2026!'
    with closing(connect(admin)) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
            cursor.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD %s').format(sql.Identifier(role)), (password,))
    owner = admin.set(database=name)
    try:
        from app.schema import upgrade_schema
        assert upgrade_schema(owner.render_as_string(hide_password=False)).code == 'schema_current'
        from app.passwords import hash_password
        with connect(owner) as connection, connection.cursor() as cursor:
            for user_id, user_role, email in [(1,'administrador',EMAIL),(2,'investigador','researcher@example.test')]:
                cursor.execute("INSERT INTO usuario(id_usuario,correo_electronico,hash_contrasena,rol,nombre_completo,activo,fecha_creacion) "
                               "VALUES (%s,%s,%s,%s,%s,true,'2026-01-01 00:00:00+00')",
                               (user_id,email,hash_password(OLD_PASSWORD),user_role,'Cuenta '+str(user_id)))
            cursor.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
            cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(role)))
            cursor.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM {}').format(sql.Identifier(role)))
            cursor.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        app_address = owner.set(username=role,password=password)
        profile = tmp_path/'profile'
        profile.mkdir()
        secret = profile/'database-url'
        secret.write_text(app_address.render_as_string(hide_password=False),encoding='utf-8')
        from app.configuration import InstallationStore
        InstallationStore(profile).save({'DATABASE_URL_FILE':str(secret),'GCS_BUCKET_NAME':'synthetic-bucket',
            'JWT_SECRET_KEY_FILE':str(profile/'jwt'),'FAMA_RATE_LIMIT_KEY_FILE':str(profile/'rate'),
            'FAMA_WEB_ORIGIN':'https://fama.example.test'},completed=True)
        (profile/'jwt').write_text('synthetic-jwt-key-only-for-operator-recovery-2026',encoding='utf-8')
        (profile/'rate').write_text('synthetic-rate-key-only-for-operator-recovery-2026',encoding='utf-8')
        yield {'owner':owner,'address':app_address,'profile':profile,'database':name,'role':role,'secret':secret}
    finally:
        with closing(connect(admin)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                assert name.startswith('fama_operator_test_') and role == name+'_app'
                cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                cursor.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_inspection_is_read_only_and_does_not_reopen_installation(recovery):
    d = recovery
    original = (d['profile']/'installation.json').read_bytes()
    result = cli(d['profile'],'recover-admin','--user-id',1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'code':'administrator_recovery_ready','database':d['database'],
        'user':{'id':1,'email':EMAIL,'rol':'administrador','activo':True},'reactivation_required':False}
    assert (d['profile']/'installation.json').read_bytes() == original
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT count(*) FROM evento_seguridad')
        assert cursor.fetchone() == (0,)
        cursor.execute('SELECT count(*) FROM control_cuentas')
        assert cursor.fetchone() == (0,)
    assert OLD_PASSWORD not in result.stdout + result.stderr


@pytest.fixture
def web(recovery, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.database_connection import database_engine
    monkeypatch.setenv('FAMA_WEB_ORIGIN','https://fama.example.test')
    monkeypatch.setenv('FAMA_RATE_LIMIT_KEY','synthetic-rate-key-only-for-operator-recovery-2026')
    monkeypatch.delenv('FAMA_ACCESS_LIMITS_JSON',raising=False)
    from app.database import get_db
    from app.routes.auth import router as auth
    from app.routes.security import router as security
    engine = database_engine(recovery['address'].render_as_string(hide_password=False))
    sessions = sessionmaker(bind=engine)
    def database():
        with sessions() as session:
            yield session
    app = FastAPI()
    app.include_router(auth)
    app.include_router(security)
    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app,base_url='https://fama.example.test',raise_server_exceptions=False) as client:
            yield client
    finally:
        engine.dispose()


def login(client, password=OLD_PASSWORD, email=EMAIL):
    return client.post('/api/auth/login',headers={'Origin':'https://fama.example.test'},
                       json={'email':email,'password':password})


def test_operator_recovers_login_and_revokes_only_the_target_credentials(recovery, web):
    from fastapi.testclient import TestClient
    d = recovery
    token = 'r'*43
    import hashlib,time
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('INSERT INTO recuperacion_cuenta(id_usuario,token_hash,expira_en) VALUES (1,%s,%s)',
                       (hashlib.sha256(token.encode()).hexdigest(),int(time.time())+600))
    with TestClient(web.app,base_url='https://fama.example.test') as other:
        assert login(other,email='researcher@example.test').status_code == 200
        assert login(web).status_code == 200
        with connect(d['owner']) as connection, connection.cursor() as cursor:
            cursor.execute('SELECT * FROM cuota_acceso ORDER BY clave_hash')
            quotas = cursor.fetchall()
        original = (d['profile']/'installation.json').read_bytes()
        result = cli(d['profile'],'recover-admin','--user-id',1,'--apply','--confirm-database',d['database'],
                     passwords=(NEW_PASSWORD,NEW_PASSWORD))
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout) == {'code':'administrator_recovered','database':d['database'],
                                             'user_id':1,'reactivated':False}
        assert NEW_PASSWORD not in result.stdout + result.stderr
        assert (d['profile']/'installation.json').read_bytes() == original
        with connect(d['owner']) as connection, connection.cursor() as cursor:
            cursor.execute('SELECT * FROM cuota_acceso ORDER BY clave_hash')
            assert cursor.fetchall() == quotas
        assert web.get('/api/auth/me').status_code == 401
        assert other.get('/api/auth/me').status_code == 200
        assert login(web).status_code == 401
        assert login(web,password=NEW_PASSWORD).status_code == 200
        assert web.get('/api/auth/me').json()['nombre_completo'] == 'Cuenta 1'
        events = web.get('/api/security/audit').json()['events']
        recovered = [event for event in events if event['action']=='account.operator_recovered']
        assert len(recovered) == 1
        assert recovered[0]['actor_id'] is None and recovered[0]['subject_user_id'] == 1
        assert token not in json.dumps(events) and NEW_PASSWORD not in json.dumps(events)
        rejected = web.post('/api/auth/reset-password',headers={'Origin':'https://fama.example.test'},
                            json={'token':token,'new_password':'OtherSyntheticPassword2026!'})
        assert rejected.status_code == 400


def test_suspended_administrator_needs_explicit_reactivation(recovery, web):
    d = recovery
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('UPDATE usuario SET activo=false WHERE id_usuario=1')
    assert login(web).status_code == 401
    preview = cli(d['profile'],'recover-admin','--user-id',1)
    assert json.loads(preview.stdout)['reactivation_required'] is True
    refused = cli(d['profile'],'recover-admin','--user-id',1,'--apply','--confirm-database',d['database'])
    assert refused.returncode == 1
    assert json.loads(refused.stdout) == {'code':'administrator_recovery_reactivation_required'}
    result = cli(d['profile'],'recover-admin','--user-id',1,'--apply','--reactivate',
                 '--confirm-database',d['database'],passwords=(NEW_PASSWORD,NEW_PASSWORD))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['reactivated'] is True
    assert login(web,password=NEW_PASSWORD).status_code == 200
    profile = web.get('/api/auth/me').json()
    assert profile['id'] == 1 and profile['rol'] == 'administrador' and profile['activo'] is True
    events = web.get('/api/security/audit').json()['events']
    assert len([e for e in events if e['action']=='account.reactivated']) == 1
    assert len([e for e in events if e['action']=='account.operator_recovered']) == 1


def test_audit_failure_rolls_back_password_revocation_and_reactivation(recovery, web):
    d = recovery
    assert login(web).status_code == 200
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT hash_contrasena FROM usuario WHERE id_usuario=1')
        original_hash = cursor.fetchone()[0]
        cursor.execute('UPDATE usuario SET activo=false WHERE id_usuario=1')
        cursor.execute(sql.SQL('REVOKE INSERT ON evento_seguridad FROM {}').format(sql.Identifier(d['role'])))
        cursor.execute('SELECT count(*) FROM sesion_web WHERE id_usuario=1')
        sessions = cursor.fetchone()[0]
    result = cli(d['profile'],'recover-admin','--user-id',1,'--apply','--reactivate',
                 '--confirm-database',d['database'],passwords=(NEW_PASSWORD,NEW_PASSWORD))
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'administrator_recovery_unavailable'}
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT hash_contrasena,activo FROM usuario WHERE id_usuario=1')
        assert cursor.fetchone() == (original_hash,False)
        cursor.execute('SELECT count(*) FROM sesion_web WHERE id_usuario=1')
        assert cursor.fetchone() == (sessions,)
    assert NEW_PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize('case,code', [
    ('researcher','administrator_recovery_administrator_required'),
    ('missing','administrator_recovery_target_not_found'),
    ('database','administrator_recovery_database_confirmation_required'),
    ('email','administrator_recovery_identity_mismatch'),
    ('password_confirmation','administrator_recovery_password_mismatch'),
    ('noninteractive','administrator_recovery_interactive_terminal_required'),
])
def test_refused_recovery_preserves_accounts_and_events(recovery, case, code):
    d = recovery
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT * FROM usuario ORDER BY id_usuario')
        before = cursor.fetchall()
    arguments = ['recover-admin','--user-id',2 if case=='researcher' else 999 if case=='missing' else 1,
                 '--apply','--confirm-database','wrong-database' if case=='database' else d['database']]
    passwords = (NEW_PASSWORD,'DifferentPassword2026!' if case=='password_confirmation' else NEW_PASSWORD)
    result = cli(d['profile'],*arguments,passwords=passwords,
                 email='wrong@example.test' if case=='email' else EMAIL, interactive=case!='noninteractive')
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':code}
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT * FROM usuario ORDER BY id_usuario')
        assert cursor.fetchall() == before
        cursor.execute('SELECT count(*) FROM evento_seguridad')
        assert cursor.fetchone() == (0,)
    assert NEW_PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize('password',['short',' '*12,'x'*1025])
def test_password_policy_is_checked_before_mutation(recovery, password):
    d = recovery
    result = cli(d['profile'],'recover-admin','--user-id',1,'--apply','--confirm-database',d['database'],
                 passwords=(password,password))
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'administrator_recovery_password_invalid'}
    from app.passwords import verify_password
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT hash_contrasena FROM usuario WHERE id_usuario=1')
        assert verify_password(OLD_PASSWORD,cursor.fetchone()[0])


def test_initial_installation_and_incompatible_schema_are_not_repaired(recovery, tmp_path):
    d = recovery
    from app.configuration import InstallationStore
    initial = tmp_path/'initial'
    InstallationStore(initial).save(InstallationStore(d['profile']).read()['values'])
    result = cli(initial,'recover-admin','--user-id',1)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'administrator_recovery_installation_not_completed'}
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE alembic_version SET version_num='unknown'")
    result = cli(d['profile'],'recover-admin','--user-id',1)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'administrator_recovery_schema_not_current'}


def test_configuration_cannot_override_the_selected_database(recovery):
    d = recovery
    url = d['address'].set(query=dict(d['address'].query,dbname='postgres'))
    d['secret'].write_text(url.render_as_string(hide_password=False),encoding='utf-8')
    result = cli(d['profile'],'recover-admin','--user-id',1)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'administrator_recovery_configuration_invalid'}


def test_operator_can_locate_the_administrator_by_email_without_knowing_its_id(recovery, web):
    result = cli(recovery['profile'],'recover-admin','--email',' ADMIN@example.test ')
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['user']['id'] == 1
    result = cli(recovery['profile'],'recover-admin','--email',EMAIL,'--apply',
                 '--confirm-database',recovery['database'],passwords=(NEW_PASSWORD,NEW_PASSWORD))
    assert result.returncode == 0, result.stdout + result.stderr
    assert login(web,password=NEW_PASSWORD).status_code == 200


def test_email_selector_refuses_ambiguous_historical_accounts(recovery):
    d = recovery
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE usuario SET correo_electronico='ADMIN@example.test',rol='administrador' WHERE id_usuario=2")
    result = cli(d['profile'],'recover-admin','--email',EMAIL)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'administrator_recovery_identity_ambiguous'}


def test_role_is_rechecked_after_waiting_for_another_account_writer(recovery):
    import time
    d = recovery
    process = None
    with closing(connect(d['owner'])) as writer:
        try:
            with writer.cursor() as cursor:
                cursor.execute('INSERT INTO control_cuentas(id) VALUES (1) ON CONFLICT (id) DO NOTHING')
                cursor.execute('UPDATE control_cuentas SET id=id WHERE id=1')
                cursor.execute('SELECT hash_contrasena FROM usuario WHERE id_usuario=1')
                previous_hash = cursor.fetchone()[0]
            process = cli(d['profile'],'recover-admin','--user-id',1,'--apply','--confirm-database',d['database'],
                          passwords=(NEW_PASSWORD,NEW_PASSWORD),background=True)
            deadline = time.monotonic()+20
            waiting = False
            with closing(connect(d['owner'])) as observer:
                observer.autocommit = True
                while time.monotonic() < deadline:
                    with observer.cursor() as cursor:
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=%s AND usename=%s "
                            "AND wait_event_type='Lock' AND query LIKE '%%control_cuentas%%')",(d['database'],d['role']))
                        waiting = cursor.fetchone()[0]
                    if waiting or process.poll() is not None:
                        break
                    time.sleep(.05)
            assert waiting, 'The operator command must wait for the real PostgreSQL account gate'
            with writer.cursor() as cursor:
                cursor.execute("UPDATE usuario SET rol='investigador' WHERE id_usuario=1")
            writer.commit()
            output,error = process.communicate(timeout=20)
            assert process.returncode == 1, output + error
            assert json.loads(output) == {'code':'administrator_recovery_administrator_required'}
            with connect(d['owner']) as connection, connection.cursor() as cursor:
                cursor.execute('SELECT rol,hash_contrasena FROM usuario WHERE id_usuario=1')
                assert cursor.fetchone() == ('investigador',previous_hash)
                cursor.execute('SELECT count(*) FROM evento_seguridad')
                assert cursor.fetchone() == (0,)
        finally:
            writer.rollback()
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


def test_connection_loss_during_apply_requires_outcome_verification(recovery):
    import time
    d = recovery
    process = None
    with closing(connect(d['owner'])) as writer:
        try:
            with writer.cursor() as cursor:
                cursor.execute('INSERT INTO control_cuentas(id) VALUES (1) ON CONFLICT (id) DO NOTHING')
                cursor.execute('UPDATE control_cuentas SET id=id WHERE id=1')
            process = cli(d['profile'],'recover-admin','--user-id',1,'--apply','--confirm-database',d['database'],
                          passwords=(NEW_PASSWORD,NEW_PASSWORD),background=True)
            pid = None
            deadline = time.monotonic()+20
            with closing(connect(d['owner'])) as observer:
                observer.autocommit = True
                while time.monotonic() < deadline:
                    with observer.cursor() as cursor:
                        cursor.execute("SELECT pid FROM pg_stat_activity WHERE datname=%s AND usename=%s "
                            "AND wait_event_type='Lock' AND query LIKE '%%control_cuentas%%'",(d['database'],d['role']))
                        row = cursor.fetchone()
                    if row:
                        pid = row[0]
                        break
                    if process.poll() is not None:
                        break
                    time.sleep(.05)
                assert pid is not None
                with observer.cursor() as cursor:
                    cursor.execute('SELECT pg_terminate_backend(%s)',(pid,))
                    assert cursor.fetchone() == (True,)
            writer.rollback()
            output,error = process.communicate(timeout=20)
            assert process.returncode == 1, output + error
            assert json.loads(output) == {'code':'administrator_recovery_outcome_unknown'}
            assert NEW_PASSWORD not in output + error
        finally:
            writer.rollback()
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


def test_terminal_cancellation_does_not_change_the_password(recovery):
    d = recovery
    result = cli(d['profile'],'recover-admin','--user-id',1,'--apply','--confirm-database',d['database'],cancel=True)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'code':'administrator_recovery_cancelled'}
    from app.passwords import verify_password
    with connect(d['owner']) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT hash_contrasena FROM usuario WHERE id_usuario=1')
        assert verify_password(OLD_PASSWORD,cursor.fetchone()[0])
