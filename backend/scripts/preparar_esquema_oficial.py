"""Migración oficial y permisos diarios mediante contraseña local oculta del migrador."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import warnings

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.configuration import load_configuration
from app.database_connection import database_engine
from app.installation import Installation
from app.schema import upgrade_schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', required=True)
    parser.add_argument('--apply', required=True, action='store_true')
    arguments = parser.parse_args()
    for key in list(os.environ):
        if key.upper().startswith('PG'):
            os.environ.pop(key)
    engine = None
    try:
        directory = Path(arguments.config_dir).resolve()
        configuration = load_configuration({'FAMA_CONFIG_DIR':str(directory)})
        address = make_url(configuration.database_url)
        if (configuration.installation_status == 'completed' or address.database != 'fama_oficial'
                or address.username != 'fama_oficial_app' or address.host != '127.0.0.1'
                or set(address.query) - {'sslmode'}
                or configuration.bucket_name != 'fama-audio-records-2026'
                or configuration.values.get('GOOGLE_CLOUD_PROJECT') != 'proyectotesis-fama'):
            report = {'code':'official_schema_configuration_invalid'}
        elif not sys.stdin.isatty():
            report = {'code':'official_schema_terminal_required'}
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('error',getpass.GetPassWarning)
                password = getpass.getpass('Contraseña SQL de fama_oficial_migrador: ')
            if not password:
                report = {'code':'official_schema_password_required'}
            else:
                migrator = address.set(username='fama_oficial_migrador',password=password).render_as_string(hide_password=False)
                del password
                engine = database_engine(migrator)
                with engine.connect() as connection:
                    connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                    flags = connection.execute(text("""SELECT current_database()='fama_oficial',
                        current_user='fama_oficial_migrador', rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls,
                        has_database_privilege(current_user,current_database(),'CREATE'),
                        has_database_privilege(current_user,current_database(),'TEMPORARY'),
                        EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid),
                        has_schema_privilege(current_user,'public','USAGE'),has_schema_privilege(current_user,'public','CREATE')
                        FROM pg_roles r WHERE rolname=current_user""")).one()
                if tuple(flags) != (True,True,False,False,False,False,False,False,False,False,False,True,True):
                    report = {'code':'official_schema_migrator_permissions_invalid'}
                else:
                    status = upgrade_schema(migrator)
                    if status.code != 'schema_current':
                        report = {'code':'official_schema_not_prepared','schema_code':status.code}
                    else:
                        with engine.begin() as connection:
                            if not connection.scalar(text('SELECT pg_try_advisory_xact_lock(5065941)')):
                                raise ValueError('busy')
                            connection.execute(text(Path(__file__).with_name('permisos_tablas_oficial.sql').read_text(encoding='utf-8')))
                        checks = Installation(directory).check()['checks']
                        if all(value['ok'] for key,value in checks.items() if key != 'first_admin'):
                            report = {'code':'official_schema_prepared','database':'fama_oficial','revision':status.revision,
                                      'runtime_permissions_ready':True,'migrator_password_saved':False,'history_transferred':False}
                        else:
                            report = {'code':'official_schema_runtime_check_failed','checks':checks}
    except (EOFError,KeyboardInterrupt):
        report = {'code':'official_schema_cancelled'}
    except getpass.GetPassWarning:
        report = {'code':'official_schema_terminal_required'}
    except Exception as error:
        original = getattr(error,'orig',error)
        state = getattr(original,'pgcode','') or ''
        authentication = state.startswith('28') or 'password authentication failed' in str(original).casefold()
        report = {'code':'official_schema_authentication_failed' if authentication else 'official_schema_unavailable'}
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(report))
    return 0 if report['code'] == 'official_schema_prepared' else 1


if __name__ == '__main__':
    raise SystemExit(main())
