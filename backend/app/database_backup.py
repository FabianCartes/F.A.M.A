"""Operator-only PostgreSQL archives and verified restoration into an empty database."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.configuration import protect_private_directory


class BackupError(ValueError):
    """Sanitized operator result; no connection string or SQL data."""


def _address(raw):
    try:
        address = make_url(raw)
        if (address.drivername not in {'postgresql', 'postgresql+psycopg2'} or not address.host
                or not address.database or not address.username or set(address.query) - {'sslmode'}):
            raise ValueError
        # pg_restore accepts a connection string as --dbname; keep it a literal database name.
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,62}', address.database):
            raise ValueError
        if any(c in str(value) for value in (address.host, address.database, address.username, address.password or '')
               for c in ('\n', '\r', '\0')):
            raise ValueError
        return address
    except (ValueError, TypeError, ArgumentError):
        raise BackupError('backup_configuration_invalid') from None


def _connect(address):
    return psycopg2.connect(**address.translate_connect_args(username='user', database='dbname'),
                            **address.query, connect_timeout=10)


def _tool(pg_bin, name):
    executable = Path(pg_bin) / (name + ('.exe' if os.name == 'nt' else ''))
    result = subprocess.run([str(executable), '--version'], capture_output=True, timeout=15)
    match = re.search(rb'PostgreSQL\) (\d+)\.', result.stdout)
    if result.returncode or not match:
        raise BackupError('backup_tools_invalid')
    return executable, int(match[1])


@contextmanager
def _libpq(address, parent):
    # Isolate libpq from inherited services, passwords, options and alternate targets.
    environment = {k:v for k,v in os.environ.items() if not k.upper().startswith('PG')}
    descriptor, temporary = tempfile.mkstemp(prefix='.pgpass-', dir=parent)
    try:
        fields = [address.host, str(address.port or 5432), address.database, address.username, address.password or '']
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(':'.join(value.replace('\\', '\\\\').replace(':', '\\:') for value in fields) + '\n')
        environment.update(PGHOST=address.host, PGPORT=str(address.port or 5432), PGDATABASE=address.database,
                           PGUSER=address.username, PGPASSFILE=temporary, PGCONNECT_TIMEOUT='10',
                           PGSSLMODE=address.query.get('sslmode', 'prefer'), PGAPPNAME='fama-database-backup')
        yield environment
    finally:
        Path(temporary).unlink(missing_ok=True)


def _inventory(connection):
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'UTC'")
        cursor.execute("SET LOCAL extra_float_digits = 3")
        cursor.execute("SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                       "WHERE c.relkind='r' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' ORDER BY 1,2")
        names = cursor.fetchall()
        tables = {}
        for schema, table in names:
            cursor.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text COLLATE "C"')
                           .format(sql.Identifier(schema, table)))
            digest = hashlib.sha256()
            count = 0
            for row in cursor:
                value = row[0].encode('utf-8')
                digest.update(len(value).to_bytes(8, 'big'))
                digest.update(value)
                count += 1
            tables[schema+'.'+table] = {'rows':count, 'sha256':digest.hexdigest()}
        cursor.execute("SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                       "WHERE c.relkind='S' AND n.nspname NOT LIKE 'pg_%' ORDER BY 1,2")
        sequences = {}
        for schema, name in cursor.fetchall():
            cursor.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(schema, name)))
            value, called = cursor.fetchone()
            sequences[schema+'.'+name] = {'last_value':value, 'is_called':called}
        cursor.execute('SELECT version_num FROM public.alembic_version')
        revision = cursor.fetchone()[0]
        return {'tables':tables, 'sequences':sequences, 'revision':revision}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _private_directory(directory):
    directory = Path(directory)
    if not directory.is_absolute() or directory.resolve() != directory or '..' in directory.parts:
        raise BackupError('backup_path_invalid')
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        raise BackupError('backup_destination_exists') from None
    protect_private_directory(directory)
    return directory


def create_backup(configuration, directory, pg_bin):
    address = _address(configuration.database_url)
    tool, major = _tool(pg_bin, 'pg_dump')
    from app.schema import check_schema
    with closing(_connect(address)) as connection:
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(5065941)')
            if not cursor.fetchone()[0]:
                raise BackupError('backup_source_busy')
            if check_schema(configuration.database_url).code != 'schema_current':
                raise BackupError('backup_schema_not_current')
            cursor.execute('SHOW server_version_num')
            if int(cursor.fetchone()[0]) // 10000 != major:
                raise BackupError('backup_major_version_mismatch')
            cursor.execute('SELECT pg_export_snapshot()')
            snapshot = cursor.fetchone()[0]
        inventory = _inventory(connection)
        directory = _private_directory(directory)
        archive = directory/'database.dump'
        with _libpq(address, directory) as environment:
            result = subprocess.run([str(tool), '--format=custom', '--no-password', '--snapshot='+snapshot,
                                     '--lock-wait-timeout=10s', '--file='+str(archive)],
                                    env=environment, capture_output=True, timeout=600)
        if result.returncode or result.stderr:
            raise BackupError('backup_dump_failed')
        with archive.open('r+b') as stream:
            os.fsync(stream.fileno())
        if _inventory(connection)['sequences'] != inventory['sequences']:
            raise BackupError('backup_sequences_changed')
        connection.rollback()
    manifest = dict(inventory, version=1, pg_major=major,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    source={'database':address.database, 'bucket':configuration.bucket_name},
                    archive_sha256=_sha256(archive), archive_bytes=archive.stat().st_size)
    temporary_manifest = directory/'manifest.partial'
    with temporary_manifest.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary_manifest, directory/'manifest.json')
    temporary_manifest.unlink()
    return {'code':'database_backup_created', 'directory':str(directory), 'sha256':manifest['archive_sha256'],
            'tables':len(inventory['tables']), 'revision':inventory['revision']}


def restore_backup(configuration, backup, target_url_file, pg_bin):
    backup = Path(backup)
    manifest = json.loads((backup/'manifest.json').read_text(encoding='utf-8'))
    archive = backup/'database.dump'
    if _sha256(archive) != manifest['archive_sha256'] or archive.stat().st_size != manifest['archive_bytes']:
        raise BackupError('backup_integrity_mismatch')
    target_file = Path(target_url_file)
    target = _address(target_file.read_text(encoding='utf-8').strip())
    source = _address(configuration.database_url)
    if target.database in {source.database, manifest['source']['database']}:
        raise BackupError('restore_source_forbidden')
    if target.database in {'postgres', 'template0', 'template1'}:
        raise BackupError('restore_target_forbidden')
    tool, major = _tool(pg_bin, 'pg_restore')
    with closing(_connect(target)) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SHOW server_version_num')
            if int(cursor.fetchone()[0]) // 10000 != major or major != manifest['pg_major']:
                raise BackupError('backup_major_version_mismatch')
            cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' "
                           "UNION ALL SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                           "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' "
                           "UNION ALL SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                           "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' "
                           "UNION ALL SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' "
                           "AND nspname NOT IN ('public','information_schema') "
                           "UNION ALL SELECT 1 FROM pg_extension WHERE extname<>'plpgsql')")
            if cursor.fetchone()[0]:
                raise BackupError('restore_target_not_empty')
        connection.rollback()
        with _libpq(target, backup) as environment:
            result = subprocess.run([str(tool), '--no-password', '--no-owner', '--no-acl', '--exit-on-error',
                                     '--single-transaction', '--dbname='+target.database, str(archive)],
                                    env=environment, capture_output=True, timeout=600)
        if result.returncode or result.stderr:
            raise BackupError('restore_failed')
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
        restored = _inventory(connection)
        connection.rollback()
    from app.schema import check_schema
    if (restored != {key:manifest[key] for key in ('tables','sequences','revision')}
            or check_schema(target.render_as_string(hide_password=False)).code != 'schema_current'):
        raise BackupError('restore_verification_failed')
    return {'code':'database_restore_verified', 'database':target.database,
            'tables':len(restored['tables']), 'revision':restored['revision'],
            'archive_sha256':manifest['archive_sha256']}
