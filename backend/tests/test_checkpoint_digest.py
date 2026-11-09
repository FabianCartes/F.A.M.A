"""Checkpoint file digests are reused only while the file identity is unchanged."""
import hashlib
import os
import time

import pytest

from app.services.checkpoint_digest import file_sha256


@pytest.fixture
def digest_spy(monkeypatch):
    """Record every full digest computed through hashlib, without changing results."""
    original = hashlib.sha256
    computed = []

    class Spy:
        def __init__(self, data=b""):
            self._hash = original(data)
            self.on_update = None

        def update(self, data):
            self._hash.update(data)
            if self.on_update is not None:
                callback, self.on_update = self.on_update, None
                callback()

        def hexdigest(self):
            value = self._hash.hexdigest()
            computed.append(value)
            return value

        def digest(self):
            return self._hash.digest()

    spies = []

    def factory(data=b""):
        spy = Spy(data)
        spies.append(spy)
        return spy

    monkeypatch.setattr(hashlib, "sha256", factory)
    return computed, spies


def _write(path, data):
    path.write_bytes(data)
    return original_sha256(data)


def original_sha256(data):
    return hashlib.new("sha256", data).hexdigest()


def test_digest_matches_file_contents(tmp_path):
    checkpoint = tmp_path / "model.pt"
    expected = _write(checkpoint, b"weights" * 4096)

    assert file_sha256(checkpoint) == expected
    assert file_sha256(str(checkpoint)) == expected


def test_unchanged_file_is_read_and_hashed_once(tmp_path, digest_spy):
    computed, _ = digest_spy
    checkpoint = tmp_path / "model.pt"
    expected = _write(checkpoint, b"weights" * 4096)

    assert [file_sha256(checkpoint) for _ in range(5)] == [expected] * 5
    assert computed.count(expected) == 1


def test_same_size_rewrite_with_restored_mtime_is_rehashed(tmp_path):
    checkpoint = tmp_path / "model.pt"
    _write(checkpoint, b"A" * 20000)
    original = checkpoint.stat()
    file_sha256(checkpoint)
    time.sleep(0.01)

    tampered = _write(checkpoint, b"B" * 20000)
    os.utime(checkpoint, ns=(original.st_atime_ns, original.st_mtime_ns))

    assert checkpoint.stat().st_size == original.st_size
    assert file_sha256(checkpoint) == tampered


def test_replaced_file_is_rehashed(tmp_path):
    checkpoint = tmp_path / "model.pt"
    _write(checkpoint, b"A" * 20000)
    file_sha256(checkpoint)
    replacement = tmp_path / "replacement.pt"
    expected = _write(replacement, b"C" * 20000)

    os.replace(replacement, checkpoint)

    assert file_sha256(checkpoint) == expected


def test_file_changed_while_hashing_is_rehashed_next_time(tmp_path, digest_spy):
    computed, spies = digest_spy
    checkpoint = tmp_path / "model.pt"
    _write(checkpoint, b"A" * 20000)

    original_factory = hashlib.sha256

    def changing_factory(data=b""):
        spy = original_factory(data)
        spy.on_update = lambda: checkpoint.write_bytes(b"D" * 30000)
        return spy

    hashlib.sha256 = changing_factory
    try:
        file_sha256(checkpoint)
    finally:
        hashlib.sha256 = original_factory

    expected = original_sha256(b"D" * 30000)
    assert file_sha256(checkpoint) == expected
    assert computed.count(expected) == 1


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        file_sha256(tmp_path / "missing.pt")
