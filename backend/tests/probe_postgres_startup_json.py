"""Parent-run, isolated PostgreSQL startup JSON-log experiment (no cleanup).

Run with an interpreter already providing SQLAlchemy and psycopg2. Creates a
private directory under the repository, one fresh local volume and one stopped
container; preserves all three, including logs. No application modules imported.
This tests libpq startup CONNECT rejection over a Unix socket using local trust,
NOT TCP/password authentication. Docker must already have the exact image below.
"""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = 'postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
ATTEMPT_LABEL = 'fama.bootstrap.attempt'
PURPOSE = 'startup-json-experiment'


class Refused(Exception):
    pass


class Experiment:
    def __init__(self):
        self.nonce = secrets.token_hex(16)
        self.name = 'fama-json-' + self.nonce
        self.database = 'probe_' + self.nonce
        self.role = 'writer_' + self.nonce
        self.application = 'startup_' + self.nonce
        self.directory = ROOT / ('.pgj-' + self.nonce)
        self.socket = self.directory / 'socket'
        self.volume = self.name + '-data'
        self.container = None
        self.stage = 'prerequisites'
        self.report = dict(status='failed', transport='unix_socket_local_trust',
                           tcp_password_path_tested=False, resources_preserved=True,
                           application_started=False, startup_rejected=False,
                           sqlstate_42501=False, matching_json_record=False,
                           container_stopped=False, run=self.nonce)

    def docker(self, *args, stdin=None, timeout=15):
        try:
            result = subprocess.run(
                ['docker', '--host', 'unix:///var/run/docker.sock', *args],
                input=stdin, capture_output=True, text=True, check=True,
                timeout=timeout, env={'PATH': '/usr/local/bin:/usr/bin:/bin',
                                     'HOME': str(self.directory),
                                     'DOCKER_CONFIG': str(self.directory / 'docker-config')})
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise Refused('docker_operation_failed') from None

    def inspect(self, kind, identity):
        try:
            value = json.loads(self.docker(kind, 'inspect', '--format', '{{json .}}', identity))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise Refused('invalid_inspection') from None

    def labels(self):
        return ['--label', ATTEMPT_LABEL + '=' + self.nonce,
                '--label', 'com.docker.compose.project=' + self.name,
                '--label', 'fama.bootstrap.database=' + self.database,
                '--label', 'fama.probe.purpose=' + PURPOSE]

    def owned(self, kind, identity):
        info = self.inspect(kind, identity)
        labels = info.get('Config', {}).get('Labels') if kind == 'container' else info.get('Labels')
        expected = {ATTEMPT_LABEL: self.nonce, 'com.docker.compose.project': self.name,
                    'fama.bootstrap.database': self.database, 'fama.probe.purpose': PURPOSE}
        if not labels or any(labels.get(k) != v for k, v in expected.items()):
            raise Refused('ownership_mismatch')
        if kind == 'volume':
            if info.get('Name') != self.volume or info.get('Driver') != 'local' or info.get('Options'):
                raise Refused('volume_identity_mismatch')
        else:
            if info.get('Id') != identity or info.get('Name') != '/' + self.name:
                raise Refused('container_identity_mismatch')
            host = info.get('HostConfig', {})
            if (info.get('Config', {}).get('Image') != POSTGRES_IMAGE
                    or host.get('NetworkMode') != 'none' or host.get('PortBindings')
                    or host.get('Privileged') or host.get('AutoRemove')):
                raise Refused('isolation_mismatch')
            mounts = info.get('Mounts', [])
            if len(mounts) != 2 or not any(
                    m.get('Type') == 'volume' and m.get('Name') == self.volume
                    and m.get('Destination') == '/var/lib/postgresql/data' for m in mounts) or not any(
                    m.get('Type') == 'bind' and m.get('Source') == str(self.socket)
                    and m.get('Destination') == '/probe-socket' for m in mounts):
                raise Refused('mount_mismatch')
            self.owned('volume', self.volume)
        return info

    def sql(self, statement):
        self.owned('container', self.container)
        return self.docker('container', 'exec', '-i', self.container, 'psql', '-X', '-qAt',
                           '-v', 'ON_ERROR_STOP=1', '-h', '/probe-socket', '-U', 'postgres',
                           '-d', 'postgres', stdin=statement, timeout=10)

    def run(self):
        # Fail before creating resources if the driver's prerequisites are absent.
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL
        from sqlalchemy.exc import DBAPIError
        import psycopg2  # noqa: F401

        # The host parent stays 0700; only the bind-mounted child is writable by
        # container postgres. No host ownership or configuration changes needed.
        if len(str(self.socket).encode()) > 85:
            raise Refused('unix_socket_path_too_long')
        self.directory.mkdir(mode=0o700)
        self.socket.mkdir(mode=0o733)
        self.socket.chmod(0o733)
        self.report['directory'] = str(self.directory)
        self.stage = 'image_inspection'
        self.inspect('image', POSTGRES_IMAGE)
        self.stage = 'fresh_volume'
        # Docker create can adopt an existing name: freshness must precede it.
        existing = self.docker('volume', 'ls', '--format', '{{.Name}}').splitlines()
        if self.volume in existing:
            raise Refused('volume_already_exists')
        if self.docker('volume', 'create', '--driver', 'local', *self.labels(), self.volume) != self.volume:
            raise Refused('unexpected_volume_name')
        self.report['volume'] = self.volume
        self.owned('volume', self.volume)
        self.stage = 'container_creation'
        identity = self.docker(
            'container', 'create', '--pull', 'never', '--name', self.name,
            *self.labels(), '--network', 'none', '--restart', 'no',
            '--memory', '512m', '--cpus', '1', '--log-driver', 'none',
            '--mount', 'type=volume,src=' + self.volume + ',dst=/var/lib/postgresql/data',
            '--mount', 'type=bind,src=' + str(self.socket) + ',dst=/probe-socket',
            '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', POSTGRES_IMAGE,
            'postgres', '-c', 'listen_addresses=', '-c', 'unix_socket_directories=/probe-socket',
            '-c', 'logging_collector=on', '-c', 'log_destination=jsonlog',
            '-c', 'log_directory=log', '-c', 'log_filename=proof.log',
            '-c', 'log_file_mode=0600', '-c', 'log_rotation_age=0',
            '-c', 'log_rotation_size=0', '-c', 'log_min_error_statement=panic',
            '-c', 'log_statement=none', '-c', 'statement_timeout=5000')
        if not re.fullmatch('[0-9a-f]{64}', identity):
            raise Refused('unexpected_container_id')
        self.container = identity
        self.report.update(container_id=identity, container_name=self.name)
        self.owned('container', identity)
        self.docker('container', 'start', identity)
        self.stage = 'final_server_readiness'
        for _ in range(45):
            self.owned('container', identity)
            # Official entrypoint execs the final server as PID 1. Its temporary
            # init server is a child of the entrypoint shell, never PID 1 postgres.
            command = self.docker('container', 'exec', identity, 'sh', '-c',
                                  'read name < /proc/1/comm; printf "%s" "$name"')
            if command == 'postgres':
                try:
                    if self.sql('SELECT 1;') == '1':
                        break
                except Refused:
                    pass
            time.sleep(1)
        else:
            raise Refused('readiness_timeout')
        self.stage = 'synthetic_setup'
        self.sql(f'CREATE DATABASE {self.database} TEMPLATE template0;\n'
                 f'REVOKE CONNECT ON DATABASE {self.database} FROM PUBLIC;\n'
                 f'CREATE ROLE {self.role} LOGIN;\n')
        self.stage = 'denied_startup'
        engine = create_engine(URL.create('postgresql+psycopg2', username=self.role,
                                          database=self.database,
                                          query={'host': str(self.socket)}),
                               connect_args={'application_name': self.application,
                                             'connect_timeout': 5}, pool_pre_ping=False)
        try:
            with engine.connect():
                pass
        except DBAPIError as error:
            self.report['startup_rejected'] = True
            self.report['sqlstate_42501'] = getattr(error.orig, 'pgcode', None) == '42501'
        finally:
            engine.dispose()
        self.stage = 'bounded_log_observation'
        for _ in range(10):
            # Only the current collector JSON file; never arbitrary server paths.
            # Read no more than 64 KiB, including when the log grows unexpectedly.
            raw = self.sql("""SELECT CASE WHEN pg_current_logfile('jsonlog') LIKE 'log/proof%'
                THEN pg_read_file(pg_current_logfile('jsonlog'),
                  greatest((pg_stat_file(pg_current_logfile('jsonlog'))).size - 65536, 0),
                  65536) ELSE '' END;""")
            for line in raw.splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # bounded tail can begin mid-record
                if (isinstance(record, dict) and record.get('state_code') == '42501'
                        and record.get('application_name') == self.application
                        and record.get('user') == self.role and record.get('dbname') == self.database):
                    self.report['matching_json_record'] = True
            if self.report['matching_json_record']:
                break
            time.sleep(1)
        if not all(self.report[k] for k in ('startup_rejected', 'matching_json_record')):
            raise Refused('proof_incomplete')
        self.report['status'] = 'verified'


def main():
    experiment = Experiment()
    try:
        experiment.run()
    except Exception:
        # No raw exception, SQL, log message, environment, or driver URL escapes.
        experiment.report.update(status='failed', failed_stage=experiment.stage)
    finally:
        if experiment.container:
            try:
                experiment.owned('container', experiment.container)
                experiment.docker('container', 'stop', '--time', '10', experiment.container, timeout=20)
                experiment.report['container_stopped'] = not experiment.owned(
                    'container', experiment.container).get('State', {}).get('Running', True)
            except Exception:
                experiment.report.update(status='failed', stop_failed=True)
        print(json.dumps(experiment.report, sort_keys=True))
    return 0 if experiment.report['status'] == 'verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
