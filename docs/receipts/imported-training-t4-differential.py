"""One-shot public HTTP differential in disposable guarded base/candidate copies."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path.cwd()
BASE = "fd0d25f1ee8e44ef59ce5ef9c0a4d56481aa828e"
OUT = ROOT / "docs/receipts/imported-training-t4-differential"


def main():
    protected = json.loads((ROOT / "docs/receipts/training-checks-inventory.json").read_text())["paths"]
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "backend"], text=True).splitlines()
    names = sorted(set([p for p in names if p.endswith(".py")] + protected + ["docs/receipts/training-checks-inventory.json"]))
    archive = subprocess.check_output(["git", "archive", BASE, "--", *names])
    changed = subprocess.check_output(["git", "diff", "--name-only", BASE, "--", "backend"], text=True).splitlines()
    changed += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "backend"], text=True).splitlines()
    probe = (ROOT / "docs/receipts/auth-reconciliation-differential-probe.txt").read_text()
    result = {"base": BASE, "scope": "20 legacy training HTTP operations plus Bearer authentication and import contracts", "normalization": "volatile timestamps, elapsed time, generated identities and JWT only; compare public outputs including relevant headers, stderr and exit", "runs": {}}
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1", DATABASE_URL="sqlite://", CUDA_VISIBLE_DEVICES="", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    with tempfile.TemporaryDirectory(prefix=".t4-differential-", dir=ROOT) as directory:
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
            (target / "backend/tests/test_auth_differential_probe.py").write_text(probe)
            command = [str(ROOT / ".venv/bin/python"), "tests/run_isolated_training_checks.py", "tests/test_auth_differential_probe.py"]
            run = subprocess.run(command, cwd=target / "backend", env=env, text=True, capture_output=True)
            Path(str(OUT) + f".{label}.stdout.log").write_text(run.stdout)
            Path(str(OUT) + f".{label}.stderr.log").write_text(run.stderr)
            markers = [json.loads(line.split("AUTH_DIFF_JSON ", 1)[1]) for line in run.stdout.splitlines() if "AUTH_DIFF_JSON " in line]
            result["runs"][label] = {"command": command, "exit": run.returncode, "public_outputs": markers, "stderr": run.stderr}
            if run.returncode != 0 or len(markers) != 4:
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
    raise SystemExit(main())
