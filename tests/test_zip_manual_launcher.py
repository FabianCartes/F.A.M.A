"""Exercise the operator interface with a fake Docker boundary, never services."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_schema_check_reuses_active_backend_and_retains_cold_check(self):
        module = self.load()
        for running in ("backend\n", ""):
            with self.subTest(running=bool(running)):
                calls = []
                def fake(arguments, environment, *, capture=False):
                    calls.append(arguments)
                    return SimpleNamespace(stdout=running)
                with patch.object(module, "_compose", side_effect=fake):
                    module._check({})
                self.assertEqual(calls[0], ["ps", "--status", "running", "--services", "backend"])
                self.assertEqual(calls[1][-1], "--check")
                self.assertEqual(calls[1][:3], ["exec", "-T", "backend"] if running
                                 else ["run", "--rm", "--no-deps"])
                self.assertNotIn("--initialize", calls[1])

    def test_loopback_relay_verifies_real_http_and_closes_listener(self):
        import http.server
        import threading
        import urllib.request
        module = self.load()
        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"synthetic manual UI")
            def log_message(self, *args):
                pass
        upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        try:
            with module._ui_relay(upstream.server_address, port=0) as relay:
                port = relay.server_address[1]
                module._verify_ui(port)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://127.0.0.1:{port}/", timeout=2) as response:
                    self.assertEqual(response.read(), b"synthetic manual UI")
                self.assertEqual(relay.server_address[0], "127.0.0.1")
            with self.assertRaises(OSError):
                opener.open(f"http://127.0.0.1:{port}/", timeout=1)
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join()

    def test_ui_http_failure_does_not_announce_success(self):
        module = self.load()
        with patch.object(module, "_ui_relay") as relay, \
                patch.object(module, "_verify_ui", side_effect=OSError("unreachable")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(OSError):
                module._serve_ui()
        self.assertNotIn("Manual ZIP UI:", output.getvalue())

    def load(self):
        spec = importlib.util.spec_from_file_location("zip_manual", ROOT / "backend/scripts/zip_manual.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_help_and_missing_acknowledgement_have_no_docker_or_directory_effects(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "REPO", Path(directory)):
            with patch.object(module.subprocess, "run", side_effect=AssertionError("No Docker")):
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as help_exit:
                    module.main(["--help"])
                self.assertEqual(help_exit.exception.code, 0)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as init_exit:
                    module.main(["init"])
                self.assertEqual(init_exit.exception.code, 2)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_remote_context_refused_before_daemon_or_root_creation(self):
        module = self.load()
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(stdout="ssh://remote.invalid\n")
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "REPO", Path(directory)):
            with patch.object(module.subprocess, "run", side_effect=fake), patch.dict(os.environ, {}, clear=True):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(module.main(["status"]), 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1:3], ["context", "inspect"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_initialization_refuses_running_api_before_any_up_or_migration(self):
        module = self.load()
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(stdout="unix:///var/run/docker.sock\n" if command[1] == "context" else "backend\n")
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "REPO", Path(directory)):
            with patch.object(module.subprocess, "run", side_effect=fake), patch.dict(os.environ, {}, clear=True):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(module.main(["init", "--writers-stopped"]), 1)
            self.assertFalse(any("up" in command or "run" in command for command in calls))

    def test_stop_preserves_data_and_targets_only_manual_project(self):
        module = self.load()
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(stdout="unix:///var/run/docker.sock\n" if command[1] == "context" else "")
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "REPO", Path(directory)):
            home = Path(directory) / ".fama-zip-manual"
            home.mkdir(mode=0o700)
            payload = home / "keep.txt"
            payload.write_text("synthetic")
            with patch.object(module.subprocess, "run", side_effect=fake), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(module.main(["stop"]), 0)
            self.assertEqual(payload.read_text(), "synthetic")
            command = calls[-1]
            self.assertEqual(command[-1], "stop")
            self.assertIn("fama-zip-manual", command)
            self.assertIn(str(Path(directory) / "docker-compose.zip-manual.yml"), command)
            self.assertNotIn("down", command)
            self.assertNotIn("-v", command)

    def test_init_creates_private_roots_and_uses_only_explicit_fresh_initializer(self):
        module = self.load()
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(stdout="unix:///var/run/docker.sock\n" if command[1] == "context" else "")
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "REPO", Path(directory)):
            with patch.object(module.subprocess, "run", side_effect=fake), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(module.main(["init", "--writers-stopped"]), 0)
            home = Path(directory) / ".fama-zip-manual"
            for root in (home, home / "imports", home / "attempts"):
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(calls[-1][-2:], ["--initialize", "--writers-stopped"])
            self.assertIn("scripts.prepare_zip_manual_database", calls[-1])
            self.assertEqual(len([command for command in calls if "run" in command]), 1)

    def test_stop_refuses_active_external_worker(self):
        module = self.load()
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(stdout="unix:///var/run/docker.sock\n")
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "REPO", Path(directory)):
            home = Path(directory) / ".fama-zip-manual"
            home.mkdir(mode=0o700)
            with module._worker_lock(home):
                with patch.object(module.subprocess, "run", side_effect=fake), patch.dict(os.environ, {}, clear=True):
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(module.main(["stop"]), 1)
            self.assertFalse(any("stop" in command for command in calls))

    def test_worker_executes_local_watch_on_host_with_only_manual_database(self):
        module = self.load()
        captured = {}
        class Executed(BaseException):
            pass
        def fake(command, **kwargs):
            return SimpleNamespace(stdout="unix:///var/run/docker.sock\n")
        def execute(path, arguments, environment):
            captured.update(path=path, arguments=arguments, environment=environment)
            raise Executed()
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "REPO", Path(directory)):
            module._roots(create=True)
            python = Path(directory) / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.touch()
            with patch.object(module.subprocess, "run", side_effect=fake), \
                    patch.object(module.os, "execvpe", side_effect=execute), \
                    patch.object(module.os, "chdir"), \
                    patch.dict(os.environ, {"DATABASE_URL": "postgresql://unused/normal",
                                           "GOOGLE_APPLICATION_CREDENTIALS": "unused-secret"}, clear=True):
                with self.assertRaises(Executed):
                    module.main(["worker"])
            self.assertEqual(captured["path"], str(python))
            self.assertEqual(captured["arguments"][-2:], ["--local-only", "--watch"])
            self.assertEqual(captured["environment"]["DATABASE_URL"], module.HOST_URL)
            self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", captured["environment"])


if __name__ == "__main__":
    unittest.main()
