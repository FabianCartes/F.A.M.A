"""Operate only the isolated synthetic ZIP stack; external worker, no automatic deletion."""
import argparse
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import sys
import select
import socket
import socketserver
import threading
import urllib.request

REPO = Path(__file__).resolve().parents[2]
PROJECT = "fama-zip-manual"
CONTAINER_URL = "postgresql+psycopg2://zip_manual:zip_manual_local_only@db:5432/fama_zip_manual"
HOST_URL = "postgresql+psycopg2://zip_manual:zip_manual_local_only@172.30.252.30:5432/fama_zip_manual"


@contextmanager
def _ui_relay(upstream=("172.30.252.10", 3000), *, port=3001):
    """Trusted local TCP relay, never a configurable/open forward proxy."""
    slots = threading.BoundedSemaphore(32)
    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            if not slots.acquire(blocking=False):
                return
            try:
                with socket.create_connection(upstream, timeout=5) as target:
                    peers = (self.request, target)
                    for peer in peers:
                        peer.settimeout(10)
                    while True:
                        readable, _, _ = select.select(peers, (), (), 60)
                        if not readable:
                            return
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            (target if source is self.request else self.request).sendall(data)
            except OSError:
                return
            finally:
                slots.release()
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True
    with Server(("127.0.0.1", port), Relay) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


def _verify_ui(port):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(f"http://127.0.0.1:{port}/", timeout=10) as response:
        if response.status != 200:
            raise ValueError("Manual UI did not return HTTP 200 through loopback")


def _serve_ui():
    with _ui_relay() as relay:
        _verify_ui(relay.server_address[1])
        print("Manual ZIP UI: http://127.0.0.1:3001; keep this terminal open; Ctrl+C closes only the relay.", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


def _environment():
    if os.getuid() == 0:
        raise ValueError("Run the manual stack as a non-root user")
    environment = dict(os.environ)
    environment.update(HOST_UID=str(os.getuid()), HOST_GID=str(os.getgid()),
                       FAMA_ZIP_MANUAL_HOME=str(REPO / ".fama-zip-manual"),
                       PYTHON_DOTENV_DISABLED="1", PYTHONDONTWRITEBYTECODE="1")
    for name in ("COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "GOOGLE_APPLICATION_CREDENTIALS",
                 "GCP_KEY_PATH", "GCS_BUCKET_NAME", "XC_API_KEY"):
        environment.pop(name, None)
    return environment


def _run(command, environment, *, capture=False):
    return subprocess.run(command, cwd=REPO, env=environment, check=True,
                          text=True, capture_output=capture)


def _compose(arguments, environment, *, capture=False):
    return _run(["docker", "compose", "--env-file", "/dev/null", "-p", PROJECT,
                 "-f", str(REPO / "docker-compose.zip-manual.yml"), *arguments],
                environment, capture=capture)


def _local_daemon(environment):
    override = environment.get("DOCKER_HOST", "")
    if override and not override.startswith("unix://"):
        raise ValueError("Remote Docker endpoints are outside this operation")
    endpoint = _run(["docker", "context", "inspect", "--format",
                     '{{(index .Endpoints "docker").Host}}'], environment, capture=True).stdout.strip()
    if not endpoint.startswith("unix://"):
        raise ValueError("Only a local Unix-socket Docker context is allowed")


def _roots(*, create=False):
    home = REPO / ".fama-zip-manual"
    roots = (home, home / "imports", home / "attempts")
    for root in roots:
        if root.is_symlink() or root.absolute() != root.resolve():
            raise ValueError("Manual roots must have physical, stable absolute paths")
        if create and not root.exists():
            root.mkdir(mode=0o700)
        info = root.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Manual roots must be private and owned by the invoking user")
    if roots[1].stat().st_dev != roots[2].stat().st_dev:
        raise ValueError("Import and attempt roots must share a filesystem")
    return roots


@contextmanager
def _worker_lock(home):
    info = home.stat()
    if (home.is_symlink() or home != home.resolve() or info.st_uid != os.getuid()
            or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077):
        raise ValueError("Worker lock requires the private physical manual root")
    descriptor = os.open(home / "worker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield descriptor
    finally:
        os.close(descriptor)


def _check(environment):
    running = _compose(["ps", "--status", "running", "--services", "backend"],
                       environment, capture=True).stdout.split()
    invocation = (["exec", "-T", "backend"] if "backend" in running else
                  ["run", "--rm", "--no-deps", "--pull", "never", "-T", "backend"])
    _compose([*invocation,
              "python", "-m", "scripts.prepare_zip_manual_database", "--database-url",
              CONTAINER_URL, "--check"], environment)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "init", "up", "worker", "check", "status", "stop"),
                        help="build images; init empty DB explicitly; up API/UI; worker in foreground; check schema; status; stop without deletion")
    parser.add_argument("--writers-stopped", action="store_true",
                        help="Required only for init: acknowledge stopped API and all external workers.")
    args = parser.parse_args(argv)
    if args.writers_stopped != (args.action == "init"):
        parser.error("init requires --writers-stopped; other actions do not accept it")
    try:
        environment = _environment()
        _local_daemon(environment)
        if args.action == "build":
            _compose(["build"], environment)
        elif args.action == "status":
            _compose(["ps", "-a"], environment)
        elif args.action == "init":
            active = _compose(["ps", "--status", "running", "--services"], environment,
                              capture=True).stdout.split()
            if any(service != "db" for service in active):
                raise ValueError("Stop the manual API/frontend and external worker before initialization")
            home, _, _ = _roots(create=True)
            with _worker_lock(home):
                _compose(["up", "-d", "--wait", "--wait-timeout", "60", "db"], environment)
                _compose(["run", "--rm", "--no-deps", "--pull", "never", "-T", "backend",
                          "python", "-m", "scripts.prepare_zip_manual_database", "--database-url",
                          CONTAINER_URL, "--initialize", "--writers-stopped"], environment)
        elif args.action == "up":
            _roots()
            _compose(["up", "-d", "--wait", "--wait-timeout", "60", "db"], environment)
            _check(environment)
            _compose(["up", "-d", "--wait", "--wait-timeout", "180", "backend", "frontend"], environment)
            _serve_ui()
        elif args.action == "worker":
            home, imports, attempts = _roots()
            python = REPO / ".venv/bin/python"
            if not python.is_file():
                raise ValueError("An existing validated project interpreter is required; do not install automatically")
            _check(environment)
            environment["DATABASE_URL"] = HOST_URL
            with _worker_lock(home) as descriptor:
                os.set_inheritable(descriptor, True)
                os.chdir(REPO / "backend")
                os.execvpe(str(python), [str(python), "-B", "-m", "scripts.run_dataset_import_worker",
                            "--database-url", HOST_URL, "--import-root", str(imports),
                            "--staging-root", str(attempts), "--local-only", "--watch"], environment)
        elif args.action == "check":
            _roots()
            _check(environment)
        elif args.action == "stop":
            home = REPO / ".fama-zip-manual"
            if home.exists():
                with _worker_lock(home):
                    _compose(["stop"], environment)
            else:
                _compose(["stop"], environment)
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("Manual ZIP operation failed; preserve data, stop writers before init/stop, and inspect the operating manual.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
