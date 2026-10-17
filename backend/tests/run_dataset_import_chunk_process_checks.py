"""Private synthetic chunk durability proof; no production crash hooks."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()


def child(root, action):
    sys.path.insert(0, str(BACKEND))
    database = root / "chunks.sqlite"

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
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    from app.routes.dataset_imports import router, get_import_user, get_import_service
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_zip import ImportLimits
    from scripts.migrate_dataset_import_jobs import migrate_jobs
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_import_chunks import migrate_chunks

    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 3, "check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    service = DatasetImports(root / "managed", limits=ImportLimits(free_bytes=1))
    app = FastAPI()
    app.include_router(router)
    owner = 1
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=owner)
    app.dependency_overrides[get_import_service] = lambda: service

    def dependency():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    base = "/api/ingestion/imports"

    def barrier():
        print("READY", flush=True)
        assert sys.stdin.readline().strip() == "GO", "Barrier not released"

    def dump():
        with engine.connect() as conn:
            return hashlib.sha256("\n".join(conn.connection.driver_connection.iterdump()).encode()).hexdigest()

    original_fsync, original_replace = os.fsync, os.replace
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            if action == "prepare":
                Base.metadata.create_all(engine)
                migrate_jobs(engine, writers_stopped=True)
                migrate_receipts(engine, writers_stopped=True)
                migrate_chunks(engine, writers_stopped=True)
                response = client.post(base, json={"request_key": "source", "name": "Source"})
                assert response.status_code == 200, response.text
                identity = response.json()["id"]
                response = client.post(f"{base}/{identity}/receipt", json={"name": "tiny.zip", "size_bytes": 10})
                assert response.status_code == 200 and response.json()["chunk_bytes"] == 4
                owner = 2
                other = client.post(base, json={"request_key": "other", "name": "Other"}).json()["id"]
                (root / "ids.json").write_text(json.dumps({"id": identity, "other": other}))
                result = {"prepared": True}
            else:
                mapping = json.loads((root / "ids.json").read_text())
                identity = mapping["id"]
                url = f"{base}/{identity}/receipt"
                partial = service.root / "staging" / identity / "receiving.part"
                archive = partial.with_name("archive.zip")

                def put(index, block):
                    return client.put(f"{url}/chunks/{index}", content=block, headers={
                        "Content-Type": "application/octet-stream", "X-Chunk-Offset": str(index * 4),
                        "X-Chunk-SHA256": hashlib.sha256(block).hexdigest()})

                if action in ("before-fsync", "after-append", "append", "replay"):
                    if action == "before-fsync":
                        def fsync(fd):
                            if os.readlink(f"/proc/self/fd/{fd}") == str(partial):
                                barrier()
                            return original_fsync(fd)
                        os.fsync = fsync
                    elif action == "after-append":
                        @event.listens_for(engine, "before_cursor_execute")
                        def before_insert(conn, cursor, statement, parameters, context, many):
                            if statement.startswith("INSERT INTO dataset_import_chunk ("):
                                assert partial.read_bytes() == b"abcd"
                                barrier()
                    before = dump()
                    response = put(0, b"abcd")
                    assert response.status_code == 200, response.text
                    assert response.json()["received_bytes"] == 4
                    if action == "replay":
                        assert dump() == before
                    result = {"received_bytes": 4}
                elif action == "fill":
                    assert put(1, b"efgh").status_code == 200
                    assert put(2, b"ij").status_code == 200
                    result = {"received_bytes": 10}
                elif action in ("rename", "finalize", "sealed-replay"):
                    if action == "rename":
                        def replace(source, target, *args, **kwargs):
                            result = original_replace(source, target, *args, **kwargs)
                            if Path(target) == archive:
                                barrier()
                            return result
                        os.replace = replace
                    before = dump()
                    response = client.post(url + "/finalize")
                    assert response.status_code == 200, response.text
                    assert response.json()["status"] == "sealed"
                    assert archive.read_bytes() == b"abcdefghij" and not partial.exists()
                    if action == "sealed-replay":
                        assert dump() == before
                    result = {"sealed": True}
                elif action in ("inspect", "probe", "cleanup-recovery"):
                    if action == "probe":
                        assert client.post(url + "/cancel").status_code == 409
                        owner = 2
                        # This operation needs the same queue gate: success while
                        # receipt I/O is paused proves it is not held across I/O.
                        response = client.put(f"{base}/{mapping['other']}/archive", content=b"other",
                                              headers={"Content-Type": "application/zip"})
                        assert response.status_code == 200, response.text
                        owner = 1
                    if action in ("probe", "cleanup-recovery"):
                        now = time.time() + service.limits.ttl_seconds + 10
                        time.time = lambda: now
                        with sessions() as db:
                            service.cleanup(db)
                    before = dump()
                    response = client.get(url)
                    assert response.status_code == 200, response.text
                    page = client.get(url + "/chunks").json()
                    assert dump() == before
                    result = dict(status=response.json()["status"], received_bytes=response.json()["received_bytes"],
                                  chunks=page["total"])
                else:
                    raise AssertionError(action)
            print(json.dumps(result), flush=True)
    finally:
        os.fsync, os.replace = original_fsync, original_replace
        engine.dispose()


def coordinator():
    inventory = BACKEND.parent / "docs/receipts/training-checks-inventory.json"
    protected = [BACKEND / "tests/run_isolated_training_checks.py", BACKEND / "tests/training_host_guard.py",
                 inventory] + [BACKEND.parent / name for name in json.loads(inventory.read_text())["paths"]]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    with tempfile.TemporaryDirectory(prefix="import-chunks-", dir="/tmp/opencode") as temporary:
        root = Path(temporary)
        assert root.stat().st_mode & 0o077 == 0
        environment = {"PATH": os.defpath, "HOME": str(root), "TMPDIR": str(root),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": "sqlite://",
            "CUDA_VISIBLE_DEVICES": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1", "FAMA_IMPORT_CHUNK_BYTES": "4"}
        children = []

        def launch(action):
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--child", str(root), action],
                cwd=BACKEND, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            children.append(process)
            return process

        def finish(process):
            output, errors = process.communicate(timeout=25)
            assert process.returncode == 0, (process.returncode, output, errors)
            return json.loads(output)

        def ready(process):
            deadline, line = time.monotonic() + 25, bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while not line.endswith(b"\n"):
                    remaining = deadline - time.monotonic()
                    assert remaining > 0 and selector.select(remaining), "Barrier deadline"
                    byte = os.read(process.stdout.fileno(), 1)
                    assert byte and len(line) < 100, "Partial-read barrier protocol"
                    line.extend(byte)
            assert line == b"READY\n", line
            assert process.poll() is None, "No public success before durable boundary"

        def crash(process):
            process.kill()
            output, errors = process.communicate(timeout=5)
            assert process.returncode == -9 and output == "" and errors == "", (output, errors)

        try:
            assert finish(launch("prepare")) == {"prepared": True}
            empty = {"status": "receiving", "received_bytes": 0, "chunks": 0}
            process = launch("before-fsync")
            ready(process)
            assert finish(launch("probe")) == empty
            crash(process)
            assert finish(launch("inspect")) == empty
            process = launch("after-append")
            ready(process)
            assert finish(launch("inspect")) == empty
            crash(process)
            assert finish(launch("inspect")) == empty
            assert finish(launch("append")) == {"received_bytes": 4}
            assert finish(launch("replay")) == {"received_bytes": 4}
            assert finish(launch("inspect")) == {"status": "receiving", "received_bytes": 4, "chunks": 1}
            assert finish(launch("fill")) == {"received_bytes": 10}
            process = launch("rename")
            ready(process)
            crash(process)
            assert finish(launch("cleanup-recovery")) == {"status": "receiving", "received_bytes": 10, "chunks": 3}
            assert finish(launch("finalize")) == {"sealed": True}
            assert finish(launch("sealed-replay")) == {"sealed": True}
            assert finish(launch("inspect")) == {"status": "sealed", "received_bytes": 10, "chunks": 3}
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected} == before
    assert not root.exists()
    print("CHUNK_PROCESS_PASS pre_fsync_no_success=true durable_append_restart=true rename_restart=true "
          "fresh_process_replay=true gate_free_during_io=true cleanup_exclusion=true "
          "original_guard_protected30_unchanged=true private_cleanup=true")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]), sys.argv[3])
    else:
        coordinator()
