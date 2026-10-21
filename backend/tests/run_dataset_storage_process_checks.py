"""Private SQLite proof of shared admission, crash and real process locks.

Mount and availability observations are synthetic; this does not qualify quotas.
Run separately from the memory-only suite. No services, cloud or real datasets.
"""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()


def child(root, action):
    sys.path.insert(0, str(BACKEND))
    database = root / "synthetic.sqlite"

    def isolation(event, args):
        if event == "socket.connect":
            raise RuntimeError("Network forbidden")
        if event == "sqlite3.connect" and Path(args[0]).resolve() != database:
            raise RuntimeError("Only the private synthetic database is authorized")
        if event == "open" and not isinstance(args[0], int) and Path(os.fsdecode(args[0])).name in (".env", ".pgpass", "token"):
            raise RuntimeError("Credential access forbidden")

    sys.addaudithook(isolation)
    from tests.training_host_guard import install_guard
    install_guard([root])
    import builtins
    import fcntl
    import hashlib
    import io
    from types import SimpleNamespace
    from fastapi import HTTPException
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models.dataset_import import ImportedDataset
    from app.models.dataset_import_metadata import DatasetSummary
    from app.models.dataset_import_revision import DatasetRevision
    from app.models.dataset_export import DatasetExport
    from app.models.dataset_storage import StorageGrant
    from app.services import dataset_storage
    from app.services.dataset_storage import PhysicalStorage
    from app.services.dataset_imports import DatasetImports
    from app.services.dataset_import_receipts import reserve_receipt
    from app.services.dataset_exports import ExportQueue, ExportLimits
    from app.services.dataset_zip import ImportLimits
    from scripts.migrate_dataset_import_jobs import migrate_jobs
    from scripts.migrate_dataset_import_receipts import migrate_receipts
    from scripts.migrate_dataset_storage import migrate_storage
    from scripts.reconcile_dataset_storage import reconcile_storage

    # Host tmpfs advertises usrquota and is intentionally refused in production.
    # Substitute only the OS mount-observation seam for this protocol proof,
    # preserving real file SQLite, fsync, process death and flock operations.
    original_open = builtins.open
    def mount_view(path, *args, **kwargs):
        if isinstance(path, str) and path.startswith("/proc/self/fdinfo/"):
            descriptor = int(path.rsplit("/", 1)[1])
            if Path(os.readlink(f"/proc/self/fd/{descriptor}")).is_relative_to(root):
                with original_open(path, *args, **kwargs) as stream:
                    return io.StringIO("".join("mnt_id:\t999999\n" if line.startswith("mnt_id:") else line
                                              for line in stream))
        if path == "/proc/self/mountinfo":
            with original_open(path, *args, **kwargs) as stream:
                return io.StringIO(stream.read() + "999999 0 0:999 / /synthetic rw - tmpfs synthetic rw\n")
        return original_open(path, *args, **kwargs)
    builtins.open = mount_view

    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 3})
    sessions = sessionmaker(bind=engine)
    managed = root / "managed"
    service = DatasetImports(managed, limits=ImportLimits(received_bytes=20, expanded_bytes=30, free_bytes=5))
    if action.startswith("prepare"):
        service._initialize()
        for name in ("attempts", "exports"):
            (managed / name).mkdir(mode=0o700)
    roots = dict(imports=managed, objects=managed / "objects", attempts=managed / "attempts",
                 manifests=managed / "attempts", scratch=managed / "attempts", exports=managed / "exports")
    policy = PhysicalStorage(roots=roots, pools={role: "local" for role in roots}, free_floors={"local": 5})
    service.storage_policy = policy
    # Deterministic availability; actual external allocation is not certified.
    dataset_storage.shutil.disk_usage = lambda _: SimpleNamespace(free=4331)
    queue = ExportQueue(sessions, service, limits=ExportLimits(files=1, bytes=1, manifest_bytes=1))
    dataset = "d" * 32

    def barrier():
        print("READY", flush=True)
        assert sys.stdin.readline().strip() == "GO"

    try:
        if action.startswith("prepare"):
            Base.metadata.create_all(engine)
            migrate_jobs(engine, writers_stopped=True)
            migrate_receipts(engine, writers_stopped=True)
            migrate_storage(engine, writers_stopped=True)
            reconcile_storage(engine, policy=policy, apply=True, writers_stopped=True)
            with sessions.begin() as db:
                db.add(ImportedDataset(id=dataset, owner_id=1, name="Synthetic", description="", revision=1))
                db.add(DatasetSummary(dataset_id=dataset, revision=1, file_count=0, class_count=0, total_size_bytes=0))
                db.add(DatasetRevision(id="e" * 32, dataset_id=dataset, revision=1, owner_id=1,
                    name="Synthetic", description="", file_count=0, total_size_bytes=0, status="complete",
                    verified_count=0, verified_bytes=0, manifest_key="synthetic", manifest_generation="1",
                    manifest_sha256="f" * 64, manifest_size_bytes=1))
            if action == "prepare":
                with sessions() as db:
                    identity = service.create(db, 1, {"request_key": "source", "name": "Source", "description": ""})["id"]
                (root / "identity").write_text(identity)
            result = {"prepared": True}
        elif action in ("import", "export", "export-before-commit", "export-after-commit", "replay"):
            if action in ("import", "export"):
                barrier()
            if action == "export-before-commit":
                @event.listens_for(engine, "after_cursor_execute")
                def before_commit(conn, cursor, statement, parameters, context, many):
                    if statement.startswith("INSERT INTO dataset_storage_grant "):
                        barrier()
            try:
                if action == "import":
                    with sessions() as db:
                        value = reserve_receipt(service, db, 1, (root / "identity").read_text(), name="tiny.zip", size_bytes=10)
                    result = {"status": 200, "reserved_bytes": value["reserved_bytes"]}
                else:
                    value = queue.admit(1, dataset, 1, "process-export")
                    if action == "export-after-commit":
                        barrier()
                    result = {"status": 202, "id": value["id"]}
            except HTTPException as error:
                result = {"status": error.status_code}
        elif action == "inspect":
            with sessions() as db:
                grants = db.execute(select(StorageGrant.__table__)).mappings().all()
                exports = db.execute(select(DatasetExport.id)).scalars().all()
                snapshot = "\n".join(db.connection().connection.driver_connection.iterdump())
            result = dict(grants=len(grants), promised=sum(g["envelope_bytes"] for g in grants),
                          exports=exports, data_sha256=hashlib.sha256(snapshot.encode()).hexdigest())
        elif action.startswith("hold-"):
            path = roots["exports"] / ("a" * 32 + "-1-1")
            path.mkdir(mode=0o700, exist_ok=True)
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fcntl.flock(fd, fcntl.LOCK_SH if action == "hold-download" else fcntl.LOCK_EX)
                barrier()
            finally:
                os.close(fd)
            result = {"released": True}
        elif action == "cutover":
            try:
                result = reconcile_storage(engine, policy=policy, apply=True, writers_stopped=True)
            except ValueError as error:
                result = {"refused": str(error)}
        else:
            raise ValueError("Unknown synthetic action")
        print(json.dumps(result, sort_keys=True), flush=True)
    finally:
        engine.dispose()


