"""Comprobar logins SQL oficiales con entrada oculta y consultas de solo lectura."""
import argparse
from contextlib import closing
import getpass
import json
import os
import sys
import warnings

import psycopg2
from psycopg2.extras import RealDictCursor


DATABASE='fama_oficial'
USERS=('fama_oficial_migrador','fama_oficial_app')


def _inspect(user,password,port):
    with closing(psycopg2.connect(host='127.0.0.1',hostaddr='127.0.0.1',port=port,dbname=DATABASE,
            user=user,password=password,connect_timeout=8,
            sslmode='disable',
            application_name='fama-official-sql-check',
            options='-c default_transaction_read_only=on -c statement_timeout=5000')) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT current_database() AS database, current_user AS "user",
                       current_setting('transaction_read_only') = 'on' AS read_only,
                       r.rolsuper AS superuser, r.rolcreatedb AS create_database,
                       r.rolcreaterole AS create_roles, r.rolinherit AS inherits_roles,
                       r.rolreplication AS replication, r.rolbypassrls AS bypass_rls,
                       has_database_privilege(current_user,current_database(),'CONNECT') AS connects,
                       has_database_privilege(current_user,current_database(),'CREATE') AS database_create,
                       has_database_privilege(current_user,current_database(),'TEMPORARY') AS temporary,
                       has_schema_privilege(current_user,'public','USAGE') AS schema_usage,
                       has_schema_privilege(current_user,'public','CREATE') AS schema_create,
                       EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS role_memberships,
                       (SELECT count(*) FROM pg_tables WHERE schemaname='public') AS public_tables
                FROM pg_roles AS r WHERE r.rolname=current_user
            """)
            return dict(cursor.fetchone())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,choices=range(1,65536),default=5433,metavar='PUERTO')
    arguments=parser.parse_args()
    if not sys.stdin.isatty():
        print(json.dumps({'code':'official_sql_terminal_required'}))
        return 1
    # Solo afecta a este proceso: libpq no heredará servicio, hostaddr u otras opciones.
    for key in list(os.environ):
        if key.upper().startswith('PG'):
            del os.environ[key]
    reports=[]
    user=None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            for user in USERS:
                password=getpass.getpass('Contraseña SQL de '+user+': ')
                if not password:
                    print(json.dumps({'code':'official_sql_password_required','user':user}))
                    return 1
                report=_inspect(user,password,arguments.port)
                del password
                expected={'database':DATABASE,'user':user,'read_only':True,
                    'superuser':False,'create_database':False,'create_roles':False,
                    'inherits_roles':False,'replication':False,'bypass_rls':False,
                    'connects':True,'database_create':False,'temporary':False,
                    'schema_usage':True,'schema_create':user==USERS[0],
                    'role_memberships':False}
                if any(report.get(key)!=value for key,value in expected.items()):
                    print(json.dumps({'code':'official_sql_permissions_invalid','user':user}))
                    return 1
                reports.append(report)
    except (EOFError,KeyboardInterrupt):
        print(json.dumps({'code':'official_sql_check_cancelled'}))
        return 1
    except getpass.GetPassWarning:
        print(json.dumps({'code':'official_sql_terminal_required'}))
        return 1
    except Exception as error:
        state=getattr(error,'pgcode','') or ''
        authentication=state.startswith('28') or 'password authentication failed' in str(error).casefold()
        code='official_sql_authentication_failed' if authentication else 'official_sql_unavailable'
        print(json.dumps({'code':code,'user':user}))
        return 1
    print(json.dumps({'code':'official_sql_access_verified','database':DATABASE,
                      'host':'127.0.0.1','port':arguments.port,'users':reports}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
