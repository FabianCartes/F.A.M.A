"""Traslado oficial explícito; contraseña del migrador solo en memoria del terminal."""
import argparse
from contextlib import contextmanager, nullcontext
import getpass
import json
import os
from pathlib import Path
import sys
import warnings

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.configuration import load_configuration
from app.database_connection import database_engine
from app.history_transfer import HistoryTransferError, ORDER, transfer_history


@contextmanager
def _source_cut(source_url):
    engine = database_engine(source_url)
    try:
        with engine.connect() as connection:
            busy = connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                "WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend')"))
            if busy:
                raise HistoryTransferError('official_history_source_busy')
            # Blocks table writes while the transfer opens its own read-only snapshot.
            # NOWAIT avoids waiting behind an existing writer; no client is terminated.
            names = ','.join('public."' + name + '"' for name in ORDER)
            connection.exec_driver_sql('LOCK TABLE ' + names + ' IN SHARE MODE NOWAIT')
            yield
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', required=True)
    parser.add_argument('--source-env-file', required=True)
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
        directory = Path(arguments.config_dir).resolve()
        configuration = load_configuration({'FAMA_CONFIG_DIR':str(directory)})
        target = make_url(configuration.database_url)
        reference = Path(arguments.source_env_file).resolve(strict=True)
        source_url = dotenv_values(reference, interpolate=False).get('DATABASE_URL')
        source = make_url(source_url)
        if (configuration.installation_status == 'completed' or target.database != 'fama_oficial'
                or target.username != 'fama_oficial_app' or target.host != '127.0.0.1'
                or set(target.query) - {'sslmode'}
                or configuration.bucket_name != 'fama-audio-records-2026'
                or configuration.values.get('GOOGLE_CLOUD_PROJECT') != 'proyectotesis-fama'
                or source.drivername not in {'postgres','postgresql','postgresql+psycopg2'}
                or source.host not in {'localhost','127.0.0.1'} or not source.database or not source.username
                or set(source.query) - {'sslmode'} or source.database == target.database):
            raise HistoryTransferError('official_history_configuration_invalid')
        target_url = configuration.database_url
        applying = arguments.operation == 'apply'
        if applying:
            if not sys.stdin.isatty():
                raise HistoryTransferError('official_history_terminal_required')
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                password = getpass.getpass('Contraseña SQL de fama_oficial_migrador: ')
            if not password:
                raise HistoryTransferError('official_history_password_required')
            target_url = target.set(username='fama_oficial_migrador', password=password).render_as_string(hide_password=False)
            del password
        with _source_cut(source_url) if applying else nullcontext():
            report = transfer_history(source_url, target_url, apply=applying,
                confirm_source=getattr(arguments,'confirm_source',None),
                confirm_target=getattr(arguments,'confirm_target',None),
                expect_digest=getattr(arguments,'expect_digest',None))
        if applying:
            report['migrator_password_saved'] = False
    except HistoryTransferError as error:
        report = {'code':str(error)}
    except (EOFError, KeyboardInterrupt):
        report = {'code':'official_history_cancelled'}
    except getpass.GetPassWarning:
        report = {'code':'official_history_terminal_required'}
    except Exception as error:
        original = getattr(error,'orig',error)
        state = getattr(original,'pgcode','') or ''
        authentication = state.startswith('28') or 'password authentication failed' in str(original).casefold()
        code = 'official_history_source_busy' if state == '55P03' else 'official_history_unavailable'
        report = {'code':'official_history_authentication_failed' if authentication else code}
    print(json.dumps(report))
    return 0 if report['code'] in {'history_transfer_ready','history_transferred'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
