"""Private evaluation copies through the public materialization boundary."""
import errno
import hashlib
from pathlib import Path
import stat
import tempfile

import pytest

from app.services.imported_evaluation import evaluation_recordings
from app.services.imported_training_source import ImportedSourceError


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir(mode=0o700)
    snapshot = root / "snapshot"
    snapshot.mkdir()
    content = b"synthetic recording bytes" * 128
    (snapshot / "member").write_bytes(content)
    row = dict(member_id="member", recording_id="recording", class_name="bird",
               group_id="group", size_bytes=len(content),
               sha256=hashlib.sha256(content).hexdigest())
    return dict(snapshot_root=root, identity=dict(snapshot_id="snapshot"),
                splits=dict(val=[row], test=[]))


def test_copies_use_private_storage_when_global_temp_is_full(source, monkeypatch):
    original = tempfile.TemporaryDirectory

    def restricted_temp(*args, **kwargs):
        if kwargs.get("dir") is None:
            raise OSError(errno.ENOSPC, "restricted global temporary volume")
        return original(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", restricted_temp)
    root = source["snapshot_root"]
    before = set(root.iterdir())
    with evaluation_recordings(source) as recordings:
        path = recordings["val"][0].path
        assert path.read_bytes() == (root / "snapshot/member").read_bytes()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["splits"]["val"][0]["sha256"]
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert path.resolve().is_relative_to(root)
        assert recordings["test"] == ()
    assert not path.exists()
    assert set(root.iterdir()) == before


@pytest.mark.parametrize("failure", ["consumer", "hash", "size", "symlink"])
def test_failure_cleans_private_copies_and_preserves_source(source, failure):
    root = source["snapshot_root"]
    member = root / "snapshot/member"
    content = member.read_bytes()
    if failure == "hash":
        source["splits"]["val"][0]["sha256"] = "0" * 64
    elif failure == "size":
        source["splits"]["val"][0]["size_bytes"] -= 1
    elif failure == "symlink":
        source["splits"]["val"][0]["member_id"] = "link"
        (root / "snapshot/link").symlink_to(member)
    before = set(root.iterdir())
    expected = RuntimeError if failure == "consumer" else ImportedSourceError
    with pytest.raises(expected):
        with evaluation_recordings(source):
            raise RuntimeError("consumer failed")
    assert set(root.iterdir()) == before
    assert member.read_bytes() == content
