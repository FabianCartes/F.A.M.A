"""Public CLI checks; never connect to Docker, PostgreSQL or the retained campaign."""
import contextlib
import importlib.util
import io
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_p5_small_case.py"


class PlanTests(unittest.TestCase):
    def test_default_plan_is_inert_and_describes_only_the_small_case(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "plan_only")
        self.assertFalse(plan["execution_authorized"])
        self.assertEqual(plan["fixture"]["zip_bytes"], 64330)
        self.assertEqual(plan["fixture"]["wav_bytes_each"], 32044)
        self.assertEqual(plan["deadline_seconds"], 900)
        self.assertEqual(result.stderr, "")

    def test_execute_needs_an_explicit_firewall_attestation_before_effects(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--execute"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--firewall-confirmed", result.stderr)
        self.assertEqual(result.stdout, "")


def load_runner():
    spec = importlib.util.spec_from_file_location("p5_runner", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LifecycleTests(unittest.TestCase):
    def run_case(self, *, failure=None, cleanup=True):
        module = load_runner()
        with tempfile.TemporaryDirectory(prefix="p5-cli-", dir="/tmp/opencode") as temp:
            runtime = SyntheticRuntime(module, Path(temp), failure)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = module.main(["--execute", "--firewall-confirmed"] +
                                   (["--cleanup"] if cleanup else []), runtime=runtime)
            return code, [json.loads(line) for line in output.getvalue().splitlines()], runtime

    def test_one_import_is_verified_before_explicit_cleanup_and_all_owned_work_stops(self):
        code, events, runtime = self.run_case()
        self.assertEqual(code, 0)
        self.assertEqual(events[-1]["status"], "verified_and_cleaned")
        self.assertTrue(events[-1]["owned_resources_stopped"])
        self.assertEqual(runtime.calls, ["preflight", "open", "start_db", "baseline",
                                        "start_hosts", "start_frontend", "observe",
                                        "stop_frontend", "stop_hosts", "observe",
                                        "cleanup", "observe", "stop_db", "report"])
        self.assertTrue(all(child.poll() is not None for child in runtime.children))

    def test_failures_never_clean_or_leave_owned_children_running(self):
        for failure in ("preflight", "start_db", "baseline", "start_hosts",
                        "start_frontend", "changed_prior", "extra_import", "wrong_fixture",
                        "child_exit", "timeout", "interrupt", "unrelated_cleanup"):
            with self.subTest(failure=failure):
                code, events, runtime = self.run_case(failure=failure)
                self.assertNotEqual(code, 0)
                self.assertNotIn("cleanup", runtime.calls)
                self.assertTrue(all(child.poll() is not None for child in runtime.children))
                self.assertNotEqual(events[-1]["status"], "verified_and_cleaned")
                self.assertNotIn("sensitive content", json.dumps(events))
                if "start_db" in runtime.calls:
                    self.assertIn("stop_db", runtime.calls)

    def test_cleanup_requires_explicit_option_and_stop_failures_are_not_success(self):
        code, events, runtime = self.run_case(cleanup=False)
        self.assertEqual(code, 3)
        self.assertNotIn("cleanup", runtime.calls)
        self.assertEqual(events[-1]["status"], "verified_cleanup_pending")
        for failure in ("stop_frontend", "stop_db", "cleanup"):
            with self.subTest(failure=failure):
                code, events, runtime = self.run_case(failure=failure)
                self.assertNotEqual(code, 0)
                self.assertIn("stop_db", runtime.calls)
                self.assertEqual(events[-1]["status"], "failed")


class SyntheticRuntime:
    """An adapter using temporary files and real disposable child processes only."""
    def __init__(self, module, home, failure):
        self.module, self.failure, self.calls = module, failure, []
        (home / "logs").mkdir(mode=0o700)
        self.real = module.Runtime(home)
        self.children = []
        self.state = {
            "inventory": {"state": "active", "drained": True, "live_grants": 0},
            "imports": {key: {"status": "imported"} for key in module.PRIOR_IMPORTS},
            "datasets": {key: {"retained": True} for key in module.PRIOR_DATASETS},
        }

    def step(self, name):
        self.calls.append(name)
        if self.failure == name:
            raise ValueError("synthetic failure; sensitive content must not be echoed")

    def preflight(self):
        self.step("preflight")

    def open_case(self):
        self.step("open")
        return self.real.open_case()

    def start_db(self):
        self.step("start_db")

    def snapshot(self):
        self.step("baseline" if "start_hosts" not in self.calls else "observe")
        state = json.loads(json.dumps(self.state))
        if "start_hosts" in self.calls:
            if self.failure == "interrupt":
                raise KeyboardInterrupt
            if self.failure == "timeout":
                raise TimeoutError
            state["imports"]["new"] = {
                "status": "imported", "archive_sha256": self.real.fixture["sha256"],
                "added_count": 2, "dataset_id": "new-dataset", "owner_id": -1,
            }
            state["datasets"]["new-dataset"] = self.real.fixture["dataset"]
            state["inventory"]["counts"] = {"active_jobs": 0, "active_receipts": 0,
                "recoverable_imports": 0, "recoverable_exports": 0,
                "cleanup_intents": 0 if "cleanup" in self.calls else 1}
            state["inventory"]["drained"] = "cleanup" in self.calls
            state["inventory"]["live_grants"] = 0 if "cleanup" in self.calls else 2
            if self.failure == "changed_prior":
                state["datasets"][self.module.PRIOR_DATASETS[0]] = {"changed": True}
            if self.failure == "extra_import":
                state["imports"]["unexpected"] = {"status": "receiving"}
            if self.failure == "wrong_fixture":
                state["imports"]["new"]["archive_sha256"] = "wrong"
            if self.failure == "unrelated_cleanup":
                state["inventory"]["counts"]["cleanup_intents"] = 2
        return state

    def start_hosts(self):
        self.step("start_hosts")
        self.real.launch("synthetic", [sys.executable, "-I", "-B", "-c",
                                      "import time; time.sleep(60)"])
        self.children.extend(self.real.children)

    def start_frontend(self):
        self.step("start_frontend")

    def alive(self):
        return self.failure != "child_exit" and all(child.poll() is None for child in self.children)

    def pause(self):
        raise TimeoutError("synthetic case did not terminate")

    def stop_frontend(self):
        self.step("stop_frontend")

    def stop_hosts(self):
        self.calls.append("stop_hosts")
        self.real.stop_hosts()

    def cleanup(self):
        self.step("cleanup")

    def stop_db(self):
        self.step("stop_db")

    def report(self, result):
        self.step("report")
        self.real.report(result)


class FilesystemTests(unittest.TestCase):
    def test_refusing_an_existing_case_preserves_all_historical_evidence(self):
        module = load_runner()
        with tempfile.TemporaryDirectory(prefix="p5-existing-", dir="/tmp/opencode") as temp:
            home = Path(temp)
            (home / "logs").mkdir(mode=0o700)
            runtime = module.Runtime(home)
            runtime.output.mkdir(mode=0o700)
            (runtime.output / "prior.log").write_bytes(b"previous interrupted case\n")
            before = {str(p.relative_to(home)): p.read_bytes()
                      for p in home.rglob("*") if p.is_file()}
            with contextlib.redirect_stdout(io.StringIO()):
                code = module.main(["--execute", "--firewall-confirmed"], runtime=runtime)
            self.assertEqual(code, 1)
            self.assertEqual({str(p.relative_to(home)): p.read_bytes()
                              for p in home.rglob("*") if p.is_file()}, before)

    def test_exclusive_case_output_preserves_fixture_and_existing_evidence(self):
        module = load_runner()
        with tempfile.TemporaryDirectory(prefix="p5-files-", dir="/tmp/opencode") as temp:
            home = Path(temp)
            (home / "logs").mkdir(mode=0o700)
            runtime = module.Runtime(home)
            fixture = runtime.open_case()
            archive = Path(fixture["path"])
            before = archive.read_bytes()
            self.assertEqual(len(before), 64330)
            self.assertEqual(len({m["sha256"] for m in fixture["dataset"]["members"]}), 2)
            with self.assertRaises(FileExistsError):
                runtime.open_case()
            self.assertEqual(archive.read_bytes(), before)

    def test_changed_target_is_rejected_without_subprocess_or_filesystem_writes(self):
        module = load_runner()
        with tempfile.TemporaryDirectory(prefix="p5-refuse-", dir="/tmp/opencode") as temp:
            runtime = module.Runtime(temp)
            output = io.StringIO()
            with mock.patch.object(runtime, "command", side_effect=AssertionError("no commands")), contextlib.redirect_stdout(output):
                code = module.main(["--execute", "--firewall-confirmed"], runtime=runtime)
            self.assertEqual(code, 1)
            self.assertEqual(list(Path(temp).iterdir()), [])
            self.assertEqual(json.loads(output.getvalue())["phase"], "preflight")

    @unittest.skipIf(os.getuid() == 0, "Real retained runner requires a non-root caller")
    def test_preflight_qualifies_stopped_data_without_starting_services(self):
        for defect in (None, "empty_database", "running", "profile", "mount", "symlink"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory(prefix="p5-preflight-", dir="/tmp/opencode") as temp:
                module = load_runner()
                home = Path(temp)
                for name in ("logs", "pgdata", "imports", "imports/objects", "attempts", "scratch", "exports"):
                    (home / name).mkdir(mode=0o700)
                (home / "storage-profile.json").write_bytes(b"synthetic-profile\n")
                module.HOME = home
                module.PROFILE_SHA = hashlib.sha256(b"synthetic-profile\n").hexdigest()
                runtime = module.Runtime(home)
                calls = []

                def command(args, **kwargs):
                    calls.append(args)
                    if args[0] == "findmnt":
                        return ("wrong" if defect == "mount" else module.SSD_UUID) + " ext4\n"
                    if "inspect" in args:
                        role = "db" if args[-1].endswith("db-1") else "frontend"
                        ip = "172.30.250.30" if role == "db" else "172.30.250.10"
                        return json.dumps([{"Id": role, "State": {"Status": "running" if defect == "running" else "exited", "Pid": 0},
                            "Mounts": [{"Source": str(home / "pgdata"), "Destination": "/var/lib/postgresql/data"}],
                            "NetworkSettings": {"Networks": {"test": {"IPAMConfig": {"IPv4Address": ip}}}},
                            "HostConfig": {"PortBindings": {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3002"}]}}}])
                    if "cp" in args:
                        stream = io.BytesIO()
                        with tarfile.open(fileobj=stream, mode="w") as archive:
                            info = tarfile.TarInfo("PG_VERSION")
                            data = b"" if defect == "empty_database" else b"16\n"
                            info.size = len(data)
                            archive.addfile(info, io.BytesIO(data))
                        return stream.getvalue()
                    raise AssertionError("A service or database command must not run")

                if defect == "profile":
                    (home / "storage-profile.json").write_bytes(b"changed")
                if defect == "symlink":
                    (home / "attempts").rmdir()
                    (home / "attempts").symlink_to(home / "scratch", target_is_directory=True)
                space = type("Space", (), {"f_bavail": 100 * 2**30, "f_frsize": 1, "f_favail": 100000})()
                with mock.patch.object(runtime, "command", side_effect=command), \
                     mock.patch.object(runtime, "open_case", side_effect=ValueError("stop after preflight")), \
                     mock.patch.object(module.os, "statvfs", return_value=space), \
                     mock.patch.object(module.socket, "socket") as sock, \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    code = module.main(["--execute", "--firewall-confirmed"], runtime=runtime)
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(output.getvalue())["phase"], "prepare_case" if defect is None else "preflight")
                self.assertFalse(runtime.output.exists())
                self.assertFalse(any("start" in args for args in calls))


class ShutdownRegressionTests(unittest.TestCase):
    def test_sigterm_during_shutdown_still_attempts_all_owned_stops(self):
        module = load_runner()
        with tempfile.TemporaryDirectory(prefix="p5-signal-", dir="/tmp/opencode") as temp:
            runtime = SyntheticRuntime(module, Path(temp), None)
            runtime.start_hosts = lambda: runtime.step("start_hosts")

            def interrupted_stop():
                runtime.calls.append("stop_frontend")
                os.kill(os.getpid(), module.signal.SIGTERM)

            runtime.stop_frontend = interrupted_stop
            interrupted = False
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    code = module.main(["--execute", "--firewall-confirmed"], runtime=runtime)
                except KeyboardInterrupt:
                    interrupted = True
            self.assertIn("stop_hosts", runtime.calls)
            self.assertIn("stop_db", runtime.calls)
            self.assertIn("report", runtime.calls)
            self.assertFalse(interrupted)
            self.assertEqual(code, 1)

    def test_post_kill_wait_timeout_does_not_skip_other_groups(self):
        module = load_runner()
        first, second = mock.Mock(pid=111), mock.Mock(pid=222)
        first.wait.side_effect = subprocess.TimeoutExpired("synthetic", 5)
        with tempfile.TemporaryDirectory(prefix="p5-wait-", dir="/tmp/opencode") as temp:
            runtime = module.Runtime(temp)
            runtime.children = [first, second]
            with mock.patch.object(module.os, "killpg") as kill:
                try:
                    runtime.stop_hosts()
                except (subprocess.TimeoutExpired, RuntimeError):
                    pass
            kill.assert_any_call(111, module.signal.SIGKILL)
            kill.assert_any_call(222, module.signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
