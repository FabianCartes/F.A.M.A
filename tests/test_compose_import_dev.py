"""Validate the real Compose merge without accessing a Docker daemon."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def configuration(dev=False):
    command = ["docker", "compose", "--env-file", "/dev/null", "-f", "docker-compose.yml"]
    if dev:
        command += ["-f", "docker-compose.dev.yml"]
    environment = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"],
                   "HOST_UID": "10001", "HOST_GID": "10001",
                   "FAMA_DEV_IMPORT_ROOT": str(ROOT / "backend/data-dev/dataset-imports")}
    result = subprocess.run(command + ["config", "--format", "json"], cwd=ROOT,
                            env=environment, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class LocalComposeTests(unittest.TestCase):
    def test_dev_merge_replaces_ports_and_networks(self):
        config = configuration(dev=True)
        services = config["services"]
        for name in ("backend", "db"):
            self.assertFalse(services[name].get("ports"))
        ports = services["frontend"]["ports"]
        self.assertEqual(len(ports), 1)
        self.assertEqual((ports[0]["host_ip"], str(ports[0]["published"]), ports[0]["target"]),
                         ("127.0.0.1", "3000", 3000))
        for service in services.values():
            self.assertEqual(set(service["networks"]), {"fama-dev"})
        backend = services["backend"]
        self.assertEqual(backend["environment"]["FAMA_ENV"], "development")
        self.assertEqual(backend["environment"]["FAMA_IMPORT_DEV_MODE"], "1")
        root = str(ROOT / "backend/data-dev/dataset-imports")
        self.assertEqual(backend["environment"]["FAMA_IMPORT_ROOT"], root)
        self.assertIn(root, [volume["target"] for volume in backend["volumes"]
                            if volume.get("source") == root])
        peer = services["frontend"]["networks"]["fama-dev"]["ipv4_address"]
        self.assertEqual(backend["environment"]["FAMA_IMPORT_DEV_FRONTEND_IP"], peer)
        self.assertIn("--no-proxy-headers", backend["command"])
        self.assertEqual(services["frontend"]["environment"]["API_URL"], "http://backend:8000")
        self.assertEqual(services["frontend"]["environment"]["NEXT_PUBLIC_API_URL"], "")

    def test_normal_stays_authenticated_and_keeps_its_ports(self):
        services = configuration()["services"]
        self.assertNotIn("FAMA_IMPORT_DEV_MODE", services["backend"]["environment"])
        self.assertNotIn("FAMA_ENV", services["backend"]["environment"])
        for service, port in (("frontend", 3000), ("backend", 8000), ("db", 5432)):
            self.assertEqual(services[service]["ports"][0]["target"], port)
            self.assertEqual(set(services[service]["networks"]), {"fama-network"})


if __name__ == "__main__":
    unittest.main()
