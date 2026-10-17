"""Synthetic OS-containment proof, separate from the unchanged guarded runner.

Run from backend with the validated interpreter. No database, services or network
connections are used. Faulty decoder entrypoints exist only in private scratch.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from unittest.mock import patch
from types import SimpleNamespace


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main():
    if Path.cwd().resolve() != BACKEND or not __debug__:
        raise SystemExit("Run non-optimized Python from backend")
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from app.services import dataset_zip_sandbox as sandbox
    from app.services.dataset_zip import ImportLimits
    from tests.test_dataset_zip_validation import archive, wav_bytes, zip64_archive

    protected = [BACKEND / "tests/run_isolated_training_checks.py", BACKEND / "tests/training_host_guard.py"]
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    with tempfile.TemporaryDirectory(prefix="t4-sandbox-", dir="/tmp/opencode") as directory:
        root = Path(directory)
        os.chmod(root, 0o700)
        source = archive(root / "input.zip", [("birds/a.wav", wav_bytes())])
        original = source.read_bytes()
        limits = ImportLimits(free_bytes=1, validation_seconds=5)
        launch = subprocess.Popen
        with (root / "startup.log").open("wb") as diagnostic:
            def capture_startup(*args, **kwargs):
                return launch(*args, **dict(kwargs, stderr=diagnostic))
            with patch.object(sandbox.subprocess, "Popen", capture_startup):
                result = sandbox.validate_zip(source, root / "valid", root="", limits=limits)
        if result["errors"]:
            print((root / "startup.log").read_bytes()[:8192].decode(errors="replace"), flush=True)
        assert result["errors"] == [], result
        assert (root / "valid" / result["files"][0]["stored_name"]).read_bytes() == wav_bytes()
        extended = zip64_archive(root / "zip64.zip", "offset")
        result = sandbox.validate_zip(extended, root / "zip64", root="", limits=limits)
        assert result["errors"] == [], result
        assert source.read_bytes() == original
        print("SANDBOX_VALID_PASS original_wav=unchanged zip64=accepted", flush=True)
        entrypoint = sandbox._CHILD.read_text()

        def probe(name, injection, *, seconds=5, expected_error=None):
            entry = root / (name + ".py")
            marker = "    configuration = json.loads(sys.argv[1])"
            assert entrypoint.count(marker) == 1
            entry.write_text(entrypoint.replace(marker, injection + "\n" + marker))
            start = time.monotonic()
            launched = []
            def track(*args, **kwargs):
                process = launch(*args, **kwargs)
                launched.append(process)
                return process
            with patch.object(sandbox, "_CHILD", entry), patch.object(sandbox.subprocess, "Popen", track):
                value = sandbox.validate_zip(source, root / name, root="",
                                             limits=replace(limits, validation_seconds=seconds))
            elapsed = time.monotonic() - start
            if expected_error:
                assert value["errors"][0]["code"] == expected_error, value
                assert value["files"] == []
            else:
                assert value["errors"] == [], value
            assert elapsed < seconds + 3, elapsed
            assert launched and all(process.returncode is not None for process in launched)
            assert all(not Path(f"/proc/{process.pid}").exists() for process in launched)
            assert source.read_bytes() == original
            print(f"SANDBOX_{name.upper()}_PASS elapsed={elapsed:.2f}", flush=True)

        probe("access", '''    import os, socket, resource, subprocess
    assert resource.getrlimit(resource.RLIMIT_AS) == (768 * 1024**2,) * 2
    assert resource.getrlimit(resource.RLIMIT_CPU) == (3, 3)
    assert os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") is None
    assert os.environ.get("FAMA_SYNTHETIC_SECRET") is None
    assert not Path("/home").exists()
    assert not Path("/etc").exists()
    assert "NoNewPrivs:\\t1" in Path("/proc/self/status").read_text()
    for operation in (lambda: socket.socket(), lambda: subprocess.Popen(["/usr/bin/true"]),
                      lambda: Path("/input.zip").write_bytes(b"changed"),
                      lambda: Path("/usr/fama-synthetic-probe").write_bytes(b"changed")):
        try:
            operation()
        except OSError:
            pass
        else:
            raise AssertionError("Sandbox access escaped")''')
        # The replaced object is the actual native decoder call seam. It never
        # invokes cooperative budget(), so only OS/supervisor controls can stop it.
        probe("wall", '''    import ctypes
    class HungDecoder:
        def __init__(self, *args):
            ctypes.CDLL(None).sleep(30)
    import dataset_zip
    dataset_zip.sf.SoundFile = HungDecoder''', seconds=2, expected_error="validation_timeout")
        probe("cpu", '''    class BusyDecoder:
        def __init__(self, *args):
            while True:
                pass
    import dataset_zip
    dataset_zip.sf.SoundFile = BusyDecoder''', expected_error="sandbox_invalid_result")
        probe("memory", '''    import ctypes
    library = ctypes.CDLL(None)
    library.malloc.argtypes = [ctypes.c_size_t]
    library.malloc.restype = ctypes.c_void_p
    assert not library.malloc(2 * 768 * 1024**2)''')
        probe("output", '''    while True:
        print("x" * 65536, flush=True)''', expected_error="sandbox_invalid_result")
        probe("fifo", '''    import os
    digest = "0" * 64
    os.mkfifo("/staging/" + digest + ".wav")
    print(json.dumps({"files": [{"sha256": digest, "original_path": "birds/a.wav",
          "stored_name": digest + ".wav", "class_name": "birds", "size_bytes": 204,
          "sample_rate": 8000, "duration_seconds": 0.01}], "errors": [], "warnings": []}), flush=True)
    raise SystemExit(0)''', expected_error="sandbox_invalid_result")
        # Exercise the production default through the public worker/HTTP seams.
        # The fixture explicitly opts out of its guarded-runner-only validator.
        import pytest
        from tests.test_dataset_import_api import imports, prepare, confirm
        with pytest.MonkeyPatch.context() as monkeypatch:
            fixture = imports.__wrapped__(root, monkeypatch, SimpleNamespace(param=True))
            client, service, _, _ = next(fixture)
            try:
                job = prepare(client, root, key="sandbox-real")
                assert job["status"] == "ready", job
                response = confirm(client, job)
                assert response.status_code == 200, response.text
                dataset = response.json()["dataset_id"]
                files = client.get(f"/api/ingestion/imports/datasets/{dataset}/files").json()["files"]
                assert len(files) == 1
                download = client.get(f"/api/ingestion/imports/datasets/{dataset}/files/{files[0]['sha256']}")
                assert download.content == wav_bytes()
                assert hashlib.sha256(download.content).hexdigest() == files[0]["sha256"]
                assert confirm(client, job).json()["added_count"] == 1
                assert len(client.get(f"/api/ingestion/imports/datasets/{dataset}/files").json()["files"]) == 1
                print("SANDBOX_WORKER_HTTP_PASS published_wav=unchanged replay=unchanged", flush=True)
            finally:
                try:
                    next(fixture)
                except StopIteration:
                    pass
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in hashes.items())
    print(json.dumps({"status": "passed", "original_guards_unchanged": True, "private_cleanup": True}))


if __name__ == "__main__":
    main()