def main():
    root = Path(tempfile.mkdtemp(prefix="dataset-storage-process-", dir="/tmp/opencode"))
    print("PRIVATE_SCRATCH", root, flush=True)
    processes = []

    def launch(case, action):
        process = subprocess.Popen([sys.executable, str(SCRIPT), "--child", str(case), action], cwd=BACKEND,
            env=dict(os.environ, HOME=str(case), TMPDIR=str(case), PYTHONDONTWRITEBYTECODE="1",
                     PYTHON_DOTENV_DISABLED="1", CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1"),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(process)
        return process

    def finish(process):
        out, err = process.communicate(timeout=12)
        assert process.returncode == 0, (out, err)
        return json.loads(out.strip().splitlines()[-1])

    def ready(process):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(12), "Synthetic barrier timeout"
            line = process.stdout.readline().strip()
        assert line == "READY", (line, process.stderr.read() if process.poll() is not None else "")

    def new_case(name, drained=False):
        case = root / name
        case.mkdir(mode=0o700)
        assert finish(launch(case, "prepare-drained" if drained else "prepare"))["prepared"]
        return case

    try:
        case = new_case("compete")
        contenders = [launch(case, action) for action in ("import", "export")]
        for process in contenders:
            ready(process)
        for process in contenders:
            process.stdin.write("GO\n"); process.stdin.flush()
        results = [finish(process) for process in contenders]
        assert sum(r["status"] == 507 for r in results) == 1, results
        assert sum(r["status"] in (200, 202) for r in results) == 1, results
        if results[0]["status"] == 200:
            assert results[0]["reserved_bytes"] == 40
        assert finish(launch(case, "inspect"))["promised"] <= 4326
        for point in ("before", "after"):
            case = new_case(point)
            before = finish(launch(case, "inspect"))
            process = launch(case, f"export-{point}-commit")
            ready(process)
            process.kill(); process.communicate(timeout=5)
            after = finish(launch(case, "inspect"))
            if point == "before":
                assert after == before
            else:
                assert after["grants"] == 1 and after["promised"] == 4326 and len(after["exports"]) == 1
                assert finish(launch(case, "replay"))["id"] == after["exports"][0]
                assert finish(launch(case, "inspect"))["grants"] == 1
        for kind in ("callback", "download"):
            case = new_case(kind, drained=True)
            process = launch(case, "hold-" + kind)
            ready(process)
            before = finish(launch(case, "inspect"))
            assert finish(launch(case, "cutover")) == {"refused": "writer_or_download_still_active"}
            assert finish(launch(case, "inspect")) == before
            process.stdin.write("GO\n"); process.stdin.flush()
            assert finish(process)["released"]
            assert finish(launch(case, "cutover"))["state"] == "active"
        print(json.dumps({"status": "passed", "scenarios": 5,
            "scope": "private file SQLite and real process locks; synthetic mount/availability; no quota, PostgreSQL or Btrfs qualification"}))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill(); process.communicate(timeout=5)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]), sys.argv[3])
    else:
        main()
