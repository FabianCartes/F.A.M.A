"""Local operator adoption of an existing administrator, separate from initial signup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.configuration import InstallationStore, load_configuration
from app.database_connection import database_engine
from app.installation import Installation, _node_lock, _write_json
from app.runtime import RuntimeDirectory


class HistoryAdoptionError(ValueError):
    """Sanitized local result."""


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def _journal(path):
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 4096:
            raise ValueError()
        value = json.loads(path.read_text(encoding='utf-8'))
        if (set(value) != {'version','binding','account','user_id','event_id','occurred_at'} or value['version'] != 1
                or any(type(value[key]) is not int or value[key] < 1 for key in ('user_id','event_id','occurred_at'))
                or any(not isinstance(value[key], str) or len(value[key]) != 64 for key in ('binding','account'))):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError):
        raise HistoryAdoptionError('history_adoption_journal_invalid') from None


def _administrator(connection, user_id, *, locking=False):
    if type(user_id) is not int or not 1 <= user_id <= 2**31-1:
        raise HistoryAdoptionError('history_adoption_user_invalid')
    row = connection.execute(text('SELECT id_usuario,correo_electronico,hash_contrasena,rol,activo '
        'FROM public.usuario WHERE id_usuario=:id' + (' FOR UPDATE' if locking else '')), {'id':user_id}).mappings().first()
    if row is None or row['rol'] != 'administrador' or not row['activo']:
        raise HistoryAdoptionError('history_adoption_active_administrator_required')
    return dict(row)


def adopt_history(directory, user_id, *, apply=False, confirm_database=None):
    directory = Path(directory).resolve()
    with _node_lock(directory):
        configuration = load_configuration({'FAMA_CONFIG_DIR':str(directory)})
        if configuration.installation_status == 'completed':
            raise HistoryAdoptionError('history_adoption_installation_completed')
        if (directory / 'finalization.json').exists():
            raise HistoryAdoptionError('history_adoption_initial_signup_pending')
        database = make_url(configuration.database_url).database
        if apply and confirm_database != database:
            raise HistoryAdoptionError('history_adoption_database_confirmation_required')
        checks = Installation(directory).check()['checks']
        if (any(not value['ok'] for key, value in checks.items() if key != 'first_admin')
                or checks['first_admin']['code'] != 'database_already_initialized'):
            raise HistoryAdoptionError('history_adoption_checks_failed')
        runtime = RuntimeDirectory(configuration)
        runtime.describe()
        public = InstallationStore(directory).read()['values']
        address = make_url(configuration.database_url)
        binding = _fingerprint({'configuration':public, 'runtime':runtime.binding,
                                'database':[address.host,address.port,address.database,address.username]})
        journal_path = directory / 'history-adoption.json'
        intent = _journal(journal_path)
        engine = database_engine(configuration.database_url)
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                account = _administrator(connection, user_id)
            account_fingerprint = _fingerprint(account)
            if intent and (intent['binding'] != binding or intent['user_id'] != user_id or intent['account'] != account_fingerprint):
                raise HistoryAdoptionError('history_adoption_identity_changed')
            if apply:
                with runtime.lease(), engine.begin() as connection:
                    if not connection.scalar(text('SELECT pg_try_advisory_xact_lock(5065941)')):
                        raise HistoryAdoptionError('history_adoption_busy')
                    connection.execute(text('INSERT INTO control_cuentas(id) VALUES(1) ON CONFLICT(id) DO NOTHING'))
                    connection.execute(text('UPDATE control_cuentas SET id=id WHERE id=1'))
                    if _fingerprint(_administrator(connection, user_id, locking=True)) != account_fingerprint:
                        raise HistoryAdoptionError('history_adoption_identity_changed')
                    if intent is None:
                        event_id = connection.scalar(text("SELECT nextval(pg_get_serial_sequence('public.evento_seguridad','id'))"))
                        intent = {'version':1, 'binding':binding, 'account':account_fingerprint, 'user_id':user_id,
                                  'event_id':event_id, 'occurred_at':int(time.time())}
                        _write_json(journal_path, intent)
                    event = connection.execute(text('SELECT occurred_at,action,outcome,actor_id,subject_user_id,dataset_id '
                        'FROM evento_seguridad WHERE id=:event'), {'event':intent['event_id']}).first()
                    expected = (intent['occurred_at'],'account.operator_adopted','success',None,user_id,None)
                    if event is not None and tuple(event) != expected:
                        raise HistoryAdoptionError('history_adoption_journal_invalid')
                    if event is None:
                        connection.execute(text("INSERT INTO evento_seguridad(id,occurred_at,action,outcome,subject_user_id) "
                            "VALUES(:event,:now,'account.operator_adopted','success',:id)"),
                            {'event':intent['event_id'],'now':intent['occurred_at'],'id':user_id})
                InstallationStore(directory).save(public, completed=True)
            return {'code':'history_adopted' if apply else 'history_adoption_ready',
                    'database':database, 'administrator_id':user_id, 'account_created_or_password_changed':False,
                    'restart_required':apply}
        except HistoryAdoptionError:
            raise
        except Exception:
            if journal_path.exists():
                raise HistoryAdoptionError('history_adoption_pending') from None
            raise
        finally:
            engine.dispose()


def main():
    parser = argparse.ArgumentParser(description='Adopción local de una cuenta administradora existente; no es alta inicial')
    parser.add_argument('--config-dir', required=True)
    parser.add_argument('--user-id', required=True, type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-database')
    arguments = parser.parse_args()
    for key in list(os.environ):
        if key.upper().startswith('PG'):
            os.environ.pop(key)
    try:
        report = adopt_history(arguments.config_dir, arguments.user_id, apply=arguments.apply,
                               confirm_database=arguments.confirm_database)
    except HistoryAdoptionError as error:
        report = {'code':str(error)}
    except Exception:
        report = {'code':'history_adoption_unavailable'}
    print(json.dumps(report))
    return 0 if report['code'] in {'history_adoption_ready','history_adopted'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
