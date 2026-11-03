"""Foreground local collection session; existing offline copy and prebuilt UI only.

Original must remain offline indefinitely. No installation, migration, activation,
cloud/training, automatic restart, deletion or forced kill is performed.
"""
import argparse
from dataclasses import fields
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['PYTHON_DOTENV_DISABLED'] = '1'


def create_api():
    """Only the existing import router; its authentication is unchanged."""
    from fastapi import FastAPI
    from app.routes.dataset_imports import router
    app = FastAPI(title='Local import collection (not the full platform)')
    app.include_router(router)

    @app.get('/health')
    def health():
        loaded = sorted(name for name in sys.modules if name == 'app.main' or
                        name.split('.')[0] in ('torch', 'tensorflow', 'training'))
        return {'scope': 'local-import-collection', 'unexpected_modules': loaded}
    return app


def configuration(root, frontend):
    # Reuse the relocation control-file reader, never its payload/hash traversal.
    from scripts.relocate_dataset_storage import private, read_json, integrity, readonly_database
    private(root, directory=True)
    report = read_json(root / 'relocation-complete.json')
    if report.get('status') != 'complete' or report.get('destination') != str(root):
        raise ValueError('complete destination binding required')
    source = Path(report.get('source', ''))
    if not source.is_absolute() or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError('disjoint offline source binding required')
    if frontend == root or not frontend.is_relative_to(root) or frontend.is_relative_to(source):
        raise ValueError('frontend must be a strict physical descendant of dedicated root')
    private(frontend, directory=True)
    profile = read_json(root / 'profile.json')
    from app.services.dataset_storage import PhysicalStorage
    policy = PhysicalStorage(**profile)
    if policy.configuration_sha256 != report.get('destination_configuration_sha256'):
        raise ValueError('configuration binding mismatch')
    if not policy.roots or any(not p.is_relative_to(root) for p in policy.roots.values()):
        raise ValueError('confined role roots required')
    for path in policy.roots.values():
        private(path, directory=True)
        if path.stat().st_dev != root.stat().st_dev:
            raise ValueError('same device required')
    environment = read_json(root / 'environment.json')
    from app.services.dataset_zip import ImportLimits
    keys = {'FAMA_IMPORT_' + field.name.upper() for field in fields(ImportLimits)} | {
        'FAMA_IMPORT_CHUNK_BYTES', 'FAMA_IMPORT_RESERVED_BYTES_PER_OWNER',
        'FAMA_IMPORT_RESERVED_BYTES_GLOBAL'}
    numeric = {}
    for key, value in environment.items():
        if key not in keys:
            raise ValueError('numeric import limits only')
        if type(value) not in (str, int) or not str(value).isascii() or not str(value).isdigit() or not 0 < int(value) <= 2**63 - 1:
            raise ValueError('invalid numeric import limit')
        numeric[key] = str(value)
    database = root / 'manual.sqlite3'
    private(database)
    with readonly_database(database) as connection:
        integrity(connection)
    private(frontend, directory=True)
    server = frontend / 'server.js'
    if not server.is_file() or server.is_symlink():
        raise ValueError('regular standalone server.js required')
    manifest = frontend / '.next/routes-manifest.json'
    if not manifest.resolve(strict=True).is_relative_to(frontend):
        raise ValueError('external frontend manifest')
    rules = json.loads(manifest.read_bytes()).get('rewrites')
    expected = {'source': '/api/:path*', 'destination': 'http://127.0.0.1:8000/api/:path*'}
    if not isinstance(rules, dict) or rules.get('beforeFiles') or rules.get('fallback') or len(rules.get('afterFiles', [])) != 1 or any(rules['afterFiles'][0].get(k) != v for k, v in expected.items()):
        raise ValueError('compiled API rewrite must target only 127.0.0.1:8000')
    # Internal dependency symlinks are legitimate; external ones are not.
    for parent, dirs, files in os.walk(frontend, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            if path.is_symlink() and not path.resolve(strict=True).is_relative_to(frontend):
                raise ValueError('external frontend symlink')
    return policy, numeric, database


def get_json(url):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=1) as response:
        return json.load(response)


