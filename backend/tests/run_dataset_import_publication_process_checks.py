"""Real import publication crash/restart proof in private synthetic storage only.

Separate from the unchanged memory-only runner. No production crash hooks.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import wave
import zipfile

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()


def child(root, action):
    sys.path.insert(0, str(BACKEND))
    database = root / "publication.sqlite"

    def isolation(event, args):
        if event == "socket.connect":
            raise RuntimeError("Network forbidden")
        if event == "open" and not isinstance(args[0], int):
            if Path(os.fsdecode(args[0])).name in (".env", ".pgpass", "token"):
                raise RuntimeError("Credential access forbidden")
        if event == "sqlite3.connect" and Path(args[0]).resolve() != database:
            raise RuntimeError("Only the private synthetic database is authorized")

    sys.addaudithook(isolation)
    from tests.training_host_guard import install_guard
    install_guard([root])
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    from app.routes.dataset_imports import router, get_import_service, get_import_user
    from app.services.dataset_import_jobs import ImportJobQueue
    from app.services.dataset_import_worker import ImportJobWorker
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_zip import ImportLimits
    from app.services.dataset_zip import validate_zip as synthetic_validator
    from app.services import dataset_import_execution

    # This original-guard procedure proves journal/restart fencing, not OS
    # containment. Its known synthetic archive uses the direct test validator;
    # the separate T4 process proof exercises the production sandbox default.
    dataset_import_execution.validate_zip = synthetic_validator

    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 5})
    sessions = sessionmaker(bind=engine)
    service = DatasetImports(root / "imports", limits=ImportLimits(free_bytes=1))
    app = FastAPI()
    app.include_router(router)
    def database_session():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database_session
    app.dependency_overrides[get_import_service] = lambda: service
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    base = "/api/ingestion/imports"
    # Controlled clocks and disabled heartbeat wakeups remove sleep-based lease
    # assumptions. Only test children alter these seams, never the operator CLI.
    ImportJobQueue._now = lambda self, db: 160.0 if action == "recover" else 100.0
    original_worker = ImportJobWorker.__init__
    def worker(self, *args, **kwargs):
        original_worker(self, *args, **kwargs, heartbeat_wait=lambda stop, interval: stop.wait())
    ImportJobWorker.__init__ = worker
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            if action == "prepare":
                from scripts.migrate_dataset_import_jobs import migrate_jobs
                Base.metadata.create_all(engine)
                migrate_jobs(engine, writers_stopped=True)
                service._initialize()
                (service.root / "attempts").mkdir(mode=0o700)
                source = client.post(base, json={"request_key": "source", "name": "Synthetic"}).json()
                audio = io.BytesIO()
                with wave.open(audio, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(b"\x01\x00" * 1600)
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w") as zipped:
                    zipped.writestr("birds/a.wav", audio.getvalue())
                assert client.put(f"{base}/{source['id']}/archive", content=archive.getvalue(),
                                  headers={"Content-Type": "application/zip"}).status_code == 200
                admitted = client.post(f"{base}/{source['id']}/preview", json={"request_key": "preview", "root": ""})
                assert admitted.status_code == 202
                (root / "source.json").write_text(json.dumps({"id": source["id"]}))
                result = {"prepared": True}
            elif action in ("run", "crash", "recover"):
                if action == "crash":
                    from app.services import dataset_import_execution as execution
                    durable = execution._durable_directory
                    def stop_after_rename(path):
                        if path == service.root / "objects":
                            print("READY", flush=True)
                            if sys.stdin.readline().strip() != "GO":
                                raise RuntimeError("Crash barrier not released")
                        return durable(path)
                    execution._durable_directory = stop_after_rename
                # Invoke the real module entry path (including parsing and engine
                # creation) in each fresh process, without a production test flag.
                sys.argv = ["run_dataset_import_worker", "--database-url", f"sqlite:///{database}",
                            "--import-root", str(service.root), "--staging-root", str(service.root / "attempts")]
                import runpy
                runpy.run_module("scripts.run_dataset_import_worker", run_name="__main__")
                raise AssertionError("CLI entry must exit")
            else:
                source = json.loads((root / "source.json").read_text())["id"]
                state = client.get(f"{base}/{source}").json()
                if action in ("confirm", "replay"):
                    response = client.post(f"{base}/{source}/confirm", json={
                        "request_key": action, "preview_token": state["preview_token"]})
                    assert response.status_code == 202, response.text
                    result = response.json()
                elif action == "inspect":
                    datasets = client.get(base + "/datasets").json()["datasets"]
                    files = client.get(f"{base}/datasets/{datasets[0]['id']}/files").json()["files"] if datasets else []
                    for file in files:
                        response = client.get(f"{base}/datasets/{datasets[0]['id']}/files/{file['sha256']}")
                        assert response.status_code == 200
                        assert hashlib.sha256(response.content).hexdigest() == file["sha256"]
                    result = {"state": state, "datasets": datasets, "files": files}
                else:
                    raise ValueError("Unknown synthetic phase")
            print(json.dumps(result), flush=True)
    finally:
        engine.dispose()


def coordinator():
    if Path.cwd().resolve() != BACKEND or not __debug__:
        raise SystemExit("Run non-optimized Python from backend")
    protected = [BACKEND / "tests/run_isolated_training_checks.py", BACKEND / "tests/training_host_guard.py",
                 BACKEND.parent / "docs/receipts/training-checks-inventory.json"]
    inventory = json.loads(protected[-1].read_text())
    protected.extend(BACKEND.parent / name for name in inventory["paths"])
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    children = []
    with tempfile.TemporaryDirectory(prefix="fama-publication-proof-", dir="/tmp/opencode") as directory:
        root = Path(directory).resolve()
        root.chmod(0o700)
        environment = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1",
                       "DATABASE_URL": "sqlite://", "CUDA_VISIBLE_DEVICES": "", "HOME": str(root),
                       "TMPDIR": str(root), "XDG_CACHE_HOME": str(root), "PYTHONHASHSEED": "0"}
        def launch(action):
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--child", str(root), action],
                                       cwd=BACKEND, env=environment, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            children.append(process)
            return process
        def finish(process):
            output, errors = process.communicate(timeout=20)
            assert process.returncode == 0, errors
            return json.loads(output)
        try:
            assert finish(launch("prepare")) == {"prepared": True}
            assert finish(launch("run")) == {"claimed": True}
            preview = finish(launch("inspect"))
            assert preview["state"]["status"] == "ready"
            assert preview["state"]["execution"]["status"] == "succeeded"
            confirm = finish(launch("confirm"))
            interrupted = launch("crash")
            deadline = time.monotonic() + 20
            line = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(interrupted.stdout, selectors.EVENT_READ)
                while not line.endswith(b"\n"):
                    remaining = deadline - time.monotonic()
                    assert remaining > 0 and selector.select(remaining), "Crash barrier deadline"
                    byte = os.read(interrupted.stdout.fileno(), 1)
                    assert byte and len(line) < 100, "Crash barrier protocol"
                    line.extend(byte)
            assert line == b"READY\n"
            interrupted.kill()
            interrupted.wait(timeout=5)
            assert interrupted.returncode < 0
            journal = finish(launch("inspect"))
            assert journal["state"]["status"] == "committing"
            assert journal["state"]["execution"]["id"] == confirm["id"]
            assert journal["state"]["execution"]["status"] == "running"
            assert journal["datasets"] == [] and journal["files"] == []
            assert len(list((root / "imports/objects").glob("*/*.wav"))) == 1
            assert finish(launch("recover")) == {"claimed": True}
            published = finish(launch("inspect"))
            assert published["state"]["status"] == "imported"
            assert published["state"]["execution"]["status"] == "succeeded"
            assert published["state"]["execution"]["result"]["added_count"] == 1
            assert len(published["datasets"]) == len(published["files"]) == 1
            assert published["datasets"][0]["revision"] == 1
            finish(launch("replay"))
            assert finish(launch("run")) == {"claimed": True}
            replayed = finish(launch("inspect"))
            assert replayed["files"] == published["files"]
            assert replayed["datasets"] == published["datasets"]
            assert finish(launch("run")) == {"claimed": False}
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
    assert not root.exists()
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected} == before
    print(json.dumps({"publication_crash_restart": "passed", "http_readback_and_download": "passed",
                      "idempotent_replay": "passed", "cli_one_shot": "passed",
                      "private_cleanup": True, "protected_inputs_unchanged": True,
                      "postgresql": "not_tested", "real_gcs": "not_tested"}))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]).resolve(strict=True), sys.argv[3])
    elif len(sys.argv) == 1:
        coordinator()
    else:
        raise SystemExit("No user-supplied probe paths or database URLs are accepted")
