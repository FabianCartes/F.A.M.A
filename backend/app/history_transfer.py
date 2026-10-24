"""Explicit relational transfer of the known, unversioned historical core."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from sqlalchemy import ForeignKeyConstraint, MetaData, inspect, text
from sqlalchemy.engine import make_url

from app.database_connection import database_engine


class HistoryTransferError(ValueError):
    """Sanitized operator result, without connection strings or row values."""


ORDER = ('usuario', 'conjunto_datos', 'audio', 'modelo', 'prediccion',
         'retroalimentacion', 'feedback_sync', 'metrica_entrenamiento')


def _unmanaged_objects(connection):
    return connection.scalar(text("""SELECT
        EXISTS(SELECT 1 FROM pg_namespace WHERE nspname NOT IN ('public','information_schema') AND nspname NOT LIKE 'pg_%')
        OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public')
        OR EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                  JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal)"""))


def _source_variant(connection):
    from app.schema import matches_schema
    from migrations.schema_0002 import metadata
    expected = MetaData()
    for name in ORDER:
        metadata.tables[name].to_metadata(expected)
    if matches_schema(connection, expected):
        return False
    for constraint in expected.tables['retroalimentacion'].constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            constraint.ondelete = 'CASCADE'
            for element in constraint.elements:
                element.ondelete = 'CASCADE'
    if not matches_schema(connection, expected):
        raise HistoryTransferError('history_source_schema_invalid')
    return True


def _address(value):
    try:
        address = make_url(value)
        if (address.get_backend_name() not in {'postgres', 'postgresql'} or not address.database
                or not address.host or not address.username or set(address.query) - {'sslmode'}):
            raise ValueError()
        return address
    except Exception:
        raise HistoryTransferError('history_configuration_invalid') from None


def _sequence(connection, table):
    pk = list(table.primary_key)[0].name
    sequence = connection.scalar(text('SELECT pg_get_serial_sequence(:table,:column)'),
                                 {'table':'public.' + table.name, 'column':pk})
    if not sequence or not re.fullmatch(r'public\.[a-z_][a-z_0-9]*', sequence):
        raise HistoryTransferError('history_sequence_invalid')
    return sequence


def _snapshot(connection):
    from migrations.schema_0002 import metadata
    result = {'tables':{}, 'next_sequence_values':{}}
    for name in ORDER:
        table = metadata.tables[name]
        rows = connection.execute(table.select().order_by(*table.primary_key)).mappings().fetchmany(100001)
        if len(rows) > 100000:
            raise HistoryTransferError('history_size_limit')
        result['tables'][name] = [dict(row) for row in rows]
        if name != 'feedback_sync':
            sequence = _sequence(connection, table)
            last, called = connection.exec_driver_sql('SELECT last_value,is_called FROM ' + sequence).one()
            options = connection.execute(text('SELECT seqincrement,seqmin,seqcycle FROM pg_sequence WHERE seqrelid=CAST(:name AS regclass)'),
                                         {'name':sequence}).one()
            next_value = last + 1 if called else last
            pk = list(table.primary_key)[0].name
            if (tuple(options) != (1, 1, False) or not 1 <= next_value <= 2**31-1
                    or next_value <= max((row[pk] for row in rows), default=0)):
                raise HistoryTransferError('history_sequence_invalid')
            result['next_sequence_values'][name] = next_value
    return result


def _digest(snapshot):
    encoded = json.dumps(snapshot, sort_keys=True, default=str, ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def transfer_history(source_url, target_url, *, apply=False, confirm_source=None, confirm_target=None, expect_digest=None):
    """Preview in read-only transactions, or copy into an empty current target atomically."""
    from app.schema import _inspect_schema
    from migrations.schema_0004 import metadata, BOOTSTRAP_TABLES
    source, target = _address(source_url), _address(target_url)
    if source.database == target.database:
        raise HistoryTransferError('history_source_equals_target')
    if apply and (confirm_source != source.database or confirm_target != target.database):
        raise HistoryTransferError('history_confirmation_required')
    source_engine = database_engine(source_url)
    target_engine = database_engine(target_url)
    try:
        with source_engine.connect().execution_options(isolation_level='REPEATABLE READ') as origin, origin.begin():
            origin.exec_driver_sql("SET TRANSACTION READ ONLY; SET LOCAL TIME ZONE 'UTC'")
            if _unmanaged_objects(origin) or set(inspect(origin).get_table_names()) != set(ORDER):
                raise HistoryTransferError('history_source_schema_invalid')
            legacy_cascade = _source_variant(origin)
            snapshot = _snapshot(origin)
            if any(row['status'] != 'synced' for row in snapshot['tables']['feedback_sync']):
                raise HistoryTransferError('history_pending_feedback_requires_review')
            if not any(row['rol'] == 'administrador' and row['activo'] for row in snapshot['tables']['usuario']):
                raise HistoryTransferError('history_active_administrator_required')
            digest = _digest(snapshot)
            with target_engine.begin() as destination:
                if not apply:
                    destination.exec_driver_sql('SET TRANSACTION READ ONLY')
                destination.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                if _unmanaged_objects(destination) or _inspect_schema(destination).code != 'schema_current':
                    raise HistoryTransferError('history_target_schema_invalid')
                if apply:
                    if not destination.scalar(text('SELECT pg_try_advisory_xact_lock(5065941)')):
                        raise HistoryTransferError('history_target_busy')
                    names = ','.join('public."' + name + '"' for name in (*metadata.tables, 'alembic_version'))
                    destination.exec_driver_sql('LOCK TABLE ' + names + ' IN SHARE ROW EXCLUSIVE MODE')
                if any(destination.execute(table.select().limit(1)).first() for table in metadata.tables.values() if table.name not in BOOTSTRAP_TABLES):
                    raise HistoryTransferError('history_target_not_empty')
                if apply:
                    if digest != expect_digest:
                        raise HistoryTransferError('history_source_changed')
                    for name in ORDER:
                        rows = snapshot['tables'][name]
                        if rows:
                            destination.execute(metadata.tables[name].insert().values(rows))
                    for name, next_value in snapshot['next_sequence_values'].items():
                        sequence = _sequence(destination, metadata.tables[name])
                        destination.exec_driver_sql('ALTER SEQUENCE ' + sequence + ' RESTART WITH ' + str(int(next_value)))
                    if _digest(_snapshot(destination)) != digest:
                        raise HistoryTransferError('history_verification_failed')
            models = snapshot['tables']['modelo']
            return {'code':'history_transferred' if apply else 'history_transfer_ready',
                    'source_database':source.database, 'target_database':target.database, 'digest':digest,
                    'rows':{name:len(rows) for name, rows in snapshot['tables'].items()},
                    'warnings':{'models_without_dataset':sum(row['id_conjunto_datos'] is None for row in models),
                                'active_models':sum(row['activo'] for row in models),
                                'historical_feedback_cascade_replaced_by_restrict':legacy_cascade},
                    'new_permissions_or_authorship_created':False}
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description='Traslado explícito de historia; no carga .env ni aplica migraciones')
    parser.add_argument('--source-url-file', required=True)
    parser.add_argument('--target-url-file', required=True)
    commands = parser.add_subparsers(dest='operation', required=True)
    commands.add_parser('plan')
    applying = commands.add_parser('apply')
    applying.add_argument('--apply', required=True, action='store_true')
    for name in ('confirm-source', 'confirm-target', 'expect-digest'):
        applying.add_argument('--' + name, required=True)
    arguments = parser.parse_args()
    for key in list(os.environ):
        if key.upper().startswith('PG'):
            os.environ.pop(key)
    try:
        urls = [Path(path).read_text(encoding='utf-8').strip() for path in
                (arguments.source_url_file, arguments.target_url_file)]
        report = transfer_history(*urls, apply=arguments.operation == 'apply',
            confirm_source=getattr(arguments, 'confirm_source', None), confirm_target=getattr(arguments, 'confirm_target', None),
            expect_digest=getattr(arguments, 'expect_digest', None))
    except HistoryTransferError as error:
        report = {'code':str(error)}
    except Exception:
        report = {'code':'history_transfer_unavailable'}
    print(json.dumps(report))
    return 0 if report['code'] in {'history_transfer_ready', 'history_transferred'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
