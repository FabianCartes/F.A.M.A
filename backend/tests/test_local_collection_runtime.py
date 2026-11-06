"""Public CLI/API tests; Node fixture below is NOT a real Next bundle."""
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import time

import pytest
from tests.test_dataset_import_api import imports, operation, confirm

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_local_collection.py'


def command(root, ui, *flags):
    return [sys.executable, '-B', str(SCRIPT), '--root', str(root), '--frontend-root', str(ui), *flags]


def test_incomplete_copy_refused_before_runtime_creation(tmp_path):
    root, ui = tmp_path / 'copy', tmp_path / 'ui'
    root.mkdir(mode=0o700)
    ui.mkdir(mode=0o700)
    result = subprocess.run(command(root, ui), capture_output=True, text=True, timeout=5)
    assert result.returncode == 1
    assert 'relocation-complete.json' in result.stderr
    assert not list(root.iterdir())


def test_help_and_port_error_are_nonmutating(tmp_path):
    result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--help'], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert all(flag in result.stdout for flag in ('--root', '--frontend-root', '8000'))
    result = subprocess.run(command(tmp_path, tmp_path, '--frontend-port', '8000'), capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert not list(tmp_path.iterdir())


def test_api_factory_actual_router_loopback_auth_and_module_scope(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.setenv('FAMA_ENV', 'development')
    monkeypatch.setenv('FAMA_IMPORT_DEV_MODE', '1')
    from fastapi.testclient import TestClient
    from scripts.run_local_collection import create_api
    app = create_api()
    with TestClient(app, client=('127.0.0.1', 1234)) as client:
        assert client.get('/health').json() == {'scope': 'local-import-collection', 'unexpected_modules': []}
        assert client.get('/api/ingestion/imports/access').json() == {'development_mode': False}
        assert client.get('/api/ingestion/datasets').status_code == 404
    with TestClient(app, client=('192.0.2.1', 1234)) as client:
        assert client.get('/api/ingestion/imports/access').json() == {'development_mode': False}
    monkeypatch.setenv('FAMA_IMPORT_DEV_MODE', '0')
    with TestClient(app, client=('127.0.0.1', 1234)) as client:
        assert client.get('/api/ingestion/imports/access').json() == {'development_mode': False}
        assert client.get('/api/ingestion/imports/datasets').status_code in (401, 403)


def bundle(ui, destination='http://127.0.0.1:8000/api/:path*'):
    ui.mkdir(mode=0o700)
    (ui / '.next').mkdir(mode=0o700)
    (ui / '.next/routes-manifest.json').write_text(json.dumps({'rewrites': {'afterFiles': [
        {'source': '/api/:path*', 'destination': destination}]}}))
    # Controlled external process for shutdown tests, not Next compatibility proof.
    (ui / 'server.js').write_text("const http=require('http');http.createServer((q,s)=>{const r=http.request('http://127.0.0.1:8000'+q.url,p=>{s.writeHead(p.statusCode,p.headers);p.pipe(s)});r.on('error',()=>{s.statusCode=503;s.end()});r.end()}).listen(+process.env.PORT,'127.0.0.1');")


@pytest.fixture
def copied(imports, tmp_path):
    from types import SimpleNamespace
    from app.routes.dataset_imports import get_import_user
    from app.services.dataset_storage import PhysicalStorage
    from scripts.migrate_dataset_storage import migrate_storage, activate_empty_lab
    from tests.test_dataset_import_receipts import migrate
    from scripts.migrate_dataset_import_chunks import migrate_chunks
    from tests.test_dataset_import_chunks import put
    from tests.test_dataset_zip_validation import archive, wav_bytes
    from tests.test_dataset_storage_relocation import cli, private_json, snapshot
    client, service, app, sessions = imports
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=-1)
    migrate(sessions)
    migrate_chunks(sessions.kw['bind'], writers_stopped=True)
    roots = dict(imports=str(service.root), objects=str(service.root / 'objects'),
                 attempts=str(service.attempt_root), manifests=str(service.attempt_root),
                 scratch=str(tmp_path / 'scratch'), exports=str(tmp_path / 'exports'))
    for name in ('scratch', 'exports'):
        Path(roots[name]).mkdir(mode=0o700)
    config = dict(roots=roots, pools=dict.fromkeys(roots, 'ssd'), free_floors={'ssd': 1})
    policy = PhysicalStorage(**config)
    migrate_storage(sessions.kw['bind'], writers_stopped=True)
    activate_empty_lab(sessions.kw['bind'], policy, writers_stopped=True)
    service.storage_policy = policy
    result = client.post('/api/ingestion/imports', json={'request_key': 'runtime', 'name': 'Birds'})
    assert result.status_code == 200, result.text
    identity = result.json()['id']
    data = archive(tmp_path / 'synthetic.zip', [('birds/a.wav', wav_bytes())]).read_bytes()
    url = f'/api/ingestion/imports/{identity}/receipt'
    assert client.post(url, json={'name': 'synthetic.zip', 'size_bytes': len(data)}).status_code == 200
    assert put(client, url, 0, data).status_code == 200
    assert client.post(url + '/finalize').status_code == 200
    preview = operation(client, identity, 'preview', {'root': ''})
    assert preview.status_code == 200, preview.text
    assert confirm(client, preview.json()).status_code == 200
    catalog = client.get('/api/ingestion/imports/datasets').json()
    dataset = catalog['datasets'][0]
    files_url = f"/api/ingestion/imports/datasets/{dataset['id']}/files"
    member = client.get(files_url).json()['files'][0]
    download = files_url + '/' + member['sha256']
    audio = client.get(download).content
    database = tmp_path / 'manual.sqlite3'
    os.close(os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    with sessions.kw['bind'].connect() as source, sqlite3.connect(database) as target:
        source.connection.driver_connection.backup(target)
    private_json(tmp_path / 'profile.json', config)
    private_json(tmp_path / 'environment.json', {'FAMA_IMPORT_FREE_BYTES': '1'})
    destination = tmp_path.parent / (tmp_path.name + '-copy')
    result = cli(tmp_path, destination, '--writers-stopped')
    assert result.returncode == 0, result.stderr
    before = snapshot(tmp_path)
    yield destination, tmp_path, catalog, download, audio
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('destination', ['http://example.invalid/api/:path*', 'http://127.0.0.1:8999/api/:path*'])
def test_compiled_rewrite_mismatch_refused_before_children(copied, destination):
    root, *_ = copied
    ui = root / 'ui'
    bundle(ui, destination)
    result = subprocess.run(command(root, ui), capture_output=True, text=True, timeout=5)
    assert result.returncode == 1
    assert 'compiled API rewrite' in result.stderr
    assert not (root / 'runtime').exists()


def test_external_private_bundle_rejected_before_runtime(copied):
    root, source, *_ = copied
    ui = source.parent / (source.name + '-external-ui')
    bundle(ui)
    # Occupant ensures the old launcher cannot start children while demonstrating
    # that it reached runtime creation instead of rejecting external confinement.
    with socket.socket() as occupant:
        occupant.bind(('127.0.0.1', 8000))
        result = subprocess.run(command(root, ui), capture_output=True, text=True, timeout=5)
    assert result.returncode == 1
    assert 'frontend must be a strict physical descendant' in result.stderr
    assert not (root / 'runtime').exists()


def wait_until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('bounded public process observation expired')


def absent(pid):
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True


@pytest.mark.parametrize('fault', ['report_failure', 'second_signal', 'child_exit'])
def test_drain_holds_lock_and_reports_actual_outcome(copied, fault):
    root, source, catalog, download, audio = copied
    ui = root / 'ui'
    bundle(ui)
    from scripts.run_local_collection import get_json
    out = (root / 'supervisor.stdout').open('wb')
    err = (root / 'supervisor.stderr').open('wb')
    # Foreign dummy is never in an owned group and must remain untouched.
    dummy = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(20)'], start_new_session=True)
    process = subprocess.Popen(command(root, ui, '--shutdown-notice-seconds', '.2'), stdout=out, stderr=err)
    pids = {}
    try:
        def ready():
            paths = list((root / 'runtime').glob('session-*/ready.json')) if (root / 'runtime').exists() else []
            assert process.poll() is None, (root / 'supervisor.stderr').read_text()
            return paths[0] if paths else None
        ready_path = wait_until(ready)
        pids = json.loads(ready_path.read_text())['pids']
        assert get_json('http://127.0.0.1:8000/api/ingestion/imports/datasets') == catalog
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:8000' + download, timeout=1) as response:
            assert response.read() == audio
        session = ready_path.parent
        if fault == 'child_exit':
            os.killpg(pids['frontend'], signal.SIGTERM)
        else:
            os.kill(pids['worker'], signal.SIGSTOP)
            if fault == 'report_failure':
                (session / 'stopped.json').mkdir(mode=0o700)
            process.send_signal(signal.SIGTERM)
            time.sleep(.7)
            if fault == 'second_signal':
                process.send_signal(signal.SIGTERM)
            time.sleep(.2)
            assert process.poll() is None, 'lock owner exited while frozen own worker remained'
            second = subprocess.run(command(root, ui), capture_output=True, text=True, timeout=4)
            assert second.returncode == 1
            assert 'Resource temporarily unavailable' in second.stderr, second.stderr
            assert not absent(pids['api']) and not absent(pids['frontend'])
            os.kill(pids['worker'], signal.SIGCONT)
        status = process.wait(timeout=5)
        assert dummy.poll() is None
        assert all(absent(pid) for pid in pids.values())
        if fault == 'report_failure':
            assert status == 1
            assert 'stopped.json' in (root / 'supervisor.stderr').read_text()
        else:
            report = json.loads((session / 'stopped.json').read_text())
            assert report['reason'] == ('ownedchild_exit' if fault == 'child_exit' else 'requested_signal')
            assert report['remaining_owned_groups'] == {}
            assert status == (1 if fault == 'child_exit' else 0)
    finally:
        # Exact PIDs from this test's public receipt only; RED must not orphan.
        for pid in pids.values():
            if not absent(pid):
                os.kill(pid, signal.SIGCONT)
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
        if pids:
            wait_until(lambda: all(absent(pid) for pid in pids.values()))
        dummy.terminate()
        dummy.wait(timeout=2)
        out.close()
        err.close()
