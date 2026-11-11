"""Offline structural checks only; never builds images or contacts Docker's daemon."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def check_layout():
    entries = (BACKEND / "bootstrap/source-files.txt").read_text().splitlines()
    if not entries or len(set(entries)) != len(entries):
        raise ValueError("Unexpected bootstrap source inventory")
    with tempfile.TemporaryDirectory(prefix="fama-bootstrap-layout-", dir="/tmp") as directory:
        private = Path(directory)
        context = private / "context"
        context.mkdir(mode=0o700)
        for name in entries:
            relative = Path(name)
            if (relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py"
                    or relative.parts[0] not in ("app", "migrations", "scripts")):
                raise ValueError("Unsafe source inventory entry")
            source = BACKEND / relative
            if any(path.is_symlink() for path in (source, *source.parents)) or not source.is_file():
                raise ValueError("Source must be an ordinary physical file")
            target = context / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for name in ("Dockerfile", "requirements.txt"):
            shutil.copyfile(BACKEND / "bootstrap" / name, context / name)
        actual = {p.relative_to(context).as_posix() for p in context.rglob("*") if p.is_file()}
        if actual != set(entries) | {"Dockerfile", "requirements.txt"}:
            raise ValueError("Build context has undeclared files")
        password = private / "synthetic-password"
        passfile = private / "synthetic-passfile"
        for path in (password, passfile):
            path.touch(mode=0o600)
            path.write_text("synthetic-layout-test-not-a-runtime-credential\n")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(private),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1",
            "FAMA_TRAINING_BUILD_CONTEXT": str(context),
            "FAMA_TRAINING_UID": "10001", "FAMA_TRAINING_GID": "10001",
            "FAMA_TRAINING_PASSWORD_FILE": str(password),
            "FAMA_TRAINING_PGPASS_FILE": str(passfile),
        }
        command = ["docker", "--host", "unix:///var/run/docker.sock", "compose", "--env-file", "/dev/null",
                   "-f", str(ROOT / "docker-compose.training-dev.yml"),
                   "--profile", "bootstrap", "config", "--format", "json"]
        rendered = subprocess.run(command, env=environment, cwd=private, check=True,
                                  capture_output=True, text=True, timeout=20)
        config = json.loads(rendered.stdout)
        if config["name"] != "fama-training-dev" or set(config["services"]) != {"db", "bootstrap"}:
            raise ValueError("Unexpected project or services")
        db, bootstrap = (config["services"][name] for name in ("db", "bootstrap"))
        if any(service.get("ports") or service.get("container_name") for service in (db, bootstrap)):
            raise ValueError("No published ports or inherited container names permitted")
        networks = config["networks"]
        if set(networks) != {"bootstrap"} or networks["bootstrap"].get("internal") is not True:
            raise ValueError("A dedicated internal network is required")
        if any(set(service["networks"]) != {"bootstrap"} for service in (db, bootstrap)):
            raise ValueError("Unexpected network attachment")
        if (len(db["volumes"]) != 1 or db["volumes"][0]["type"] != "volume"
                or db["volumes"][0]["source"] != "training_pgdata"
                or bootstrap.get("volumes")):
            raise ValueError("No previous storage may be mounted")
        if (set(config["volumes"]) != {"training_pgdata"}
                or config["volumes"]["training_pgdata"].get("external")):
            raise ValueError("Unexpected PostgreSQL volume")
        if bootstrap["build"]["context"] != str(context) or not bootstrap["read_only"]:
            raise ValueError("Bootstrap context/rootfs mismatch")
        for service in (db, bootstrap):
            if any(key.startswith(("GOOGLE", "GCS", "GCP", "XC_")) for key in service["environment"]):
                raise ValueError("Cloud configuration is forbidden")
        probe = '''import importlib,json,pathlib,sys
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
def audit(event,args):
    if event=="socket.connect": raise RuntimeError("Network forbidden")
    if event=="open" and not isinstance(args[0],int) and pathlib.Path(args[0]).name in (".env",".pgpass","token"):
        raise RuntimeError("Credential reads forbidden")
sys.addaudithook(audit)
for name in json.loads(sys.argv[2]): importlib.import_module(name)
for name in sys.modules:
    if name.split(".")[0] in ("torch","tensorflow","google","fastapi","pydantic","training","poc"):
        raise RuntimeError("Unexpected runtime dependency")
print(json.dumps({"source_imports":len(json.loads(sys.argv[2])),"cloud_ml_runtime_loaded":False}))
'''
        # Alembic loads its environment and revision files itself; they are not importable modules.
        modules = [name.removesuffix(".py").removesuffix("/__init__").replace("/", ".") for name in entries
                   if name != "migrations/env.py" and not name.startswith("migrations/versions/")]
        result = subprocess.run([sys.executable, "-B", "-c", probe, str(context), json.dumps(modules)],
                                cwd=private, env=environment, capture_output=True, text=True,
                                check=True, timeout=20)
        result = json.loads(result.stdout)
        result.update(compose_services=2, context_files=len(actual), daemon_required=False,
                      postgres_tested=False, resources_created=False)
        return result


if __name__ == "__main__":
    print(json.dumps(check_layout(), sort_keys=True))