def group_alive(process):
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False


def drain_owned(children, notice_seconds, diagnostic):
    """No exception/notice can release the lock before every group is absent.

    Unknown group state is treated as alive. Diagnostics are best effort, never
    control flow. The caller keeps idempotent signal handlers installed throughout.
    """
    failed = False
    def report(message):
        nonlocal failed
        try:
            diagnostic(message)
        except BaseException:
            failed = True
    for name in ('worker', 'api', 'frontend'):
        if name not in children:
            continue
        process = children[name]
        deadline = time.monotonic() + (notice_seconds if name == 'worker' else min(30, notice_seconds))
        signalled = warned = False
        while True:
            try:
                process.poll()
                if not group_alive(process):
                    break
                if not signalled:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        signalled = True
                    except ProcessLookupError:
                        # Confirm absence on the next observation, not by assumption.
                        pass
                if not warned and time.monotonic() >= deadline:
                    warned = True
                    report(f'drain notice: {name} owned PGID {process.pid} still present; lock retained')
                time.sleep(.1)
            except BaseException as error:
                failed = True
                report(f'drain uncertainty: {name} owned PGID {process.pid}: {type(error).__name__}; lock retained')
                # Keep protecting the lock even if observation/signalling fails.
    return failed


def supervise(root, frontend, port, notice_seconds=930):
    policy, numeric, database = configuration(root, frontend)
    runtime = root / 'runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    from scripts.relocate_dataset_storage import private, write_json, readonly_database
    private(runtime, directory=True)
    lock_path = runtime / 'session.lock'
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        private(lock_path)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Never kill occupants or select another port.
        for number in (8000, port):
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1', number))
        node = shutil.which('node')
        if not node:
            raise ValueError('existing node required')
        import tempfile
        session = Path(tempfile.mkdtemp(prefix='session-', dir=runtime))
        for name in ('home', 'tmp', 'cache'):
            (session / name).mkdir(mode=0o700)
        env = dict(numeric, PATH=os.environ.get('PATH', os.defpath), HOME=str(session / 'home'),
                   TMPDIR=str(session / 'tmp'), XDG_CACHE_HOME=str(session / 'cache'),
                   PYTHONDONTWRITEBYTECODE='1', PYTHON_DOTENV_DISABLED='1',
                   FAMA_ENV='development', FAMA_IMPORT_DEV_MODE='1',
                   DATABASE_URL='sqlite:///' + str(database),
                   FAMA_IMPORT_STORAGE_PROFILE=str(root / 'profile.json'),
                   FAMA_IMPORT_ROOT=str(policy.roots['imports']),
                   OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   NEXT_TELEMETRY_DISABLED='1', HOSTNAME='127.0.0.1', PORT=str(port))
        # Verify current ledger read-only, never empty-activate or compare a stale DB SHA.
        previous = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(env)
            from app.services.dataset_storage_runtime import runtime_import_service
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            service = runtime_import_service(policy.roots['imports'], attempt_root=policy.roots['attempts'])
            connection = readonly_database(database)
            engine = create_engine('sqlite://', creator=lambda: connection)
            try:
                with Session(engine) as db:
                    service.storage_policy.verify(db, service)
                    from app.models.dataset_storage import StorageGrant, StoragePool
                    if {row.id for row in db.query(StoragePool)} != set(policy.free_floors):
                        raise ValueError('unknown pool binding')
                    if any(row.policy_sha256 != policy.policy_hash(service.limits) or
                           row.pool_id not in policy.free_floors for row in db.query(StorageGrant)):
                        raise ValueError('grant policy binding mismatch')
            finally:
                engine.dispose()
        finally:
            os.environ.clear()
            os.environ.update(previous)
        commands = {
            'api': [sys.executable, '-B', '-m', 'uvicorn', 'scripts.run_local_collection:create_api', '--factory', '--host', '127.0.0.1', '--port', '8000', '--no-proxy-headers'],
            'worker': [sys.executable, '-B', '-m', 'scripts.run_dataset_import_worker', '--database-url', env['DATABASE_URL'], '--import-root', str(policy.roots['imports']), '--staging-root', str(policy.roots['attempts']), '--local-only', '--watch', '--execution-seconds', '900'],
            'frontend': [node, str(frontend / 'server.js')]}
        children, logs = {}, []
        stopping = False
        def requested(*_):
            nonlocal stopping
            stopping = True
        handlers = {number: signal.signal(number, requested) for number in (signal.SIGINT, signal.SIGTERM)}
        outcome = 'startup_failure'
        try:
            for name, command in commands.items():
                log = (session / (name + '.log')).open('xb')
                logs.append(log)
                children[name] = subprocess.Popen(command, env=env, cwd=frontend if name == 'frontend' else Path(__file__).resolve().parents[1], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 60
            while not stopping:
                if any(child.poll() is not None for child in children.values()):
                    outcome = 'ownedchild_exit'
                    raise RuntimeError('owned child exited; inspect session logs')
                try:
                    health = get_json('http://127.0.0.1:8000/health')
                    direct = get_json('http://127.0.0.1:8000/api/ingestion/imports/access')
                    proxied = get_json(f'http://127.0.0.1:{port}/api/ingestion/imports/access')
                    if health == {'scope': 'local-import-collection', 'unexpected_modules': []} and direct == proxied == {'development_mode': True}:
                        break
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('readiness timeout')
                time.sleep(.2)
            if not stopping:
                write_json(session / 'ready.json', {'scope': 'local-import-collection', 'root': str(root), 'pids': {k: p.pid for k, p in children.items()}})
                print(json.dumps({'ready': str(session), 'frontend': f'http://127.0.0.1:{port}'}), flush=True)
                while not stopping:
                    if any(child.poll() is not None for child in children.values()):
                        outcome = 'ownedchild_exit'
                        raise RuntimeError('owned child exited; no restart')
                    time.sleep(.2)
            if stopping:
                outcome = 'requested_signal'
        finally:
            # Until drain returns, no report I/O or handler restoration may unwind
            # this frame: the instance lock remains held even on repeated signals.
            drain_failed = drain_owned(children, notice_seconds,
                lambda message: print(message, file=sys.stderr, flush=True))
            try:
                write_json(session / 'stopped.json', {'reason': 'drain_failure' if drain_failed else outcome,
                    'remaining_owned_groups': {}, 'data_preserved': True, 'forced_kill': False})
            finally:
                for log in logs:
                    log.close()
                for number, handler in handlers.items():
                    signal.signal(number, handler)
            if drain_failed:
                raise RuntimeError('drain_failure; all owned groups eventually proven absent')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='NEW dedicated complete relocated private root; original stays offline')
    parser.add_argument('--frontend-root', required=True, type=Path, help='Dedicated prebuilt Next standalone copy with public/static; compiled API rewrite must use port 8000')
    parser.add_argument('--frontend-port', type=int, default=3000)
    parser.add_argument('--shutdown-notice-seconds', type=float, default=930,
                        help='Diagnostic notice only (0 < seconds <= 930); never forces exit or releases flock')
    args = parser.parse_args()
    if not 0 < args.shutdown_notice_seconds <= 930:
        parser.error('shutdown notice must be positive and <=930')
    if not 1 <= args.frontend_port <= 65535 or args.frontend_port == 8000:
        parser.error('frontend port must be 1..65535 and different from API 8000')
    os.umask(0o077)
    # Control validation must not initialize a default backend/data engine or
    # consume ambient credentials before the dedicated child env is assembled.
    path = os.environ.get('PATH', os.defpath)
    os.environ.clear()
    os.environ.update(PATH=path, DATABASE_URL='sqlite://',
                      PYTHONDONTWRITEBYTECODE='1', PYTHON_DOTENV_DISABLED='1')
    try:
        supervise(args.root, args.frontend_root, args.frontend_port, args.shutdown_notice_seconds)
    except Exception as error:
        print(f'local session refused/failed: {type(error).__name__}: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
