"""Parse the opt-in manual stack without a daemon, credentials or host data."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ManualConfigurationTests(unittest.TestCase):
    def configuration(self):
        environment = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"],
                       "HOST_UID": "10001", "HOST_GID": "10001",
                       "FAMA_ZIP_MANUAL_HOME": "/tmp/synthetic-zip-manual"}
        result = subprocess.run(["docker", "compose", "--env-file", "/dev/null",
                                 "-p", "fama-zip-manual", "-f", "docker-compose.zip-manual.yml",
                                 "config", "--format", "json"], cwd=ROOT, env=environment,
                                text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_stack_has_no_worker_and_only_its_own_resources(self):
        config = self.configuration()
        services = config["services"]
        self.assertEqual(set(services), {"frontend", "backend", "db"})
        for service in services.values():
            self.assertNotIn("container_name", service)
            self.assertEqual(set(service["networks"]), {"zip-manual"})
        self.assertEqual(services["backend"]["image"], "fama-zip-manual-backend:local")
        self.assertEqual(services["frontend"]["image"], "fama-zip-manual-frontend:local")
        self.assertNotIn("deploy", services["backend"])
        self.assertNotIn("security_opt", services["backend"])
        self.assertFalse(services["backend"].get("ports"))
        self.assertFalse(services["db"].get("ports"))
        self.assertTrue(config["networks"]["zip-manual"]["internal"])
        self.assertFalse(services["frontend"].get("ports"))
        self.assertEqual(services["db"]["environment"]["POSTGRES_DB"], "fama_zip_manual")
        self.assertEqual(set(config["volumes"]), {"manual_pgdata"})

    def test_api_and_host_share_canonical_paths_without_real_mounts(self):
        services = self.configuration()["services"]
        backend = services["backend"]
        self.assertEqual(backend["environment"]["FAMA_IMPORT_ROOT"],
                         "/tmp/synthetic-zip-manual/imports")
        binds = [volume for volume in backend["volumes"] if volume["type"] == "bind"]
        self.assertEqual(len(binds), 1)
        self.assertEqual(binds[0]["source"], "/tmp/synthetic-zip-manual")
        self.assertEqual(binds[0]["target"], binds[0]["source"])
        self.assertEqual(backend["environment"]["FAMA_ENV"], "development")
        self.assertEqual(backend["environment"]["FAMA_IMPORT_DEV_FRONTEND_IP"],
                         services["frontend"]["networks"]["zip-manual"]["ipv4_address"])
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", backend["environment"])

    def test_backend_build_uses_a_source_only_context_policy(self):
        config = self.configuration()
        self.assertEqual(config["services"]["backend"]["build"]["dockerfile"], "Dockerfile.zip-manual")
        policy = (ROOT / "backend/Dockerfile.zip-manual.dockerignore").read_text().splitlines()
        self.assertEqual(policy[0], "**")
        self.assertIn("!requirements.txt", policy)
        self.assertIn("!app/**/*.py", policy)
        self.assertNotIn("!*.json", policy)
        self.assertNotIn("!data/", policy)
        self.assertNotIn("!checkpoints/", policy)


if __name__ == "__main__":
    unittest.main()
