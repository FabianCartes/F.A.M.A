"""Assisted host CLI; all Docker interaction is emulated at subprocess boundary."""
import json
import re
import subprocess

import pytest


def test_unavailable_docker_cannot_create_local_or_persistent_state(tmp_path, monkeypatch, capsys):
    from scripts.provision_training_postgres import main
    destination = tmp_path / "new-state"
    def unavailable(command, **kwargs):
        assert command[:3] == ["docker", "--host", "unix:///var/run/docker.sock"]
        raise FileNotFoundError("private diagnostic not for receipt")
    monkeypatch.setattr(subprocess, "run", unavailable)
    assert main(["--state-dir", str(destination)]) == 1
    assert not destination.exists()
    output = capsys.readouterr()
    assert not output.out
    assert "private diagnostic" not in output.err
    assert "docker_unavailable" in output.err


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    from scripts import provision_training_postgres as provision
    from pathlib import Path
    class Daemon:
        def __init__(self):
            self.calls, self.objects = [], {}
            self.bad_probe = False
            self.adopt_volume = False
            self.network_name_mismatch = False
            self.next_id = 100
        def run(self, command, **kwargs):
            assert command[:3] == ["docker", "--host", "unix:///var/run/docker.sock"]
            args = command[3:]
            self.calls.append(args)
            assert "rm" not in args and "prune" not in args and "compose" not in args
            assert not set(kwargs['env']) & {'DOCKER_HOST', 'GOOGLE_APPLICATION_CREDENTIALS'}
            def opt(flag):
                return args[args.index(flag) + 1]
            if args[0] == "version":
                output = "29.9.1"
            elif "ls" in args:
                output = ""
                filters = [args[i + 1] for i, x in enumerate(args) if x == '--filter']
                if args[0] == 'container':
                    found = []
                    for identity, obj in self.objects.items():
                        if 'HostConfig' not in obj:
                            continue
                        if any(f.startswith('name=') and re.search(f[5:], obj['Name']) for f in filters):
                            found.append(identity)
                        if any(f.startswith('label=') and obj['Config']['Labels'].get(f[6:].split('=', 1)[0]) == f[6:].split('=', 1)[1] for f in filters):
                            found.append(identity)
                    output = '\n'.join(found)
            elif args[0] == "build":
                Path(opt('--iidfile')).write_text('sha256:' + 'c' * 64)
                labels = dict(args[i + 1].split('=', 1) for i, x in enumerate(args) if x == '--label')
                self.objects['sha256:' + 'c' * 64] = {'Id': 'sha256:' + 'c' * 64, 'Config': {'Labels': labels}}
                output = ""
            elif args[:2] == ['image', 'inspect'] and args[-1].startswith('postgres:'):
                output = json.dumps({'Id': 'sha256:' + 'd' * 64, 'RepoDigests': ['postgres@' + provision.POSTGRES_IMAGE.split('@')[1]]})
            elif len(args) > 1 and args[1] == 'create':
                self.next_id += 1
                labels = dict(args[i + 1].split('=', 1) for i, x in enumerate(args) if x == '--label')
                identity = f'{self.next_id:064x}'
                name = args[-1] if args[0] in ('volume', 'network') else opt('--name')
                obj = {'Id': identity, 'Name': name, 'Labels': labels}
                if args[0] == 'volume':
                    identity = name
                    obj['Driver'] = 'local'
                    if self.adopt_volume:
                        obj['Labels'] = {}
                if args[0] == 'network':
                    obj.update(Internal=True, Containers={})
                    if self.network_name_mismatch:
                        obj['Name'] = 'another-owned-network'
                if args[0] == 'container':
                    net = opt('--network')
                    obj.update(Name='/' + name, Config={'Labels': labels, 'Image': ('sha256:' + 'd' * 64 if '-db' in name else 'sha256:' + 'c' * 64)},
                               HostConfig={'NetworkMode': net, 'PortBindings': {}, 'ReadonlyRootfs': '--read-only' in args},
                               NetworkSettings={'Networks': {'bootstrap': {'NetworkID': net}}}, Mounts=[])
                    mounts = [args[i + 1] for i, x in enumerate(args) if x == '--mount']
                    for mount in mounts:
                        bits = dict(x.split('=', 1) for x in mount.split(',') if '=' in x)
                        obj['Mounts'].append({'Type': bits['type'], 'Name': bits['src'], 'Source': bits['src'], 'Destination': bits['dst'], 'RW': 'readonly' not in mount})
                self.objects[identity] = obj
                output = identity
            elif len(args) > 1 and args[1] == 'inspect':
                output = json.dumps(self.objects[args[-1]])
            elif args[:2] == ['container', 'wait']:
                output = '0'
            elif args[:2] == ['container', 'logs']:
                obj = self.objects[args[-1]]
                database = obj['Labels']['fama.bootstrap.database']
                output = json.dumps({'database': database, 'database_oid': '789', 'system_id': '123456',
                    'schema_verified': True, 'inventory_unchanged': True, 'identity_rejected': True,
                    'writer_rejected': not self.bad_probe, 'quarantined': True})
            elif args[:2] in (['container', 'start'], ['container', 'stop'], ['container', 'exec']):
                output = ''
            else:
                raise AssertionError(args)
            return subprocess.CompletedProcess(command, 0, stdout=output + '\n', stderr='')
    fake = Daemon()
    monkeypatch.setattr(subprocess, 'run', fake.run)
    return fake


