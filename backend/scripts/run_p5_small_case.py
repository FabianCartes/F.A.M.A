"""Plan, or explicitly supervise one tiny P5 import on the retained P4 runtime.

Execution requires separate operator authorization. No initialization, activation,
firewall modification, cloud access or automatic repair is ever performed.
"""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import time
import wave
import zipfile


HOME = Path("/run/media/kevin/FAMA_P2/fama-p2/p4-transport-01")
PROFILE_SHA = "08b5c4a6bc1fb08d2dae36759a96a3557cafeb238c401c8ab5a72833acca95de"
SSD_UUID = "2cf2c3f8-b261-44a1-9cc3-d05b58e3f361"
PRIOR_IMPORTS = ("51023cc2a02d4d8caf753f2278ea02fd", "eb52527c47dd47b8add0ed5d67ed3e84")
PRIOR_DATASETS = ("d3f0136ce66842d4b21cdbf524cd05fc", "eef8ce14ee49470391f75042a42f51f9")
BACKEND = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Runtime:
    """Fixed OS adapter; no shell commands, ambient credentials or target discovery."""

    def __init__(self, home=HOME):
        self.home = Path(home)
        self.output = self.home / "logs" / "p5-small-01"
        self.children, self.logs, self.containers = [], [], {}
        self.started_at = time.monotonic()
        self.fixture = None
        self.output_owned = False
        self.env = {"PATH": os.defpath, "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHON_DOTENV_DISABLED": "1", "HOME": "/nonexistent"}

    def command(self, args, *, timeout=10, binary=False):
        return subprocess.run(args, cwd=BACKEND, env=self.env, check=True,
                              capture_output=True, text=not binary, timeout=timeout).stdout

    def docker(self, *args, binary=False):
        return self.command(["docker", "--host", "unix:///var/run/docker.sock",
                             "--config", "/nonexistent", *args], binary=binary)

    def inspect(self, target):
        return json.loads(self.docker("inspect", target))[0]

    def preflight(self):
        if os.getuid() == 0 or self.home != HOME:
            raise ValueError("Only the retained non-root campaign is supported")
        for path in (self.home, *self.home.parents):
            if path.is_symlink():
                raise ValueError("Symlinked campaign")
        for name in ("", "logs", "pgdata", "imports", "imports/objects", "attempts", "scratch", "exports"):
            directory = self.home / name
            info = directory.stat()
            if directory.is_symlink() or not stat.S_ISDIR(info.st_mode) or (info.st_uid != os.getuid() and name != "pgdata"):
                raise ValueError("Unexpected campaign directory")
            if name != "pgdata" and info.st_mode & 0o077:
                raise ValueError("Private owned campaign directories required")
        profile = self.home / "storage-profile.json"
        if profile.is_symlink() or digest(profile) != PROFILE_SHA or self.output.exists() or self.output.is_symlink():
            raise ValueError("Changed profile or existing case output")
        mount = self.command(["findmnt", "-rn", "-T", str(self.home), "-o", "UUID,FSTYPE"]).split()
        space = os.statvfs(self.home)
        self.initial_free = space.f_bavail * space.f_frsize
        if mount != [SSD_UUID, "ext4"] or space.f_bavail * space.f_frsize < 22 * 2**30 or space.f_favail < 10000:
            raise ValueError("Insufficient selected SSD headroom")
        for port in (3002, 8000):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1" if port == 3002 else "172.30.250.1", port))
        for role in ("db", "frontend"):
            item = self.inspect(f"fama-p4-host-01-{role}-1")
            if item["State"]["Status"] != "exited" or item["State"]["Pid"] != 0:
                raise ValueError("Refuse to adopt running campaign services")
            self.containers[role] = item["Id"]
            networks = item["NetworkSettings"]["Networks"].values()
            expected_ip = "172.30.250.30" if role == "db" else "172.30.250.10"
            if not any((n.get("IPAMConfig") or {}).get("IPv4Address") == expected_ip for n in networks):
                raise ValueError("Unexpected campaign network")
            if role == "db":
                mounts = [(m["Source"], m["Destination"]) for m in item["Mounts"]]
                if (str(self.home / "pgdata"), "/var/lib/postgresql/data") not in mounts:
                    raise ValueError("Unexpected database storage")
                # Read through the stopped container; never start postgres on an empty bind.
                raw = self.docker("cp", f"{item['Id']}:/var/lib/postgresql/data/PG_VERSION", "-", binary=True)
                with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                    entries = archive.getmembers()
                    if len(entries) != 1 or not entries[0].isfile() or entries[0].size != 3:
                        raise ValueError("Existing PostgreSQL 16 data is required")
                    if archive.extractfile(entries[0]).read(4) != b"16\n":
                        raise ValueError("Unexpected PostgreSQL version")
            elif item["HostConfig"]["PortBindings"].get("3000/tcp") != [{"HostIp": "127.0.0.1", "HostPort": "3002"}]:
                raise ValueError("Expected the retained loopback frontend on port 3002")

    def open_case(self):
        self.output.mkdir(mode=0o700)  # Exclusive; never overwrite historical evidence.
        self.output_owned = True
        for name in ("home", "tmp"):
            (self.output / name).mkdir(mode=0o700)
        self.env.update(HOME=str(self.output / "home"), TMPDIR=str(self.output / "tmp"),
                        FAMA_ENV="development", FAMA_IMPORT_DEV_MODE="1",
                        FAMA_IMPORT_DEV_FRONTEND_IP="172.30.250.10",
                        DATABASE_URL="postgresql+psycopg2://p4_development:p4_synthetic_local_only@172.30.250.30:5432/fama_p4_transport",
                        FAMA_IMPORT_ROOT=str(self.home / "imports"), FAMA_EXPORT_ROOT=str(self.home / "exports"),
                        FAMA_IMPORT_STORAGE_PROFILE=str(self.home / "storage-profile.json"),
                        FAMA_IMPORT_RECEIVED_BYTES="67108864", FAMA_IMPORT_EXPANDED_BYTES="268435456",
                        FAMA_IMPORT_CONCURRENT_IMPORTS="1", CUDA_VISIBLE_DEVICES="",
                        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
        members = []
        archive = self.output / "small.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as target:
            for label, frequency in (("class-a", 440), ("class-b", 880)):
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav:
                    wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    wav.writeframes(b"".join(struct.pack("<h", round(1000 * math.sin(2 * math.pi * frequency * i / 16000))) for i in range(16000)))
                data = buffer.getvalue()
                target.writestr(zipfile.ZipInfo(f"{label}/audio.wav", (2026, 1, 1, 0, 0, 0)), data)
                members.append({"class_name": label, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        if archive.stat().st_size != 64330:
            raise ValueError("Unexpected fixture dimensions")
        self.fixture = {"path": str(archive), "sha256": digest(archive),
                        "dataset": {"owner_id": -1, "revision": 1, "file_count": 2,
                                    "class_count": 2, "total_size_bytes": 64088, "members": members}}
        return self.fixture

    def start_db(self):
        self.docker("start", self.containers["db"])
        deadline = time.monotonic() + 30
        while True:
            try:
                self.docker("exec", self.containers["db"], "pg_isready", "-q", "-U", "p4_development", "-d", "fama_p4_transport")
                return
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Existing PostgreSQL did not become ready") from None
                time.sleep(1)

    def snapshot(self):
        return json.loads(self.command([sys.executable, "-B", "-c",
            "import json; from scripts.run_p5_small_case import campaign_snapshot; print(json.dumps(campaign_snapshot()))"]))

    def launch(self, name, args):
        stream = (self.output / f"{name}.log").open("xb")
        self.logs.append(stream)
        child = subprocess.Popen(args, cwd=BACKEND, env=self.env, stdin=subprocess.DEVNULL,
                                 stdout=stream, stderr=stream, start_new_session=True)
        self.children.append(child)

    def start_hosts(self):
        self.launch("api", [sys.executable, "-B", "-m", "uvicorn", "app.p4_host_api:create_app",
                            "--factory", "--host", "172.30.250.1", "--port", "8000", "--no-proxy-headers"])
        self.launch("worker", [sys.executable, "-B", "-m", "scripts.run_dataset_import_worker", *self.worker_args(), "--local-only", "--watch"])

    def worker_args(self):
        return ["--database-url", self.env["DATABASE_URL"], "--import-root", str(self.home / "imports"),
                "--staging-root", str(self.home / "attempts"), "--storage-profile", str(self.home / "storage-profile.json")]

    def start_frontend(self):
        self.docker("start", self.containers["frontend"])

    def alive(self):
        space = os.statvfs(self.home)
        free = space.f_bavail * space.f_frsize
        return (all(child.poll() is None for child in self.children)
                and free >= 20 * 2**30 and self.initial_free - free <= 2 * 2**30
                and space.f_favail >= 10000
                and digest(self.home / "storage-profile.json") == PROFILE_SHA
                and all(stream.tell() <= 16 * 2**20 for stream in self.logs))

    def pause(self):
        time.sleep(2)

    def stop_frontend(self):
        self.docker("stop", "--time", "5", self.containers["frontend"])
        if self.inspect(self.containers["frontend"])["State"]["Pid"] != 0:
            raise ValueError("Frontend did not stop")

    def stop_hosts(self):
        errors = []
        for child in self.children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except (Exception, KeyboardInterrupt):
                errors.append("terminate")
        for child in self.children:
            try:
                child.wait(timeout=5)
            except (Exception, KeyboardInterrupt):
                pass
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except (Exception, KeyboardInterrupt):
                errors.append("kill")
            try:
                child.wait(timeout=5)
            except (Exception, KeyboardInterrupt):
                errors.append("wait")
        for stream in self.logs:
            try:
                stream.close()
            except (Exception, KeyboardInterrupt):
                errors.append("close_log")
        if errors:
            raise RuntimeError("Owned process shutdown incomplete")

    def cleanup(self):
        result = json.loads(self.command([sys.executable, "-B", "-m", "scripts.run_dataset_import_worker",
                                         *self.worker_args(), "--cleanup-only"]))
        if result.get("failed") != 0 or result.get("completed") != 1:
            raise ValueError("Unexpected explicit cleanup result")

    def stop_db(self):
        self.docker("stop", "--time", "5", self.containers["db"])
        if self.inspect(self.containers["db"])["State"]["Pid"] != 0:
            raise ValueError("Database did not stop")

    def report(self, result):
        if self.output_owned and self.output.is_dir():
            with (self.output / "result.json").open("x") as stream:
                json.dump(result, stream, sort_keys=True)


def campaign_snapshot():
    """Read-only child probe; reuse schema, runtime-view and publication checks."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scripts.p4_host import DATABASE_URL
    from scripts.prepare_p4_runtime import check_p4
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_metadata import DatasetMember, DatasetSummary
    from app.services.dataset_storage_runtime import runtime_import_service

    if digest(HOME / "storage-profile.json") != PROFILE_SHA:
        raise ValueError("Changed retained profile")
    service = runtime_import_service(HOME / "imports", attempt_root=HOME / "attempts", profile=HOME / "storage-profile.json")
    engine = create_engine(DATABASE_URL, connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=5000"})
    try:
        inventory = check_p4(engine)
        with Session(engine) as db:
            imports = db.query(DatasetImport).limit(4).all()
            datasets = db.query(ImportedDataset).limit(4).all()
            if len(imports) > 3 or len(datasets) > 3:
                raise ValueError("Unexpected campaign work")
            result = {"inventory": inventory, "imports": {}, "datasets": {}}
            for row in imports:
                result["imports"][row.id] = {key: getattr(row, key) for key in
                    ("owner_id", "status", "archive_sha256", "dataset_id", "added_count", "sync_status")}
            for row in datasets:
                summary = db.get(DatasetSummary, row.id)
                members = db.query(DatasetMember).filter_by(dataset_id=row.id).order_by(DatasetMember.class_name).limit(3).all()
                if summary is None or len(members) > 2:
                    raise ValueError("Unexpected published members")
                for member in members:
                    path = service.download(db, row.owner_id, row.id, member.sha256)
                    if path.stat().st_size != member.size_bytes:
                        raise ValueError("Published size mismatch")
                result["datasets"][row.id] = {"owner_id": row.owner_id, "revision": row.revision,
                    "file_count": summary.file_count, "class_count": summary.class_count,
                    "total_size_bytes": summary.total_size_bytes,
                    "members": [{key: getattr(member, key) for key in ("class_name", "size_bytes", "sha256")} for member in members]}
                if row.id in PRIOR_DATASETS:
                    known = {PRIOR_DATASETS[0]: (6144044, "164100334314e57adbe5d3dac3fbf3008dba789bdb24a95fa0d70df7fc16b7fb"),
                             PRIOR_DATASETS[1]: (18432044, "e7ea9c8e87715fb0806daf8445159f22f730125ab49a7f44286c163874f98d28")}
                    expected_size, expected_hash = known[row.id]
                    if (row.owner_id != -1 or row.revision != 1 or summary.revision != 1
                            or len(members) != 1 or members[0].sha256 != expected_hash
                            or members[0].size_bytes != expected_size):
                        raise ValueError("Retained publication differs from P4 evidence")
                    result["datasets"][row.id].update(name=row.name, description=row.description,
                                                      summary_revision=summary.revision)
            return result
    finally:
        engine.dispose()


def verify_observation(before, current, fixture):
    for group, keys in (("imports", PRIOR_IMPORTS), ("datasets", PRIOR_DATASETS)):
        if any(current[group].get(key) != before[group][key] for key in keys):
            raise ValueError("Retained publication metadata changed")
    new = set(current["imports"]) - set(before["imports"])
    if len(new) > 1 or len(set(current["datasets"]) - set(before["datasets"])) > 1:
        raise ValueError("More than one new case")
    if not new:
        return False
    row = current["imports"][new.pop()]
    if row["status"] in ("failed", "cancelled", "needs_correction"):
        raise ValueError("Case rejected or failed")
    if row["status"] != "imported":
        return False
    if (row.get("archive_sha256") != fixture["sha256"] or row.get("added_count") != 2
            or row.get("owner_id") != -1 or row.get("dataset_id") in before["datasets"]
            or current["datasets"].get(row.get("dataset_id")) != fixture["dataset"]):
        raise ValueError("Wrong fixture or publication")
    return True


def supervise(runtime, *, cleanup):
    result = {"status": "failed", "phase": "preflight", "owned_resources_stopped": False, "stop_errors": []}
    db_owned = frontend_owned = hosts_owned = False
    success = False
    start = time.monotonic()
    try:
        runtime.preflight()
        result["phase"] = "prepare_case"
        fixture = runtime.open_case()
        result["phase"] = "start_database"
        db_owned = True  # Record start intent before dispatch, including ambiguous failure.
        runtime.start_db()
        result["phase"] = "check_baseline"
        before = runtime.snapshot()
        if (set(before["imports"]) != set(PRIOR_IMPORTS) or set(before["datasets"]) != set(PRIOR_DATASETS)
                or before["inventory"]["state"] != "active" or not before["inventory"]["drained"]
                or before["inventory"]["live_grants"] != 0):
            raise ValueError("Unexpected retained baseline")
        hosts_owned = True
        result["phase"] = "start_hosts"
        runtime.start_hosts()
        frontend_owned = True
        result["phase"] = "start_frontend"
        runtime.start_frontend()
        print(json.dumps({"status": "ready_for_one_ui_import", "fixture": fixture["path"],
                          "url": "http://127.0.0.1:3002", "zip_bytes": 64330}), flush=True)
        result["phase"] = "observe_import"
        while time.monotonic() - start < 780:  # Reserve two minutes for stop/check/cleanup.
            if not runtime.alive():
                raise ValueError("Owned child exited")
            if verify_observation(before, runtime.snapshot(), fixture):
                success = True
                break
            runtime.pause()
        if not success:
            raise TimeoutError("Case window exhausted")
    except (Exception, KeyboardInterrupt):
        pass  # Raw subprocess/DB errors can include credentials; retain private logs only.
    finally:
        for owned, action in ((frontend_owned, runtime.stop_frontend), (hosts_owned, runtime.stop_hosts)):
            if owned:
                try:
                    action()
                except (Exception, KeyboardInterrupt):
                    result["stop_errors"].append(action.__name__)
        if success and not result["stop_errors"]:
            try:
                stable = runtime.snapshot()
                if not verify_observation(before, stable, fixture):
                    raise ValueError("Publication not stable after stopping writers")
                result["status"] = "verified_cleanup_pending"
                if cleanup:
                    result["phase"] = "cleanup"
                    inventory = stable["inventory"]
                    if (inventory["counts"] != {"active_jobs": 0, "active_receipts": 0,
                            "recoverable_imports": 0, "recoverable_exports": 0, "cleanup_intents": 1}
                            or inventory["live_grants"] != 2):
                        raise ValueError("Cleanup would touch unexpected work")
                    runtime.cleanup()
                    after = runtime.snapshot()
                    if not verify_observation(before, after, fixture) or not after["inventory"]["drained"] or after["inventory"]["live_grants"] != 0:
                        raise ValueError("Cleanup did not drain safely")
                    result["status"] = "verified_and_cleaned"
            except (Exception, KeyboardInterrupt):
                result["status"] = "failed"
        if db_owned:
            try:
                runtime.stop_db()
            except (Exception, KeyboardInterrupt):
                result["stop_errors"].append("stop_db")
        result["owned_resources_stopped"] = not result["stop_errors"]
        if result["stop_errors"]:
            result["status"] = "failed"
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        try:
            runtime.report(result)
        except (Exception, KeyboardInterrupt):
            result["status"] = "failed"
        print(json.dumps(result), flush=True)
    return 0 if result["status"] == "verified_and_cleaned" else 3 if result["status"] == "verified_cleanup_pending" else 1


def main(argv=None, *, runtime=None):
    """CLI seam; an injected runtime supports isolated synthetic lifecycle tests."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--execute", action="store_true", help="Start the retained runtime only after separate case-specific authorization.")
    parser.add_argument("--firewall-confirmed", action="store_true", help="Operator attests the separately authorized narrow P4 rule is present; never adds it.")
    parser.add_argument("--cleanup", action="store_true", help="Explicitly clean eligible staging after verified success only; requires --execute.")
    args = parser.parse_args(argv)
    if args.execute and not args.firewall_confirmed:
        parser.error("--execute requires --firewall-confirmed and separate operational authorization")
    if not args.execute:
        if args.firewall_confirmed or args.cleanup:
            parser.error("--firewall-confirmed and --cleanup require --execute")
        print(json.dumps({"status": "plan_only", "execution_authorized": False,
                          "deadline_seconds": 900,
                          "fixture": {"zip_bytes": 64330, "wav_bytes_each": 32044,
                                      "members": ["class-a/audio.wav", "class-b/audio.wav"]}}))
        return 0
    previous = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        return supervise(runtime if runtime is not None else Runtime(), cleanup=args.cleanup)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
