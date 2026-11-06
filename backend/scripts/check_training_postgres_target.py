"""Read-only collision preflight, not provisioning or an exclusive Docker lock."""
import argparse
import json
import os
import re
import subprocess
import sys


class PreflightRefused(Exception):
    pass


def check_target(project):
    """Query only the authorized local daemon; never inspect resource contents."""
    prefix = ["docker", "--host", "unix:///var/run/docker.sock"]
    # Do not inherit remote contexts, TLS settings, registry credentials or cloud
    # configuration. A missing config directory is intentional, not a fallback.
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   "HOME": "/nonexistent", "DOCKER_CONFIG": "/nonexistent"}

    def query(*arguments):
        try:
            result = subprocess.run(prefix + list(arguments), env=environment,
                                    check=True, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            raise PreflightRefused("docker_unavailable") from None
        return result.stdout.strip()

    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?",
                        query("version", "--format", "{{.Server.Version}}")):
        raise PreflightRefused("docker_unavailable")
    inventories = (
        ("container", "ls", "--all", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.ID}}"),
        ("container", "ls", "--all", "--filter", f"name=^/{project}-(db|bootstrap)(-[0-9]+)?$", "--format", "{{.ID}}"),
        ("volume", "ls", "--filter", f"name=^{project}_training_pgdata$", "--format", "{{.Name}}"),
        ("network", "ls", "--filter", f"name=^{project}_bootstrap$", "--format", "{{.ID}}"),
        ("image", "ls", "--filter", f"reference={project}-bootstrap:local", "--format", "{{.ID}}"),
    )
    for arguments in inventories:
        if query(*arguments):
            raise PreflightRefused("resource_collision")
    return {"project": project, "resources_created": False, "target_available": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="fama-training-dev",
                        help="fama-training-dev or a disposable fama-training-dev-test-<16 hex digits>; never creates resources.")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"fama-training-dev(?:-test-[a-f0-9]{16})?", args.project):
        parser.error("Unsupported training project name")
    try:
        result = check_target(args.project)
    except PreflightRefused as error:
        print(f"Training PostgreSQL preflight refused: {error}. No resources were created or changed.", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
