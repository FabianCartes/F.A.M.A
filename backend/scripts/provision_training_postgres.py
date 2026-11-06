"""Local assisted PostgreSQL provisioning; no application startup or automatic deletion."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_training_postgres_target import PreflightRefused, check_target

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = 'postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
ATTEMPT_LABEL = 'fama.bootstrap.attempt'


class Refused(Exception):
    pass


def private_write(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


class Provision:
    def __init__(self, state):
        self.state = state
        self.nonce = secrets.token_hex(16)
        self.report = dict(status='in_progress', run=self.nonce, phases=[], attempts=[], application_started=False)
        self.environment = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(state),
                            'DOCKER_CONFIG': str(state / 'docker-config')}
        self.owned = []
        self.bindings = {}

    def save(self):
        temporary = self.state / ('receipt-' + secrets.token_hex(8))
        private_write(temporary, json.dumps(self.report, sort_keys=True, indent=2) + '\n')
        os.replace(temporary, self.state / 'receipt.json')

    def docker(self, *args, mutation=False, timeout=30):
        if mutation:
            # No argv, environments or credentials are written to this journal.
            self.report['attempts'].append({'operation': ' '.join(args[:2]), 'outcome': 'unknown'})
            self.save()
        try:
            output = subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', *args],
                                    env=self.environment, check=True, capture_output=True,
                                    text=True, timeout=timeout).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise Refused('docker_operation_failed_preserve_state') from None
        if mutation:
            self.report['attempts'][-1]['outcome'] = 'returned'
            self.save()
        return output

    def inspect(self, kind, identity):
        try:
            value = json.loads(self.docker(kind, 'inspect', '--format', '{{json .}}', identity))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise Refused('invalid_resource_evidence') from None

    def own(self, kind, identity):
        value = self.inspect(kind, identity)
        labels = value.get('Config', {}).get('Labels') if kind in ('container', 'image') else value.get('Labels')
        if not labels or labels.get(ATTEMPT_LABEL) != self.nonce:
            raise Refused('ownership_mismatch')
        binding = self.bindings.get((kind, identity))
        if binding is not None:
            name, project, database = binding
            if (value.get('Name', '').lstrip('/') != name
                    or labels.get('com.docker.compose.project') != project
                    or labels.get('fama.bootstrap.database') != database):
                raise Refused('identity_mismatch')
        if kind != 'volume' and value.get('Id') != identity:
            raise Refused('identity_mismatch')
        if kind == 'volume' and (value.get('Name') != identity or value.get('Driver') != 'local'):
            raise Refused('identity_mismatch')
        return value

    def labels(self, project, database):
        return ['--label', f'{ATTEMPT_LABEL}={self.nonce}', '--label', f'com.docker.compose.project={project}',
                '--label', f'fama.bootstrap.database={database}']

    def context(self):
        context = self.state / 'context'
        context.mkdir(mode=0o700)
        backend = ROOT / 'backend'
        names = (backend / 'bootstrap/source-files.txt').read_text().splitlines()
        if len(names) != 30 or len(set(names)) != len(names):
            raise Refused('source_inventory_mismatch')
        files = [(backend / name, context / name) for name in names]
        files += [(backend / 'bootstrap' / name, context / name) for name in ('Dockerfile', 'requirements.txt')]
        digest = hashlib.sha256()
        for source, target in files:
            relative = target.relative_to(context)
            if (relative.is_absolute() or '..' in relative.parts or source != source.resolve(strict=True)
                    or not stat.S_ISREG(source.stat().st_mode)):
                raise Refused('unsafe_source_context')
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            data = source.read_bytes()
            private_write(target, data.decode('utf-8'))
            digest.update(str(relative).encode() + b'\0' + data)
        self.report['source_sha256'] = digest.hexdigest()
        self.save()
        return context

    def image(self, context):
        iidfile = self.state / 'image-id'
        self.docker('build', '--label', f'{ATTEMPT_LABEL}={self.nonce}', '--iidfile', str(iidfile), str(context),
                    mutation=True, timeout=900)
        image = iidfile.read_text().strip()
        iidfile.chmod(0o600)
        if not re.fullmatch('sha256:[0-9a-f]{64}', image):
            raise Refused('invalid_image_identity')
        self.own('image', image)
        self.report['image_id'] = image
        self.save()
        return image

    def network(self, identity, allowed):
        network = self.own('network', identity)
        if not network.get('Internal') or set(network.get('Containers', {})) - set(allowed):
            raise Refused('unexpected_network_member')

    def container(self, identity, network, volume, image):
        info = self.own('container', identity)
        if (info['Config']['Image'] != image or info['HostConfig'].get('PortBindings')
                or info['HostConfig']['NetworkMode'] != network):
            raise Refused('container_isolation_mismatch')
        if volume is not None:
            self.own('volume', volume)
            mounts = [m for m in info['Mounts'] if m['Destination'] == '/var/lib/postgresql/data']
            if len(mounts) != 1 or mounts[0].get('Name') != volume or mounts[0]['Type'] != 'volume':
                raise Refused('volume_binding_mismatch')
        return info

    def phase(self, project, kind, image, postgres):
        check_target(project)
        database = 'fama_training_dev_' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        phase = dict(project=project, kind=kind, database=database, containers=[])
        self.report['phases'].append(phase)
        self.save()
        folder = self.state / kind
        folder.mkdir(mode=0o700)
        password = secrets.token_hex(32)
        private_write(folder / 'pg-admin', password + '\n')
        private_write(folder / 'pg-client', 'db:5432:*:fama_training_bootstrap:' + password + '\n')
        labels = self.labels(project, database)
        volume = project + '_training_pgdata'
        returned = self.docker('volume', 'create', *labels, volume, mutation=True)
        if returned != volume:
            raise Refused('invalid_volume_identity')
        phase['volume'] = volume
        self.save()
        self.bindings[('volume', volume)] = (volume, project, database)
        self.own('volume', volume)  # volume create may silently adopt: labels must prove OUR creation.
        network = self.docker('network', 'create', '--internal', *labels, project + '_bootstrap', mutation=True)
        phase['network_id'] = network
        self.save()
        if not re.fullmatch('[0-9a-f]{64}', network):
            raise Refused('invalid_network_identity')
        self.bindings[('network', network)] = (project + '_bootstrap', project, database)
        self.network(network, [])
        self.own('volume', volume)
        self.own('image', image)
        db = self.docker('container', 'create', '--name', project + '-db', *labels, '--network', network,
                         '--network-alias', 'db', '--restart', 'no', '--memory', '512m', '--cpus', '1',
                         '--mount', f'type=volume,src={volume},dst=/var/lib/postgresql/data',
                         '--mount', f'type=bind,src={folder / "pg-admin"},dst=/run/secrets/pg-admin,readonly',
                         '-e', 'POSTGRES_USER=fama_training_bootstrap', '-e', 'POSTGRES_DB=postgres',
                         '-e', 'POSTGRES_PASSWORD_FILE=/run/secrets/pg-admin', postgres, mutation=True)
        phase['containers'].append(db)
        self.owned.append(db)
        self.bindings[('container', db)] = (project + '-db', project, database)
        self.save()
        self.container(db, network, volume, postgres)
        self.network(network, [db])
        self.docker('container', 'start', db, mutation=True)
        ready = False
        for _ in range(45):
            self.container(db, network, volume, postgres)
            self.network(network, [db])
            try:
                # TCP is not ready during the official image's temporary init server.
                self.docker('container', 'exec', db, 'pg_isready', '-h', '127.0.0.1', '-U', 'fama_training_bootstrap', '-d', 'postgres', timeout=5)
                ready = True
                break
            except Refused:
                time.sleep(1)
        if not ready:
            raise Refused('new_postgres_not_ready')
        self.container(db, network, volume, postgres)
        self.own('image', image)
        worker = self.docker('container', 'create', '--name', project + '-bootstrap', *labels, '--network', network,
                             '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                             '--user', f'{os.getuid()}:{os.getgid()}', '--memory', '256m', '--cpus', '1',
                             '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m,mode=1777',
                             '--mount', f'type=bind,src={folder / "pg-client"},dst=/run/secrets/pg-client,readonly',
                             '-e', 'PGPASSFILE=/run/secrets/pg-client', '-e', 'PYTHON_DOTENV_DISABLED=1',
                             '-e', 'PGOPTIONS=-c statement_timeout=15000 -c lock_timeout=5000',
                             '--entrypoint', 'python', image, '-B', '-m', 'scripts.training_postgres_probe', '--database', database, mutation=True)
        phase['containers'].append(worker)
        self.owned.append(worker)
        self.bindings[('container', worker)] = (project + '-bootstrap', project, database)
        self.save()
        info = self.container(worker, network, None, image)
        if not info['HostConfig'].get('ReadonlyRootfs'):
            raise Refused('runner_rootfs_not_readonly')
        self.network(network, [db, worker])
        self.docker('container', 'start', worker, mutation=True)
        if self.docker('container', 'wait', worker, timeout=180) != '0':
            raise Refused('bootstrap_probe_failed')
        self.container(worker, network, None, image)
        self.network(network, [db, worker])
        try:
            proof = json.loads(self.docker('container', 'logs', worker))
            expected = {'schema_verified', 'inventory_unchanged', 'identity_rejected', 'writer_rejected', 'quarantined'}
            if (proof['database'] != database or any(proof.get(key) is not True for key in expected)
                    or any(not re.fullmatch('[1-9][0-9]*', proof.get(key, '')) for key in ('database_oid', 'system_id'))):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise Refused('incomplete_postgres_proof') from None
        phase['proof'] = proof
        self.container(db, network, volume, postgres)
        self.docker('container', 'stop', '--time', '10', db, mutation=True)
        phase['status'] = 'verified_stopped'
        self.save()

    def stop_owned(self):
        for identity in reversed(self.owned):
            try:
                self.own('container', identity)
                self.docker('container', 'stop', '--time', '10', identity, mutation=True)
            except (Refused, KeyError, TypeError):
                self.report['stop_incomplete'] = True
        self.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True, help='Fresh absolute directory below an existing physical parent; contains private state and a sanitized receipt. Never reuse an attempt.')
    parser.add_argument('--create-persistent', action='store_true', help='After successful disposable proof ONLY, create and verify fama-training-dev; default performs the disposable test only. No activation.')
    args = parser.parse_args(argv)
    state = Path(args.state_dir)
    if (not state.is_absolute() or state.exists() or state.is_symlink() or not state.parent.is_dir()
            or state.parent != state.parent.resolve() or any(c in str(state) for c in ',\n\r')):
        parser.error('A fresh absolute state directory below an existing physical parent is required')
    if os.getuid() == 0:
        parser.error('A non-root host user is required')
    test_project = 'fama-training-dev-test-' + secrets.token_hex(8)
    runner = None
    try:
        if args.create_persistent:
            check_target('fama-training-dev')
        check_target(test_project)
        state.mkdir(mode=0o700)
        runner = Provision(state)
        runner.save()
        context = runner.context()
        postgres = runner.inspect('image', POSTGRES_IMAGE)
        if 'postgres@' + POSTGRES_IMAGE.split('@')[1] not in postgres.get('RepoDigests', []):
            raise Refused('postgres_image_not_pinned')
        postgres = postgres['Id']
        runner.report['postgres_image_id'] = postgres
        runner.save()
        image = runner.image(context)
        runner.phase(test_project, 'disposable', image, postgres)
        if args.create_persistent:
            runner.phase('fama-training-dev', 'persistent', image, postgres)
        runner.report['status'] = 'prepared_not_activated' if args.create_persistent else 'disposable_verified'
        runner.save()
        print(json.dumps({'status': runner.report['status'], 'receipt': str(state / 'receipt.json')}, sort_keys=True))
        return 0
    except (PreflightRefused, Refused, OSError, ValueError, KeyError, TypeError, KeyboardInterrupt) as error:
        if runner is not None:
            runner.report['status'] = 'failed_preserved'
            runner.stop_owned()
        reason = str(error) if isinstance(error, (PreflightRefused, Refused)) else 'execution_failed_preserve_state'
        print(f'Training PostgreSQL provisioning refused: {reason}. Preserve state; no application was started.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
