"""Synthetic receipt contention/restart proof, separate from the memory runner."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()


def child(root, action, key):
    sys.path.insert(0, str(BACKEND))
    database = root / "receipts.sqlite"

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
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.database import Base, get_db
    from app.routes.dataset_imports import router, get_import_user, get_import_service
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_zip import ImportLimits
    from scripts.migrate_dataset_import_jobs import migrate_jobs
    from scripts.migrate_dataset_import_receipts import migrate_receipts, main

    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 10, "check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    # Six tiny admissions must reach the reservation seam, not the predecessor's
    # active-import count; the byte budgets below remain 50/80 bytes.
    service = DatasetImports(root / "managed", limits=ImportLimits(
        received_bytes=20, expanded_bytes=30, free_bytes=1, concurrent_imports=20))
    app = FastAPI()
    app.include_router(router)
    owner = int(key.split(":")[0]) if ":" in key else 1
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=owner)
    app.dependency_overrides[get_import_service] = lambda: service

    def dependency():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    base = "/api/ingestion/imports"

    def dump():
        with engine.connect() as db:
            return hashlib.sha256("\n".join(db.connection.driver_connection.iterdump()).encode()).hexdigest()

    mapping = json.loads((root / "ids.json").read_text()) if (root / "ids.json").exists() else {}
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            if action == "prepare":
                Base.metadata.create_all(engine)
                migrate_jobs(engine, writers_stopped=True)
                before = dump()
                try:
                    migrate_receipts(engine)
                except ValueError as error:
                    assert str(error) == "stop_writers_before_receipt_migration"
                else:
                    raise AssertionError("Missing acknowledgement accepted")
                assert dump() == before
                assert migrate_receipts(engine, writers_stopped=True) == {"version": 1, "verified": True}
                for user in (1, 2, 3):
                    owner = user
                    for number in (0, 1):
                        identity = f"{user}:{number}"
                        response = client.post(base, json={"request_key": identity, "name": identity})
                        assert response.status_code == 200, response.text
                        mapping[identity] = response.json()["id"]
                (root / "ids.json").write_text(json.dumps(mapping))
                result = {"prepared": True}
            elif action == "cli":
                import contextlib
                import io
                output, errors = io.StringIO(), io.StringIO()
                before = dump()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    assert main(["--database-url", f"sqlite:///{database}", "--writers-stopped"]) == 0
                assert output.getvalue() == '{"version": 1, "verified": true}\n'
                assert errors.getvalue() == "" and dump() == before
                result = {"cli": True}
            elif action == "inspect":
                before, result = dump(), {}
                for identity, value in mapping.items():
                    owner = int(identity.split(":")[0])
                    response = client.get(f"{base}/{value}/receipt")
                    assert response.status_code in (200, 404), response.text
                    result[identity] = response.json() if response.status_code == 200 else None
                assert dump() == before
            else:
                url = f"{base}/{mapping[key]}"
                if action in ("admit", "reject"):
                    if action == "admit":
                        print("READY", flush=True)
                        assert sys.stdin.readline().strip() == "GO"
                    before = dump()
                    response = client.post(url + "/receipt", json={"name": "birds.zip", "size_bytes": 10})
                    assert response.status_code in (200, 429), response.text
                    if response.status_code == 429 and action == "reject":
                        assert dump() == before
                    result = {"status": response.status_code}
                elif action == "fail-delete":
                    directory = service.root / "staging" / mapping[key]
                    directory.mkdir(mode=0o700)
                    (directory / "part").write_bytes(b"synthetic")
                    original = shutil.rmtree

                    def failed(path, *args, **kwargs):
                        if Path(path) == directory:
                            raise OSError("Synthetic deletion failure")
                        return original(path, *args, **kwargs)

                    shutil.rmtree = failed
                    assert client.post(url + "/cancel").status_code == 500
                    assert (directory / "part").read_bytes() == b"synthetic"
                    assert client.get(url + "/receipt").json()["reserved_bytes"] == 40
                    result = {"held": True}
                elif action == "cancel":
                    response = client.post(url + "/cancel")
                    assert response.status_code == 200, response.text
                    receipt = client.get(url + "/receipt").json()
                    assert receipt["reserved_bytes"] == 0 and receipt["status"] == "cancelled"
                    assert not (service.root / "staging" / mapping[key]).exists()
                    result = {"released": True}
                else:
                    raise AssertionError(action)
        print(json.dumps(result), flush=True)
    finally:
        engine.dispose()


def coordinator():
    inventory = BACKEND.parent / "docs/receipts/training-checks-inventory.json"
    protected = [BACKEND / "tests/run_isolated_training_checks.py", BACKEND / "tests/training_host_guard.py",
                 inventory] + [BACKEND.parent / name for name in json.loads(inventory.read_text())["paths"]]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    # The coordinator owns exactly this fresh temporary root. Never accept an
    # ambient root override or adopt a previous run's database for this proof.
    with tempfile.TemporaryDirectory(prefix="import-receipt-", dir="/tmp/opencode") as temporary:
        root = Path(temporary)
        assert root.stat().st_mode & 0o077 == 0
        environment = {"PATH": os.defpath, "HOME": str(root), "TMPDIR": str(root),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": "sqlite://",
            "CUDA_VISIBLE_DEVICES": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1", "FAMA_IMPORT_RESERVED_BYTES_GLOBAL": "80",
            "FAMA_IMPORT_RESERVED_BYTES_PER_OWNER": "50"}
        children = []

        def launch(action, key="0"):
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--child", str(root), action, key],
                cwd=BACKEND, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            children.append(process)
            return process

        def finish(process):
            output, errors = process.communicate(timeout=20)
            assert process.returncode == 0, (process.returncode, output, errors)
            return json.loads(output)

        def ready(process):
            deadline, line = time.monotonic() + 20, bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while not line.endswith(b"\n"):
                    remaining = deadline - time.monotonic()
                    assert remaining > 0 and selector.select(remaining), "Readiness deadline"
                    byte = os.read(process.stdout.fileno(), 1)
                    assert byte and len(line) < 100, "Readiness protocol"
                    line.extend(byte)
            assert line == b"READY\n", line

        def release(process):
            process.stdin.write("GO\n")
            process.stdin.flush()

        try:
            assert finish(launch("prepare")) == {"prepared": True}
            assert finish(launch("cli")) == {"cli": True}
            keys = [f"{user}:{number}" for user in (1, 2, 3) for number in (0, 1)]
            contenders = [launch("admit", key) for key in keys]
            for process in contenders:
                ready(process)
            for process in contenders:
                release(process)
            results = [finish(process) for process in contenders]
            accepted = [key for key, result in zip(keys, results) if result["status"] == 200]
            assert len(accepted) == 2 and len({key.split(":")[0] for key in accepted}) == 2, results
            state = finish(launch("inspect"))
            assert sum(row["reserved_bytes"] for row in state.values() if row) == 80
            assert finish(launch("reject", next(key for key in keys if key not in accepted)))["status"] == 429
            chosen = accepted[0]
            assert finish(launch("fail-delete", chosen)) == {"held": True}
            assert finish(launch("inspect"))[chosen]["reserved_bytes"] == 40
            assert finish(launch("cancel", chosen)) == {"released": True}
            assert finish(launch("inspect"))[chosen]["reserved_bytes"] == 0
            successor = next(key for key in keys if key.split(":")[0] == chosen.split(":")[0] and key != chosen)
            process = launch("admit", successor)
            ready(process)
            release(process)
            assert finish(process)["status"] == 200
            state = finish(launch("inspect"))
            assert sum(row["reserved_bytes"] for row in state.values() if row) == 80
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected} == before
    assert not root.exists()
    print("RECEIPT_PROCESS_PASS contenders=6 accepted=2 owner_distinct=2 durable_release=true "
          "failed_delete_holds=true inert_reads=true rejection_dump_unchanged=true cli_exact_output=true "
          "original_guard_protected30_unchanged=true private_cleanup=true")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        coordinator()
