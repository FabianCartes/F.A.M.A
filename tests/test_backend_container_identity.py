"""Configuration contract only: no daemon, credentials, dotenv or backend imports."""
from pathlib import Path
import os
import subprocess
import unittest

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]


class ContainerIdentity(unittest.TestCase):
    def test_compose_requires_host_identity_and_private_home(self):
        text = (ROOT / "docker-compose.yml").read_text()
        backend = text.split("  backend:\n", 1)[1].split("  frontend:\n", 1)[0]
        self.assertRegex(backend, r'user: "\$\{HOST_UID:\?[^}]+\}:\$\{HOST_GID:\?[^}]+\}"')
        self.assertIn("- HOME=/home/fama", backend)
        self.assertRegex(backend, r'/home/fama:uid=\$\{HOST_UID:\?[^}]+\},gid=\$\{HOST_GID:\?[^}]+\},mode=0700')
        self.assertIn("./backend/data:/app/data", backend)
        self.assertIn("./backend/checkpoints:/app/checkpoints", backend)
        self.assertIn("capabilities: [gpu]", backend)
        self.assertIn("condition: service_healthy", backend)

    @unittest.skipIf(yaml is None, "PyYAML unavailable: structural checks only")
    def test_compose_resolves_private_home_for_different_host_uid(self):
        backend = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["backend"]
        # Only identity fields enter Compose: no real mounts, env_file or secrets.
        minimal = {"services": {"backend": {"image": "identity-test", **{
            key: backend[key] for key in ("user", "tmpfs") if key in backend
        }}}}
        source = yaml.safe_dump(minimal)
        base_env = {"PATH": os.defpath, "HOME": "/nonexistent"}
        command = ["docker", "compose", "--env-file", "/dev/null", "-f", "-", "config"]
        for identity in ({}, {"HOST_UID": "", "HOST_GID": ""},
                         {"HOST_UID": "12345"}, {"HOST_GID": "23456"}):
            result = subprocess.run(command, input=source, text=True, capture_output=True,
                                    env={**base_env, **identity})
            self.assertNotEqual(result.returncode, 0, result.stdout)
        result = subprocess.run(command, input=source, text=True, capture_output=True,
                                env={**base_env, "HOST_UID": "12345", "HOST_GID": "23456"})
        self.assertEqual(result.returncode, 0, result.stderr)
        resolved = yaml.safe_load(result.stdout)["services"]["backend"]
        self.assertEqual(resolved["user"], "12345:23456")
        self.assertIn("/home/fama:uid=12345,gid=23456,mode=0700", resolved["tmpfs"])

    def test_image_default_is_nonroot_with_owned_work_directories(self):
        text = (ROOT / "backend/Dockerfile").read_text()
        self.assertIn("USER 10001:10001", text)
        self.assertIn("HOME=/home/fama", text)
        self.assertIn("install -d -o 10001 -g 10001 -m 0700 /home/fama", text)
        self.assertIn("chown 10001:10001 /app/data /app/checkpoints", text)
        self.assertNotRegex(text, r'chown\s+-R|chmod\s+(?:-R\s+)?0?777')
        self.assertIn("    ffmpeg", text)


if __name__ == "__main__":
    unittest.main()
