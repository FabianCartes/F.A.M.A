"""Fail-closed, bounded process execution for untrusted archive/audio processing."""
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import sysconfig
import threading
import time
import unicodedata

from app.services.dataset_zip import _parts, fingerprint


_CHILD = Path(__file__).with_name("dataset_zip_child.py")
_SLOTS = threading.BoundedSemaphore(4)
_MEMORY_BYTES = 768 * 1024**2


def _failure(code):
    return {"files": [], "errors": [{"path": "", "code": code,
            "action": "Corrige la ruta, estructura o contenido y vuelve a subir el ZIP."}],
            "warnings": [], "classes": [], "unique_count": 0, "duplicate_count": 0,
            "fingerprint": fingerprint([])}


def _command(source, staging, root, limits, maximum_output):
    dependencies = Path(sysconfig.get_path("purelib"))
    command = ["/usr/bin/prlimit", f"--as={_MEMORY_BYTES}",
               f"--cpu={max(1, math.ceil(limits.validation_seconds / 2))}", "--core=0", "--nofile=64",
               f"--fsize={max(limits.audio_bytes, maximum_output)}", "--", "/usr/bin/bwrap",
               "--unshare-all", "--unshare-user", "--disable-userns", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
               "--clearenv", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
               "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
               "--dir", "/code", "--dir", "/deps", "--chdir", "/staging",
               "--ro-bind", str(source), "/input.zip", "--bind", str(staging), "/staging",
               "--ro-bind", str(Path(__file__).with_name("dataset_zip.py")), "/code/dataset_zip.py",
               "--ro-bind", str(_CHILD), "/code/entry.py"]
    # Do not expose the project, home, environment files, cloud SDK or all of
    # site-packages to a compromised native decoder.
    for pattern in ("soundfile.py", "_soundfile.py", "typing_extensions.py", "cffi", "_cffi_backend*.so",
                    "numpy", "numpy.libs", "_soundfile_data"):
        for path in sorted(dependencies.glob(pattern)):
            command.extend(["--ro-bind", str(path), "/deps/" + path.name])
    for name, value in (("OPENBLAS_NUM_THREADS", "1"), ("OMP_NUM_THREADS", "1"),
                        ("MKL_NUM_THREADS", "1"), ("PYTHONDONTWRITEBYTECODE", "1")):
        command.extend(["--setenv", name, value])
    command.extend([str(Path(sys.executable).resolve()), "-I", "-S", "/code/entry.py",
                    json.dumps({"root": root, "limits": asdict(limits)}, separators=(",", ":"))])
    return command


def _read_result(process, deadline, maximum):
    output = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if not selector.select(remaining):
                raise TimeoutError
            block = os.read(process.stdout.fileno(), min(65536, maximum + 1 - len(output)))
            if not block:
                break
            output.extend(block)
            if len(output) > maximum:
                raise ValueError("sandbox_output_limit")
    process.wait(timeout=max(0.001, deadline - time.monotonic()))
    if process.returncode != 0:
        raise ValueError("sandbox_failed")
    return json.loads(output)


def _checked_result(result, staging, root, limits):
    """Treat child metadata as untrusted; never grant paths publication authority."""
    files, errors, warnings = result["files"], result["errors"], result["warnings"]
    if (not isinstance(files, list) or len(files) > limits.entries or not isinstance(errors, list)
            or len(errors) > limits.entries + 1 or not isinstance(warnings, list)
            or len(warnings) > limits.entries * 2):
        raise ValueError("sandbox_invalid_result")
    if not files and not errors:
        raise ValueError("sandbox_invalid_result")
    root_parts = _parts(root, limits) if root else []
    hashes, checked, total = {}, [], 0
    for file in files:
        digest = file["sha256"]
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("sandbox_invalid_result")
        parts = _parts(file["original_path"], limits)
        if parts[:len(root_parts)] != root_parts or len(parts) < len(root_parts) + 2:
            raise ValueError("sandbox_invalid_result")
        label = unicodedata.normalize("NFC", parts[len(root_parts)])
        if file["stored_name"] != digest + ".wav" or file["class_name"] != label:
            raise ValueError("sandbox_invalid_result")
        if (type(file["size_bytes"]) is not int or not 0 < file["size_bytes"] <= limits.audio_bytes
                or type(file["sample_rate"]) is not int or file["sample_rate"] <= 0
                or not isinstance(file["duration_seconds"], (int, float))
                or not 0 < file["duration_seconds"] <= limits.audio_seconds):
            raise ValueError("sandbox_invalid_result")
        total += file["size_bytes"]
        if total > limits.expanded_bytes:
            raise ValueError("sandbox_invalid_result")
        duplicate = digest in hashes
        if duplicate and hashes[digest] != label:
            raise ValueError("sandbox_invalid_result")
        if not duplicate:
            path = staging / (digest + ".wav")
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != file["size_bytes"]:
                    raise ValueError("sandbox_invalid_result")
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError("sandbox_invalid_result")
        hashes[digest] = label
        checked.append({key: file[key] for key in ("original_path", "class_name", "sha256", "stored_name",
                        "size_bytes", "duration_seconds", "sample_rate")})
        checked[-1]["duplicate"] = duplicate
    diagnostics = []
    for issues in (errors, warnings):
        selected = []
        for issue in issues:
            if (not isinstance(issue["path"], str) or len(issue["path"].encode()) > limits.path_bytes * 4
                    or not isinstance(issue["code"], str) or not re.fullmatch("[a-z_]{1,64}", issue["code"])):
                raise ValueError("sandbox_invalid_result")
            selected.append({"path": issue["path"], "code": issue["code"]})
            if issues is errors:
                selected[-1]["action"] = _failure("")["errors"][0]["action"]
        diagnostics.append(selected)
    names = {digest + ".wav" for digest in hashes}
    if errors:
        names.add("decoding.part")
    for path in staging.iterdir():
        if path.name not in names or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("sandbox_invalid_result")
    return {"files": checked, "errors": diagnostics[0], "warnings": diagnostics[1],
            "classes": sorted(set(hashes.values())), "unique_count": len(hashes),
            "duplicate_count": sum(f["duplicate"] for f in checked), "fingerprint": fingerprint(checked)}


def validate_zip(source, staging, *, root, limits):
    """Run all ZIP parsing/extraction and native decoding in a killable OS sandbox.

    Linux bubblewrap, prlimit, libseccomp and the Python/decoder runtime are
    prerequisites. Any failure refuses validation; there is no in-process fallback.
    """
    deadline = time.monotonic() + limits.validation_seconds
    source, staging = Path(source).absolute(), Path(staging).absolute()
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    if source.is_symlink() or staging.is_symlink() or any(staging.iterdir()):
        return _failure("sandbox_invalid_staging")
    if not _SLOTS.acquire(timeout=max(0, deadline - time.monotonic())):
        return _failure("validation_timeout")
    process = None
    try:
        maximum = min(16 * 1024**2, max(65536, limits.entries * (limits.path_bytes * 8 + 2048)))
        process = subprocess.Popen(_command(source, staging, root, limits, maximum),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env={}, close_fds=True, start_new_session=True)
        result = _read_result(process, deadline, maximum)
        return _checked_result(result, staging, root, limits)
    except (TimeoutError, subprocess.TimeoutExpired):
        return _failure("validation_timeout")
    except (OSError, RuntimeError):
        return _failure("sandbox_unavailable")
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        return _failure("sandbox_invalid_result")
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            process.stdout.close()
        _SLOTS.release()
