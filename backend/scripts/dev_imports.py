"""Check regular Compose development imports or supervise their host worker."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]


def _physical_private(path):
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise ValueError("A physical path is required")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Links are not supported")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("A private directory owned by the invoking user is required")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "worker"),
                        help="Check an already running development backend, or run its local-only worker in this terminal; no migrations/startup.")
    args = parser.parse_args(argv)
    try:
        if os.getuid() == 0:
            raise ValueError("Non-root user required")
        environment = dict(os.environ, HOST_UID=str(os.getuid()), HOST_GID=str(os.getgid()),
                           FAMA_DEV_IMPORT_ROOT=str(REPO / "backend/data-dev/dataset-imports"))
        if environment.get("DOCKER_HOST") and not environment["DOCKER_HOST"].startswith("unix://"):
            raise ValueError("Only a local Docker socket is supported")

        def run(arguments):
            return subprocess.run(["docker", *arguments], cwd=REPO, env=environment,
                                  check=True, capture_output=True, text=True, timeout=30).stdout

        endpoint = run(["context", "inspect", "--format", '{{(index .Endpoints "docker").Host}}']).strip()
        if not endpoint.startswith("unix://"):
            raise ValueError("Only local Docker is supported")
        payload = run(["compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml",
                       "exec", "-T", "backend", "python", "-B", "-m",
                       "scripts.check_dev_import_database", "--worker-config"])
        config = json.loads(payload)
        root = _physical_private(REPO / "backend/data-dev/dataset-imports")
        if config["import_root"] != str(root):
            raise ValueError("Backend and host must use the same physical root")
        from urllib.parse import urlsplit
        url = urlsplit(config["database_url"])
        if (url.scheme != "postgresql+psycopg2" or url.hostname != "172.30.253.30"
                or url.port != 5432 or not url.path.strip("/") or url.query or url.fragment):
            raise ValueError("Expected the fixed development bridge database")
        limits = config["limits_environment"]
        if not isinstance(limits, dict) or any(not key.startswith("FAMA_IMPORT_")
                                              or not isinstance(value, str)
                                              for key, value in limits.items()):
            raise ValueError("Invalid development configuration")
        if args.action == "check":
            print("Development import schema checked; host connectivity and sandbox execution remain untested.")
            return 0
        attempts = REPO / "backend/data-dev/dataset-import-attempts"
        attempts.mkdir(mode=0o700, exist_ok=True)
        _physical_private(attempts)
        if root.stat().st_dev != attempts.stat().st_dev:
            raise ValueError("Import and attempt directories must share a filesystem")
        descriptor = os.open(root / "dev-worker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Credentials remain in process memory, not worker process argv/logs.
            for key in tuple(os.environ):
                if key.startswith("FAMA_IMPORT_") or key in (
                        "DATABASE_URL", "GOOGLE_APPLICATION_CREDENTIALS", "GCP_KEY_PATH",
                        "GCS_BUCKET_NAME", "XC_API_KEY"):
                    os.environ.pop(key, None)
            os.environ.update(limits, PYTHON_DOTENV_DISABLED="1")
            os.chdir(REPO / "backend")
            sys.path.insert(0, str(REPO / "backend"))
            from scripts.run_dataset_import_worker import main as worker
            return worker(["--database-url", config["database_url"], "--import-root", str(root),
                           "--staging-root", str(attempts), "--local-only", "--watch"])
        finally:
            os.close(descriptor)
    except (Exception, SystemExit) as error:
        if isinstance(error, SystemExit) and error.code == 0:
            return 0
        parser.exit(1, "Development imports unavailable. Preserve data and inspect the development "
                    "manual; no services or migrations were started by this command.\n")


if __name__ == "__main__":
    raise SystemExit(main())
