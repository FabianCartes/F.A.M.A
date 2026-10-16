"""Separate synthetic process proof; never relaxes the in-memory test runner.

Run from backend with the documented interpreter. The coordinator launches only
this file with an allowlisted environment. Every child installs the original
write guard before importing application code and authorizes exactly one private
SQLite file. No service, decoder, real dataset or cloud client is started.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()


def child(root, action, owner, key):
    sys.path.insert(0, str(BACKEND))
    database = root / "queue.sqlite"

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
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models.dataset_import import DatasetImport
    from app.models.dataset_import_job import ImportJob
    from app.models.dataset_import_metadata import ImportSummary
    from app.services.dataset_import_jobs import ImportJobQueue, JobLimits
    from scripts.migrate_dataset_import_jobs import migrate_jobs

    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 10})
    sessions = sessionmaker(bind=engine)
    queue = ImportJobQueue(sessions, limits=JobLimits(2, 1), clock=lambda: 100.0)
    try:
        if action == "prepare":
            Base.metadata.create_all(engine)
            migrate_jobs(engine, writers_stopped=True)
            with sessions.begin() as db:
                for user in (1, 2, 3):
                    for number in range(3):
                        db.add(DatasetImport(id=f"{user * 10 + number:032x}", owner_id=user,
                                            request_key=str(number), request={}, status="validating",
                                            archive_sha256="a" * 64, created_at=1, preview={},
                                            added_count=0, sync_status="pending"))
                        db.flush()
                        db.add(ImportSummary(import_id=f"{user * 10 + number:032x}", preview={},
                                             file_count=0, class_count=0, error_count=0,
                                             warning_count=0, total_size_bytes=0))
            result = {"prepared": True}
        elif action == "admit":
            print("READY", flush=True)
            if sys.stdin.readline().strip() != "GO":
                raise RuntimeError("Admission barrier not released")
            try:
                result = {"accepted": queue.admit(owner, f"{owner * 10 + int(key):032x}",
                                                 "preview", "operation", {"root": ""})}
            except Exception as error:
                from fastapi import HTTPException
                if not isinstance(error, HTTPException) or error.status_code not in (409, 429):
                    raise
                result = {"rejected": error.status_code}
        elif action == "inspect":
            with sessions() as db:
                result = {"jobs": [queue.get(row.owner_id, row.id)
                                    for row in db.scalars(select(ImportJob).order_by(ImportJob.id))],
                          "counts": [queue.active_counts(user) for user in (1, 2, 3)]}
        elif action == "cancel":
            result = queue.cancel(owner, key)
        else:
            raise ValueError("Unknown private probe phase")
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
    # System temp is intentional: no workspace SQLite, no existing data adopted.
    with tempfile.TemporaryDirectory(prefix="fama-import-job-proof-", dir="/tmp/opencode") as directory:
        root = Path(directory).resolve()
        root.chmod(0o700)
        environment = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1",
                       "DATABASE_URL": "sqlite://", "CUDA_VISIBLE_DEVICES": "", "HOME": str(root),
                       "TMPDIR": str(root), "XDG_CACHE_HOME": str(root), "PYTHONHASHSEED": "0"}

        def launch(action, owner=0, key="0"):
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--child", str(root), action, str(owner), key],
                                       cwd=BACKEND, env=environment, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            children.append(process)
            return process

        def finish(process):
            output, errors = process.communicate(timeout=20)
            if process.returncode != 0:
                # Diagnostics contain no actual credentials; they still stay
                # local and are not written into a persisted proof artifact.
                raise AssertionError(f"Synthetic child failed: {errors}")
            return json.loads(output)

        try:
            assert finish(launch("prepare")) == {"prepared": True}
            # Nine independent processes wait on explicit pipe barriers. There
            # are no sleeps or timing-based race assumptions in this proof.
            contenders = [launch("admit", user, str(number))
                          for user in (1, 2, 3) for number in range(3)]
            for process in contenders:
                assert process.stdout.readline().strip() == "READY"
            for process in contenders:
                process.stdin.write("GO\n")
                process.stdin.flush()
            results = [finish(process) for process in contenders]
            accepted = [result["accepted"] for result in results if "accepted" in result]
            assert len(accepted) == 2
            assert len({int(job["import_id"], 16) // 10 for job in accepted}) == 2
            persisted = finish(launch("inspect"))
            assert len(persisted["jobs"]) == 2
            assert all(count["global"] == 2 and count["owner"] <= 1 for count in persisted["counts"])
            # All admitting processes exited. A fresh process sees the queued
            # operation with exactly its durable identity and requested params.
            ids = {job["id"] for job in accepted}
            assert {job["id"] for job in persisted["jobs"]} == ids
            job = accepted[0]
            owner = int(job["import_id"], 16) // 10
            assert finish(launch("cancel", owner, job["id"]))["status"] == "cancelled"
            after_release = finish(launch("inspect"))
            assert all(count["global"] == 1 for count in after_release["counts"])
            # Replay contenders targeting the same owner/import/key produce
            # exactly one identity, even when multiple processes admit it.
            next_import = str((int(job["import_id"], 16) % 10 + 1) % 3)
            contenders = [launch("admit", owner, next_import) for _ in range(3)]
            for process in contenders:
                assert process.stdout.readline().strip() == "READY"
            for process in contenders:
                process.stdin.write("GO\n")
                process.stdin.flush()
            replay = [finish(process) for process in contenders]
            assert all("accepted" in result for result in replay), replay
            assert len({result["accepted"]["id"] for result in replay}) == 1
            proof = {"simultaneous_processes": 9, "global_limit": 2, "owner_limit": 1,
                     "admission": "passed", "same_operation_race": "passed",
                     "persisted_after_process_exit": "passed", "release_after_restart": "passed",
                     "worker_execution_recovery": "not_tested", "postgresql": "not_tested"}
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
    assert not root.exists()
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected} == before
    print(json.dumps(dict(proof, private_cleanup=True, protected_inputs_unchanged=True)))


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--child":
        # No ambient database discovery. The coordinator owns this fresh root.
        child(Path(sys.argv[2]).resolve(strict=True), sys.argv[3], int(sys.argv[4]), sys.argv[5])
    elif len(sys.argv) == 1:
        coordinator()
    else:
        raise SystemExit("No user-supplied probe paths or database URLs are accepted")
