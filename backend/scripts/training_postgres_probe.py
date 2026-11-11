"""Owned-cluster bootstrap proof, run only inside the source-only Docker image."""
import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import secrets
import sys


class _ProbeFailure(Exception):
    """Only fixed diagnostic values cross the proof/CLI boundary."""

    def __init__(self, phase, error):
        from sqlalchemy.exc import OperationalError

        phases = ('create_database', 'permission_rejection', 'initialize',
                  'verify', 'quarantine', 'cleanup')
        category = 'unexpected_error'
        sqlstate_present = False
        if isinstance(error, OperationalError):
            category = 'operational_error'
            sqlstate_present = getattr(error.orig, 'pgcode', None) is not None
        self.diagnostic = dict(phase=phase if phase in phases else 'unknown',
                               category=category, sqlstate_present=sqlstate_present)
        super().__init__()


def prove(database):
    # Per-invocation state, shared only with the implementation below. Original
    # proof failures are wrapped before finalization; cleanup failures supersede
    # them just as they did before, but are explicitly identified as cleanup.
    stage = ['create_database']
    try:
        return _prove(database, stage)
    except _ProbeFailure:
        raise
    except Exception as error:
        raise _ProbeFailure(stage[0], error) from None


def _prove(database, stage):
    from sqlalchemy import create_engine, event, inspect, text
    from sqlalchemy.engine import Engine, URL
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.pool import NullPool
    from scripts.prepare_zip_manual_database import main as bootstrap

    url = URL.create('postgresql+psycopg2', username='fama_training_bootstrap',
                     host='db', port=5432, database='postgres')
    admin = create_engine(url, poolclass=NullPool, isolation_level='AUTOCOMMIT')
    target = None
    created = False
    def sql(statement):
        with admin.connect() as connection:
            return connection.execute(text(statement)).all() if statement.lstrip().startswith('SELECT') else connection.execute(text(statement))
    def exclusive(dbapi, record, proxy):
        with dbapi.cursor() as cursor:
            cursor.execute('SELECT current_database()')
            if cursor.fetchone()[0] == database:
                cursor.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()')
                if cursor.fetchone()[0] != 0:
                    raise RuntimeError('Unexpected target session')
        dbapi.rollback()
    def invoke(args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = bootstrap(args)
        if code != 0:
            raise RuntimeError('Bootstrap CLI failed')
        return json.loads(output.getvalue())
    try:
        # Identifiers are generated/validated, never arbitrary client SQL.
        sql(f'CREATE DATABASE "{database}" TEMPLATE template0 ALLOW_CONNECTIONS false')
        created = True
        sql(f'REVOKE CONNECT ON DATABASE "{database}" FROM PUBLIC')
        sql('CREATE ROLE fama_training_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION')
        denied_password = secrets.token_hex(32)
        with admin.connect() as connection:
            connection.execute(text('CREATE ROLE fama_probe_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :password'), {'password': denied_password})
        sql(f'ALTER DATABASE "{database}" ALLOW_CONNECTIONS true')
        target_url = url.set(database=database)
        target = create_engine(target_url, poolclass=NullPool)
        with target.connect() as connection:
            _, oid, system = connection.execute(text('SELECT current_database(), oid, system_identifier FROM pg_database CROSS JOIN pg_control_system() WHERE datname=current_database()')).one()
        stage[0] = 'permission_rejection'
        writer_url = target_url.set(username='fama_probe_writer', password=denied_password)

        def permission_preconditions():
            # Catalog facts establish permission state, not the cause of a
            # connection failure. A classified rejection is required separately.
            with admin.connect() as connection:
                role = connection.execute(text(
                    'SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, '
                    'rolcreaterole, rolreplication, rolbypassrls '
                    'FROM pg_roles WHERE rolname=:writer'
                ), {'writer': writer_url.username}).one_or_none()
                if role is None or tuple(role) != (writer_url.username, True, False, False, False, False, False):
                    raise RuntimeError('Writer role prerequisites not established')
                memberships = connection.execute(text(
                    'SELECT roleid, member FROM pg_auth_members '
                    'WHERE member=(SELECT oid FROM pg_roles WHERE rolname=:writer)'
                ), {'writer': writer_url.username}).all()
                if memberships:
                    raise RuntimeError('Writer membership prerequisites not established')
                target_identity = connection.execute(text(
                    'SELECT datname, oid, datallowconn, '
                    "has_database_privilege(:writer, oid, 'CONNECT') "
                    'FROM pg_database WHERE datname=:database'
                ), {'writer': writer_url.username, 'database': database}).one_or_none()
                if target_identity is None or tuple(target_identity) != (database, oid, True, False):
                    raise RuntimeError('Target permission prerequisites not established')

        denied = None
        control = None
        try:
            permission_preconditions()
            control = create_engine(writer_url.set(database='postgres'), poolclass=NullPool)
            with control.connect() as connection:
                identity = connection.execute(text('SELECT current_user, current_database()')).one()
                if tuple(identity) != (writer_url.username, 'postgres'):
                    raise RuntimeError('Writer control identity not established')
            denied = create_engine(writer_url, poolclass=NullPool)
            try:
                with denied.connect():
                    raise RuntimeError('Foreign writer connected')
            except OperationalError as error:
                if getattr(error.orig, 'pgcode', None) != '42501':
                    raise
                permission_preconditions()
        finally:
            # Attempt both disposals even if one fails; retain cleanup diagnostics.
            try:
                try:
                    if denied is not None:
                        denied.dispose()
                finally:
                    if control is not None:
                        control.dispose()
            except Exception as error:
                raise _ProbeFailure('cleanup', error) from None
        stage[0] = 'initialize'
        event.listen(Engine, 'checkout', exclusive)
        args = ['--database-url', target_url.render_as_string(hide_password=False), '--training-development',
                '--expected-system-id', str(system), '--expected-database-oid', str(oid)]
        result = invoke(args + ['--initialize', '--writers-stopped'])
        if result != {'prepared': True, 'stages': ['migrations']}:
            raise RuntimeError('Unexpected initialization stages')
        def inventory():
            with target.connect() as connection:
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                inspector = inspect(connection)
                parts = []
                for name in sorted(inspector.get_table_names(schema='public')):
                    quoted = connection.dialect.identifier_preparer.quote(name)
                    schema = (inspector.get_columns(name), inspector.get_pk_constraint(name),
                              inspector.get_foreign_keys(name), inspector.get_indexes(name),
                              inspector.get_unique_constraints(name), inspector.get_check_constraints(name))
                    rows = sorted(repr(tuple(row)) for row in connection.exec_driver_sql(f'SELECT * FROM public.{quoted}'))
                    parts.append((name, schema, rows))
                return hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()
        stage[0] = 'verify'
        before = inventory()
        # All physical connections opened by the CLI check are read-only.
        os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=5000'
        if invoke(args + ['--check']) != {'prepared': True, 'verification': 'training_schema_and_markers'}:
            raise RuntimeError('Schema check failed')
        os.environ['PGOPTIONS'] = '-c statement_timeout=15000 -c lock_timeout=5000'
        wrong = list(args)
        wrong[-1] = str(oid + 1)
        try:
            invoke(wrong + ['--check'])
        except SystemExit as error:
            if error.code != 1:
                raise
        else:
            raise RuntimeError('Wrong identity accepted')
        if inventory() != before:
            raise RuntimeError('Application inventory changed')
        stage[0] = 'quarantine'
        target.dispose()
        if sql(f"SELECT count(*) FROM pg_stat_activity WHERE datname='{database}'")[0][0] != 0:
            raise RuntimeError('Target sessions remain')
        sql(f'ALTER DATABASE "{database}" ALLOW_CONNECTIONS false')
        if sql(f"SELECT datallowconn FROM pg_database WHERE datname='{database}'")[0][0] is not False:
            raise RuntimeError('Target not quarantined')
        try:
            with target.connect():
                raise RuntimeError('Quarantined database accepted a connection')
        except OperationalError as error:
            if getattr(error.orig, 'pgcode', None) != '55000':
                raise
        return dict(database=database, database_oid=str(oid), system_id=str(system), schema_verified=True,
                    inventory_unchanged=True, identity_rejected=True, writer_rejected=True, quarantined=True)
    except _ProbeFailure:
        raise
    except Exception as error:
        raise _ProbeFailure(stage[0], error) from None
    finally:
        stage[0] = 'cleanup'
        if target is not None:
            target.dispose()
        if created:
            # This is only our generated target. A failure never reopens it.
            sql(f'ALTER DATABASE "{database}" ALLOW_CONNECTIONS false')
        if event.contains(Engine, 'checkout', exclusive):
            event.remove(Engine, 'checkout', exclusive)
        admin.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'fama_training_dev_[0-9]{14}', args.database):
        parser.error('Unsupported generated database name')
    try:
        result = prove(args.database)
    except Exception as error:
        diagnostic = dict(phase='unknown', category='unexpected_error', sqlstate_present=False)
        if type(error) is _ProbeFailure:
            diagnostic = error.diagnostic
        print(json.dumps(diagnostic, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
