"""Public private-source persistence contract, no network or database."""
from pathlib import Path
import pytest


def test_local_prediction_audio_is_durable_owned_and_byte_verified(tmp_path):
    from app.services.local_prediction_audio import LocalPredictionAudio
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    store = LocalPredictionAudio(root)
    content = b'original validated WAV bytes'
    key = store.save(1, content)
    assert key.startswith('local_predictions/1/')
    assert LocalPredictionAudio(root).read(1, key) == content
    with pytest.raises(ValueError):
        store.read(2, key)
    assert store.read(1, key) == content
    store.discard(1, key)
    with pytest.raises(FileNotFoundError):
        store.read(1, key)


@pytest.mark.parametrize('owner,key', [
    (True, 'local_predictions/1/a/b/1.wav'),
    (0, 'local_predictions/0/a/b/1.wav'),
    (1, '../outside.wav'),
    (1, '/absolute.wav'),
    (1, 'raw_audios/0123456789abcdef0123456789abcdef.wav'),
])
def test_local_source_rejects_untrusted_owner_or_key_before_io(tmp_path, owner, key):
    from app.services.local_prediction_audio import LocalPredictionAudio
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    with pytest.raises(ValueError):
        LocalPredictionAudio(root).read(owner, key)
    assert list(root.iterdir()) == []


def test_local_source_rejects_changed_bytes_symlinks_and_hardlinks(tmp_path):
    import os
    from app.services.local_prediction_audio import LocalPredictionAudio
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    store = LocalPredictionAudio(root)
    key = store.save(1, b'original')
    path = root / key
    assert path.stat().st_mode & 0o777 == 0o400
    assert all(p.stat().st_mode & 0o777 == 0o700 for p in path.parents if p.is_relative_to(root))
    path.chmod(0o600)
    path.write_bytes(b'tampered')
    with pytest.raises(ValueError):
        store.read(1, key)
    path.write_bytes(b'original')
    outside = tmp_path / 'outside.wav'
    os.link(path, outside)
    with pytest.raises(ValueError):
        store.read(1, key)
    outside.unlink()
    path.unlink()
    outside.write_bytes(b'original')
    path.symlink_to(outside)
    with pytest.raises(OSError):
        store.read(1, key)
    assert outside.read_bytes() == b'original'


def test_local_source_refuses_symlink_root_and_insufficient_space(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.services.local_prediction_audio import LocalPredictionAudio
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    alias = tmp_path / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(Exception):
        LocalPredictionAudio(alias).save(1, b'original')
    assert list(root.iterdir()) == []
    monkeypatch.setattr('os.fstatvfs', lambda fd: SimpleNamespace(f_bavail=1, f_frsize=1))
    with pytest.raises(OSError, match='Insufficient'):
        LocalPredictionAudio(root).save(1, b'original')
    assert list(root.rglob('*.wav')) == []



def test_read_keeps_verified_directory_descriptor_during_namespace_swap(tmp_path, monkeypatch):
    import os
    from app.services.local_prediction_audio import LocalPredictionAudio
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    store = LocalPredictionAudio(root)
    key = store.save(1, b'original')
    path = root / key
    outside = tmp_path / 'outside'
    outside.mkdir(mode=0o700)
    decoy = outside / path.name
    decoy.write_bytes(b'outsider')
    held = root / 'held-original'
    original_open = os.open
    swaps = []
    def swap_namespace(name, flags, *args, **kwargs):
        if name == path.name and kwargs.get('dir_fd') is not None and not swaps:
            path.parent.rename(held)
            path.parent.symlink_to(outside, target_is_directory=True)
            swaps.append(True)
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', swap_namespace)
    assert store.read(1, key) == b'original'
    assert swaps == [True]
    assert decoy.read_bytes() == b'outsider'
    with pytest.raises(OSError):
        store.discard(1, key)
    assert decoy.read_bytes() == b'outsider'
    assert (held / path.name).read_bytes() == b'original'


def test_read_rejects_bytes_changed_between_initial_stat_and_read(tmp_path, monkeypatch):
    import os
    import stat
    from app.services.local_prediction_audio import LocalPredictionAudio
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    store = LocalPredictionAudio(root)
    key = store.save(1, b'original')
    path = root / key
    inode = path.stat().st_ino
    original_stat = os.fstat
    mutations = []
    def mutate_after_stat(fd):
        info = original_stat(fd)
        if stat.S_ISREG(info.st_mode) and info.st_ino == inode and not mutations:
            mutations.append(True)
            path.chmod(0o600)
            path.write_bytes(b'mutated!')
            path.chmod(0o400)
        return info
    monkeypatch.setattr(os, 'fstat', mutate_after_stat)
    with pytest.raises(ValueError, match='integrity mismatch'):
        store.read(1, key)
    assert mutations == [True]
    assert path.read_bytes() == b'mutated!'
