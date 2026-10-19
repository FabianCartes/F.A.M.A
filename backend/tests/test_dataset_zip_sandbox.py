"""Fail-closed process admission; actual OS policy has a separate process proof."""
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from tests.test_dataset_zip_validation import archive, wav_bytes


def test_unavailable_sandbox_never_falls_back_to_in_process_decoding(tmp_path, monkeypatch):
    from app.services.dataset_zip_sandbox import validate_zip
    from app.services.dataset_zip import ImportLimits
    import subprocess

    source = archive(tmp_path / "input.zip", [("birds/a.wav", wav_bytes())])
    original = source.read_bytes()

    def denied(*args, **kwargs):
        raise OSError("synthetic sandbox unavailable")

    monkeypatch.setattr(subprocess, "Popen", denied)
    result = validate_zip(source, tmp_path / "staged", root="", limits=ImportLimits())
    assert result["errors"][0]["code"] == "sandbox_unavailable"
    assert result["files"] == []
    assert source.read_bytes() == original
    assert not list((tmp_path / "staged").iterdir())


@pytest.mark.parametrize("fault", ["wrong_hash", "bad_size", "stored_escape", "bad_diagnostic"])
def test_successful_child_cannot_authorize_invalid_result(tmp_path, monkeypatch, fault):
    """Protocol regression only; real isolation is exercised by the OS procedure."""
    from app.services import dataset_zip_sandbox
    from app.services.dataset_zip import ImportLimits

    source = archive(tmp_path / "input.zip", [("birds/a.wav", wav_bytes())])
    original = source.read_bytes()
    staging = tmp_path / "staging"
    audio = wav_bytes()
    digest = hashlib.sha256(audio).hexdigest()

    def child(*args, **kwargs):
        stored_name = digest + ".wav"
        (staging / stored_name).write_bytes(b"x" * len(audio) if fault == "wrong_hash" else audio)
        file = {"original_path": "birds/a.wav", "class_name": "birds", "sha256": digest,
                "stored_name": stored_name, "size_bytes": len(audio),
                "duration_seconds": 0.01, "sample_rate": 8000}
        if fault == "bad_size":
            file["size_bytes"] = str(len(audio))
        elif fault == "stored_escape":
            file["stored_name"] = "../outside.wav"
        warnings = [{"path": "birds", "code": "unsafe\ncode"}] if fault == "bad_diagnostic" else []
        read_fd, write_fd = os.pipe()
        try:
            # Anonymous pipe IPC, not a filesystem write requiring a guard root.
            payload = json.dumps({"files": [file], "errors": [], "warnings": warnings}).encode()
            assert os.write(write_fd, payload) == len(payload)
        finally:
            os.close(write_fd)
        return SimpleNamespace(stdout=os.fdopen(read_fd, "rb"), returncode=0,
                               poll=lambda: 0, wait=lambda timeout=None: 0)

    monkeypatch.setattr(dataset_zip_sandbox.subprocess, "Popen", child)
    result = dataset_zip_sandbox.validate_zip(source, staging, root="", limits=ImportLimits(free_bytes=1))
    assert result["files"] == []
    assert result["errors"][0]["code"] == "sandbox_invalid_result"
    assert source.read_bytes() == original
    assert not (tmp_path / "outside.wav").exists()


@pytest.mark.parametrize("entry", ["birds/a.wav", "birds/session/a.wav", "birds/empty/"])
def test_layout_policy_reaches_child_and_preserves_actionable_diagnostics(tmp_path, monkeypatch, entry):
    from app.services import dataset_zip_sandbox, dataset_zip

    source = archive(tmp_path / "input.zip", [(entry, b"" if entry.endswith("/") else wav_bytes())])
    staging = tmp_path / "staging"

    def child(command, **kwargs):
        config = json.loads(command[-1])
        assert config["layout"] == "class_folders"
        assert kwargs["env"] == {} and kwargs["close_fds"] and kwargs["start_new_session"]
        result = dataset_zip.validate_zip(source, staging, root=config["root"],
            limits=dataset_zip.ImportLimits(**config["limits"]), layout=config["layout"])
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, json.dumps(result).encode())
        finally:
            os.close(write_fd)
        return SimpleNamespace(stdout=os.fdopen(read_fd, "rb"), returncode=0,
            poll=lambda: 0, wait=lambda timeout=None: 0)

    monkeypatch.setattr(dataset_zip_sandbox.subprocess, "Popen", child)
    result = dataset_zip_sandbox.validate_zip(source, staging, root="",
        limits=dataset_zip.ImportLimits(free_bytes=1), layout="class_folders")
    if entry == "birds/a.wav":
        assert result["errors"] == [] and result["classes"] == ["birds"]
    else:
        assert result["errors"] == [{"path": entry, "code": "class_folders_required",
            "action": "Organiza el ZIP como clase/audio.wav, sin carpeta contenedora ni subcarpetas."}]
        assert result["files"] == []