def test_persistent_creation_requires_disposable_proof(daemon, tmp_path, capsys):
    from scripts.provision_training_postgres import main
    state = tmp_path / 'new-state'
    assert main(['--state-dir', str(state), '--create-persistent']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'prepared_not_activated'
    receipt = json.loads((state / 'receipt.json').read_text())
    assert [phase['kind'] for phase in receipt['phases']] == ['disposable', 'persistent']
    assert all(phase['proof']['quarantined'] for phase in receipt['phases'])
    assert len(list((state / 'context').rglob('*.py'))) == 30
    assert all(p.stat().st_mode & 0o077 == 0 for p in state.rglob('*') if p.is_file())
    assert not any(word in (state/'receipt.json').read_text() for word in ('password', 'PGPASS', 'secret'))


def test_failed_disposable_never_creates_persistent(daemon, tmp_path, capsys):
    from scripts.provision_training_postgres import main
    daemon.bad_probe = True
    state = tmp_path/'new-state'
    assert main(['--state-dir', str(state), '--create-persistent']) == 1
    receipt = json.loads((state/'receipt.json').read_text())
    assert receipt['status'] == 'failed_preserved'
    assert [phase['kind'] for phase in receipt['phases']] == ['disposable']
    assert not any('fama-training-dev-db' in call for call in daemon.calls)
    assert 'writer_rejected' not in capsys.readouterr().err  # Diagnostics never dump child payloads.


def test_existing_volume_is_not_adopted_or_started(daemon, tmp_path, capsys):
    from scripts.provision_training_postgres import main
    daemon.adopt_volume = True
    assert main(['--state-dir', str(tmp_path/'new-state')]) == 1
    assert not any(call[:2] == ['container','start'] for call in daemon.calls)
    assert 'ownership_mismatch' in capsys.readouterr().err


def test_network_binding_must_match_this_phase(daemon, tmp_path, capsys):
    from scripts.provision_training_postgres import main
    daemon.network_name_mismatch = True
    assert main(['--state-dir', str(tmp_path/'new-state')]) == 1
    assert not any(call[:2] == ['container','start'] for call in daemon.calls)
    assert 'identity_mismatch' in capsys.readouterr().err


def test_existing_state_is_preserved_before_docker(daemon, tmp_path, capsys):
    from scripts.provision_training_postgres import main
    state = tmp_path/'existing'
    state.mkdir()
    sentinel = state/'receipt.json'
    sentinel.write_text('existing independent state')
    with pytest.raises(SystemExit) as error:
        main(['--state-dir', str(state), '--create-persistent'])
    assert error.value.code == 2
    assert sentinel.read_text() == 'existing independent state'
    assert not daemon.calls


def test_uncertain_creation_is_recorded_without_retry(daemon, tmp_path, monkeypatch, capsys):
    from scripts.provision_training_postgres import main
    original = daemon.run
    attempts = []
    def timeout(command, **kwargs):
        if command[3:5] == ['network', 'create']:
            attempts.append(command)
            raise subprocess.TimeoutExpired(command, 30, stderr='sensitive daemon output')
        return original(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', timeout)
    state = tmp_path/'new-state'
    assert main(['--state-dir', str(state), '--create-persistent']) == 1
    receipt = json.loads((state/'receipt.json').read_text())
    assert len(attempts) == 1
    assert receipt['attempts'][-1] == {'operation': 'network create', 'outcome': 'unknown'}
    assert receipt['status'] == 'failed_preserved'
    assert 'sensitive daemon output' not in capsys.readouterr().err
    assert len(receipt['phases']) == 1


def test_unknown_network_member_is_never_started(daemon, tmp_path, monkeypatch, capsys):
    from scripts.provision_training_postgres import main
    original = daemon.run
    def intruder(command, **kwargs):
        result = original(command, **kwargs)
        if command[3:5] == ['network', 'inspect']:
            item = json.loads(result.stdout)
            item['Containers'] = {'foreign-container': {}}
            result.stdout = json.dumps(item)
        return result
    monkeypatch.setattr(subprocess, 'run', intruder)
    assert main(['--state-dir', str(tmp_path/'new-state')]) == 1
    assert not any(call[:2] == ['container', 'start'] for call in daemon.calls)
    assert 'unexpected_network_member' in capsys.readouterr().err


def test_foreign_member_after_db_creation_prevents_start(daemon, tmp_path, monkeypatch, capsys):
    from scripts.provision_training_postgres import main
    original = daemon.run
    def boundary(command, **kwargs):
        result = original(command, **kwargs)
        if command[3:5] == ['network', 'inspect'] and any('HostConfig' in obj for obj in daemon.objects.values()):
            data = json.loads(result.stdout)
            data['Containers'] = {'foreign-container': {}}
            result.stdout = json.dumps(data)
        return result
    monkeypatch.setattr(subprocess, 'run', boundary)
    state = tmp_path/'new-state'
    assert main(['--state-dir', str(state), '--create-persistent']) == 1
    assert not any(call[:2] == ['container', 'start'] for call in daemon.calls)
    receipt = json.loads((state/'receipt.json').read_text())
    assert receipt['status'] == 'failed_preserved'
    assert [phase['kind'] for phase in receipt['phases']] == ['disposable']
    assert 'unexpected_network_member' in capsys.readouterr().err
