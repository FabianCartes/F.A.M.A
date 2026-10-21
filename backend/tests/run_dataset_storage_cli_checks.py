"""Independent file-SQLite CLI regressions; run separately from the memory guard.

The sole argument is an existing, empty private scratch directory outside the
worktree. Mount observations are synthetic and do not qualify the host.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

BACKEND = Path(__file__).resolve().parents[1]
REFUSAL = "Storage reconciliation refused; preserve work and inspect the maintenance procedure.\n"
CHILD = r'''
import os, runpy, sys
from pathlib import Path
root = Path(os.environ["T4_PRIVATE_ROOT"])
from tests.training_host_guard import install_guard
install_guard([root])
def private(event, args):
    if event == "socket.connect":
        raise RuntimeError("No network")
    if event == "sqlite3.connect":
        name = os.fsdecode(args[0])
        if name.startswith("file:"):
            from urllib.parse import unquote
            name = unquote(name[5:].split("?", 1)[0])
        if not Path(name).resolve().is_relative_to(root):
            raise RuntimeError("Only private SQLite")
    if event == "open" and not isinstance(args[0], int) and Path(os.fsdecode(args[0])).name in (".env", ".pgpass", "token"):
        raise RuntimeError("No credentials")
sys.addaudithook(private)
from app.services import dataset_storage
# Explicit synthetic topology fixture, not operational/private-root qualification.
dataset_storage._mount = lambda path: ("synthetic", 1, 1, 4096, "ext4")
module = sys.argv.pop(1)
sys.argv[0] = module.rsplit(".", 1)[1] + ".py"
runpy.run_module(module, run_name="__main__")
'''


def check_cli(tmp_path):
    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.routes import dataset_imports  # noqa: F401 - register application tables
    from app.models import dataset_import_revision, dataset_export, dataset_import_receipt  # noqa: F401
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_metadata import ImportSummary, DatasetSummary
    from scripts.migrate_dataset_import_jobs import migrate_jobs
    from scripts.migrate_dataset_storage import migrate_storage

    tmp_path = tmp_path.resolve(strict=True)
    if any(tmp_path.iterdir()) or tmp_path.is_relative_to(BACKEND.parent):
        raise ValueError("An empty external scratch directory is required")
    os.environ["HOME"] = os.environ["TMPDIR"] = str(tmp_path)
    roots = {"imports": tmp_path / "managed", "objects": tmp_path / "managed/objects",
             "attempts": tmp_path / "attempts", "exports": tmp_path / "exports"}
    roots["manifests"] = roots["scratch"] = roots["attempts"]
    for path in set(roots.values()) | {roots["imports"] / "staging"}:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(dict(roots={k: str(v) for k, v in roots.items()},
        pools={k: "private" for k in roots}, free_floors={"private": 5})))
    pristine = tmp_path / "pristine.sqlite"
    engine = create_engine(f"sqlite:///{pristine}")
    Base.metadata.create_all(engine)
    migrate_jobs(engine, writers_stopped=True)
    migrate_storage(engine, writers_stopped=True)
    with Session(engine) as db:
        db.add(ImportedDataset(id="d" * 32, owner_id=1, name="Retained", description="", revision=1))
        db.add(DatasetSummary(dataset_id="d" * 32, revision=1, file_count=1, class_count=1, total_size_bytes=8))
        db.commit()
    engine.dispose()
    (roots["objects"] / "retained.wav").write_bytes(b"retained")
    env = dict(os.environ, HOME=str(tmp_path), TMPDIR=str(tmp_path), T4_PRIVATE_ROOT=str(tmp_path),
        PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1", DATABASE_URL="sqlite://",
        CUDA_VISIBLE_DEVICES="", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")

    def command(module, args):
        result = subprocess.run([sys.executable, "-c", CHILD, module, *args], cwd=BACKEND,
            env=env, text=True, capture_output=True, timeout=12)
        return result.returncode, result.stdout, result.stderr

    def snapshot(db):
        return (hashlib.sha256(db.read_bytes()).hexdigest(),
            {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
             for root in set(roots.values()) for p in root.rglob("*") if p.is_file()})

    def fresh(name):
        db = tmp_path / (name + ".sqlite")
        shutil.copyfile(pristine, db)
        return db

    def args(db):
        return ["--database-url", f"sqlite:///{db}"]

    def apply(db, selected=profile):
        return command("scripts.reconcile_dataset_storage", args(db) +
            ["--apply", "--writers-stopped", "--profile", str(selected)])

    def mutate(db, sql, values=()):
        with sqlite3.connect(db) as conn:
            conn.execute(sql, values)

    def check(name, result, expected):
        assert result == expected, (name, result, expected)
        print("PASS", name, "exit", result[0], flush=True)

    empty_counts = dict(recoverable_imports=0, active_jobs=0, active_receipts=0,
                        recoverable_exports=0, cleanup_intents=0)
    db = fresh("inventory")
    before = snapshot(db)
    result = command("scripts.reconcile_dataset_storage", args(db))
    expected = dict(action="inventory", version=1, state="prepared", schema_verified=True,
                    pools=0, live_grants=0, counts=empty_counts, drained=True)
    check("inventory_exact_sanitized", result, (0, json.dumps(expected, sort_keys=True) + "\n", ""))
    assert snapshot(db) == before

    for defect in ("legacy", "missing_summary", "malformed_summary", "cleanup", "leaked_grant", "mismatched_pool"):
        db = fresh(defect)
        if defect in ("legacy", "missing_summary", "malformed_summary", "cleanup"):
            engine = create_engine(f"sqlite:///{db}")
            with Session(engine) as session:
                session.add(DatasetImport(id="a" * 32, owner_id=1, request_key="private-request",
                    request={}, status="receiving" if defect == "legacy" else "cancelled",
                    created_at=1, preview={}, added_count=0, sync_status="pending"))
                if defect != "missing_summary":
                    preview = [] if defect == "malformed_summary" else ({"_cleanup": {"state": "unknown"}} if defect == "cleanup" else {})
                    session.add(ImportSummary(import_id="a" * 32, preview=preview, file_count=0,
                        class_count=0, error_count=0, warning_count=0, total_size_bytes=0))
                session.commit()
            engine.dispose()
        else:
            mutate(db, "INSERT INTO dataset_storage_pool VALUES (?, ?, ?)", ("private", "0" * 64, 5))
            if defect == "leaked_grant":
                mutate(db, "INSERT INTO dataset_storage_grant VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("1" * 64, "private", "legacy", "attempt", 1, 1, "2" * 64, 10, "live"))
        before = snapshot(db)
        check(defect, apply(db), (1, "", REFUSAL))
        assert snapshot(db) == before, defect
        inspected = command("scripts.reconcile_dataset_storage", args(db))
        if defect == "legacy":
            assert json.loads(inspected[1])["counts"] == dict(empty_counts, recoverable_imports=1)
            assert "private-request" not in inspected[1] and "a" * 32 not in inspected[1]
        elif defect in ("missing_summary", "malformed_summary", "cleanup"):
            assert inspected == (1, "", REFUSAL)
        assert snapshot(db) == before, defect

    for name, body in (("invalid_json", "{"), ("oversize", " " * 65537), ("unknown_key", '{"unexpected": 1}')):
        selected = tmp_path / (name + ".json")
        selected.write_text(body)
        db = fresh(name)
        before = snapshot(db)
        check(name, apply(db, selected), (1, "", REFUSAL))
        assert snapshot(db) == before
    db = fresh("flags")
    before = snapshot(db)
    result = command("scripts.reconcile_dataset_storage", args(db) + ["--profile", str(profile)])
    assert result[0] == 2 and result[1] == "" and result[2].endswith(
        "error: --apply, --writers-stopped and --profile must be supplied together\n"), result
    assert snapshot(db) == before
    print("PASS flags exit 2", flush=True)

    import fcntl
    locked = roots["exports"] / ("b" * 32 + "-1-1")
    locked.mkdir(mode=0o700)
    for mode in (fcntl.LOCK_EX, fcntl.LOCK_SH):
        fd = os.open(locked, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, mode)
            db = fresh("busy" + str(mode))
            before = snapshot(db)
            check("busy_" + str(mode), apply(db), (1, "", REFUSAL))
            assert snapshot(db) == before
        finally:
            os.close(fd)

    db = fresh("activate")
    with sqlite3.connect(db) as conn:
        legacy_before = list(conn.iterdump())
    files_before = snapshot(db)[1]
    expected = dict(expected, action="activate", state="active", pools=1)
    first = apply(db)
    check("drained_activation", first, (0, json.dumps(expected, sort_keys=True) + "\n", ""))
    after = snapshot(db)
    assert after[1] == files_before
    check("matching_replay", apply(db), first)
    assert snapshot(db) == after
    with sqlite3.connect(db) as conn:
        legacy_after = list(conn.iterdump())
    clean = lambda rows: [row for row in rows if not row.startswith('INSERT INTO "dataset_storage_')]
    assert clean(legacy_before) == clean(legacy_after)
    print("PASS retained_rows_files_unchanged", flush=True)


if __name__ == "__main__":
    print("PRIVATE_SCRATCH", sys.argv[1], flush=True)
    check_cli(Path(sys.argv[1]))
