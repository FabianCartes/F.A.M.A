"""Operator-only upgrade for the existing Cloud SQL test database via local proxy."""
import argparse
import getpass
import json
import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from app.schema import HEAD, upgrade_schema


def main():
    parser = argparse.ArgumentParser(description='Actualiza fama_pruebas y concede permisos diarios; no guarda contraseñas.')
    parser.add_argument('--apply', action='store_true', required=True)
    parser.add_argument('--port', type=int, choices=range(1, 65536), default=5433, metavar='PUERTO')
    parser.add_argument('--password-stdin', action='store_true', help='Leer la contraseña de una tubería segura en vez de la consola')
    arguments = parser.parse_args()
    password = sys.stdin.readline().rstrip('\r\n') if arguments.password_stdin else getpass.getpass('Contraseña SQL de fama_migrador: ')
    if not password:
        print(json.dumps({'code': 'migration_password_required'}))
        return 1
    address = URL.create('postgresql+psycopg2', username='fama_migrador', password=password,
                         host='127.0.0.1', port=arguments.port, database='fama_pruebas')
    result = upgrade_schema(address.render_as_string(hide_password=False))
    if result.code != 'schema_current':
        print(json.dumps({'code': result.code, 'revision': result.revision}))
        return 1
    engine = None
    try:
        engine = create_engine(address, connect_args={'connect_timeout': 10,
                              'options': '-c statement_timeout=30000 -c lock_timeout=5000'})
        with engine.begin() as connection:
            statement = (Path(__file__).parent / 'permisos_tablas_pruebas.sql').read_text(encoding='utf-8')
            # The script contains PostgreSQL format('%I', ...). Send it without
            # DBAPI parameter interpolation, within this same transaction.
            with connection.connection.cursor() as cursor:
                cursor.execute(statement)
                code = cursor.fetchone()[0]
            if code != 'runtime_permissions_ready':
                raise RuntimeError('permissions_unconfirmed')
    except Exception:
        print(json.dumps({'code': 'runtime_permissions_unconfirmed', 'revision': HEAD}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps({'code': 'autonomy_update_ready', 'revision': HEAD}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
