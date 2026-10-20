"""Public host CLI, fake Docker and fake foreground worker; no daemon or DB."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class DevelopmentImports(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="dev-imports-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "project with spaces"
        scripts = self.root / "backend/scripts"
        scripts.mkdir(parents=True)
        self.cli = scripts / "dev_imports.py"
        shutil.copyfile(REPO / "backend/scripts/dev_imports.py", self.cli)
        self.imports = self.root / "backend/data-dev/dataset-imports"
        self.imports.mkdir(parents=True, mode=0o700)
        self.output = Path(self.scratch.name) / "worker.json"
        (scripts / "run_dataset_import_worker.py").write_text(
            "import json, os\nfrom pathlib import Path\n"
            "def main(args):\n"
            " Path(os.environ['TEST_WORKER']).write_text(json.dumps(args))\n"
            " return 0\n")
        bindir = Path(self.scratch.name) / "bin"
        bindir.mkdir()
        docker = bindir / "docker"
        docker.write_text(f"#!{sys.executable}\n" +
            "import json, os, sys\nfrom pathlib import Path\n"
            "args=sys.argv[1:]\n"
            "with open(os.environ['TEST_DOCKER'], 'a') as f: f.write(json.dumps(args)+'\\n')\n"
            "if args[:2]==['context','inspect']:\n"
            " print('tcp://remote.invalid:2375' if os.getenv('SCENARIO')=='remote' else 'unix:///test.sock')\n"
            "elif 'exec' in args:\n"
            " if os.getenv('SCENARIO')=='unprepared': sys.exit(1)\n"
            " root=Path.cwd()/'backend/data-dev/dataset-imports'\n"
            " if os.getenv('SCENARIO')=='wrong-root': root=Path('/app/data/dataset-imports')\n"
            " print(json.dumps({'database_url':'postgresql+psycopg2://test:synthetic@172.30.253.30:5432/fama_db', 'import_root':str(root), 'limits_environment':{}}))\n"
            "else: sys.exit(99)\n")
        docker.chmod(0o700)
        self.log = Path(self.scratch.name) / "docker.jsonl"
        self.env = dict(os.environ, PATH=str(bindir), TEST_WORKER=str(self.output),
                        TEST_DOCKER=str(self.log), PYTHONDONTWRITEBYTECODE="1")
        for name in ("DOCKER_HOST", "DOCKER_CONTEXT"):
            self.env.pop(name, None)

    def run_cli(self, action, scenario="ready"):
        return subprocess.run([sys.executable, "-B", str(self.cli), action],
            cwd=self.scratch.name, env=dict(self.env, SCENARIO=scenario),
            capture_output=True, text=True, timeout=10)

    def test_check_and_worker_are_explicit_and_foreground_local_only(self):
        checked = self.run_cli("check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertFalse(self.output.exists())
        started = self.run_cli("worker")
        self.assertEqual(started.returncode, 0, started.stderr)
        args = json.loads(self.output.read_text())
        self.assertIn("--local-only", args)
        self.assertIn("--watch", args)
        self.assertEqual(args[args.index("--import-root") + 1], str(self.imports))
        self.assertEqual(args[args.index("--staging-root") + 1],
                         str(self.root / "backend/data-dev/dataset-import-attempts"))
        log = self.log.read_text()
        self.assertNotIn('"up"', log)
        self.assertNotIn('"build"', log)
        self.assertNotIn("--apply", log)
        self.assertNotIn("synthetic", checked.stdout + checked.stderr + started.stdout + started.stderr)

    def test_rejects_invalid_targets_or_unprepared_store_before_worker(self):
        for scenario in ("remote", "unprepared", "wrong-root"):
            with self.subTest(scenario=scenario):
                result = self.run_cli("worker", scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())
                self.assertNotIn("synthetic", result.stderr)

    def test_worker_lock_prevents_second_worker(self):
        with (self.imports / "dev-worker.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_cli("worker")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_help_and_unknown_actions_do_not_access_docker(self):
        self.assertEqual(self.run_cli("--help").returncode, 0)
        self.assertEqual(self.run_cli("migrate").returncode, 2)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
