"""One-shot HTTP compatibility evidence; scratch tests never enter the test suite.

Run from the project root. Reads the pinned T3 base only to create isolated copies;
no committed test depends on Git history. Both copies use the original guard.
"""
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path.cwd()
BASE = "957f9ec41e20f702b42c0c0e2ef62423bfb695b9"
OUT = ROOT / "docs/receipts/imported-training-t3-differential"
PROBE = '''
import json, re
import pytest
from tests.test_api_training import client
from tests.test_training_flow import training_env, register, partitions

@pytest.mark.parametrize("name", ["AvesChilenas", "engine_diagnostics"])
def test_http_legacy(name, client, training_env):
    register(training_env[1], name)
    partitions(training_env[2], name)
    responses = []
    def query(method, path, **kwargs):
        r = getattr(client, method)("/api/training/" + path, **kwargs)
        responses.append([method, path, r.status_code, r.json()])
    headers = {"Authorization": "Bearer invalid"}
    for path in ("datasets", "history", "progress"):
        query("get", path + "?include_imported=false&snapshot_id=" + "a" * 32, headers=headers)
    query("post", "stop", headers=headers)
    query("post", "models/999/activate", headers=headers)
    query("post", "start", headers=headers, json={"dataset_name": name,
        "imported_dataset_id": None, "snapshot_id": None, "imported_prepared_version": None})
    query("get", "progress", headers=headers)
    query("get", "history?include_imported=false", headers=headers)
    query("post", "stop", headers=headers)
    query("get", "progress", headers=headers)
    def normalize(value):
        if isinstance(value, dict):
            return {k: ("<volatile>" if k in ("timestamp", "elapsed_seconds") else normalize(v))
                    for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        if isinstance(value, str):
            return re.sub(r"[0-9a-f]{64}|[0-9a-f]{32}", "<identity>", value)
        return value
    print("T3_DIFF_JSON " + json.dumps({"dataset": name, "responses": normalize(responses),
        "history": client.get("/api/training/history").json()}, sort_keys=True))
'''


def main():
    protected = json.loads((ROOT / "docs/receipts/training-checks-inventory.json").read_text())["paths"]
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "backend"], text=True).splitlines()
    names = sorted(set([n for n in names if n.endswith(".py")] + protected + ["docs/receipts/training-checks-inventory.json"]))
    archive = subprocess.check_output(["git", "archive", BASE, "--", *names])
    changed = subprocess.check_output(["git", "diff", "--name-only", BASE, "--", "backend"], text=True).splitlines()
    changed += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "backend"], text=True).splitlines()
    result = {"base": BASE, "scope": "10 HTTP operations for each of 2 legacy datasets; new optional fields/nulls and invalid bearer; activation missing ID only", "normalization": "volatile job/version identities, log timestamps and elapsed_seconds; no response/status/message differences otherwise allowed", "runs": {}}
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1", DATABASE_URL="sqlite://", CUDA_VISIBLE_DEVICES="", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    with tempfile.TemporaryDirectory(prefix=".t3-differential-", dir=ROOT) as directory:
        scratch = Path(directory)
        for label in ("base", "candidate"):
            target = scratch / label
            target.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as source:
                source.extractall(target, filter="data")
            (target / ".git").mkdir()
            if label == "candidate":
                for name in changed:
                    src, dst = ROOT / name, target / name
                    if src.is_file():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(src.read_bytes())
                    elif dst.exists():
                        dst.unlink()
            (target / "backend/tests/test_t3_differential_probe.py").write_text(PROBE)
            command = [str(ROOT / ".venv/bin/python"), "tests/run_isolated_training_checks.py", "tests/test_t3_differential_probe.py"]
            run = subprocess.run(command, cwd=target / "backend", env=env, text=True, capture_output=True)
            Path(str(OUT) + f".{label}.stdout.log").write_text(run.stdout)
            Path(str(OUT) + f".{label}.stderr.log").write_text(run.stderr)
            markers = [json.loads(line.split("T3_DIFF_JSON ", 1)[1]) for line in run.stdout.splitlines() if "T3_DIFF_JSON " in line]
            result["runs"][label] = {"command": command, "exit": run.returncode, "public_outputs": markers, "stderr": run.stderr}
            if run.returncode != 0 or len(markers) != 2:
                result["status"] = "failed_execution"
                break
        else:
            a, b = result["runs"]["base"], result["runs"]["candidate"]
            result["status"] = "passed" if (a["public_outputs"], a["stderr"], a["exit"]) == (b["public_outputs"], b["stderr"], b["exit"]) else "regression"
    result["scratch_removed"] = not scratch.exists()
    Path(str(OUT) + ".json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "scratch_removed": result["scratch_removed"], "exits": {k: v["exit"] for k, v in result["runs"].items()}}, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
