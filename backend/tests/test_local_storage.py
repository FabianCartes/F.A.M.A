"""Link-safe private root opening through its public function."""
import os

import pytest

from app.services.local_storage import LocalStorageError, root_directory


def test_creates_a_private_root_and_yields_a_directory_descriptor(tmp_path):
    root = tmp_path / "a" / "b"
    with root_directory(root) as fd:
        assert os.fstat(fd).st_mode & 0o077 == 0
    assert root.is_dir() and root.stat().st_mode & 0o077 == 0


def test_rejects_a_symlinked_ancestor(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(real)
    with pytest.raises(LocalStorageError):
        with root_directory(tmp_path / "link" / "root"):
            pass


def test_rejects_a_group_accessible_root(tmp_path):
    root = tmp_path / "open"
    root.mkdir()
    root.chmod(0o750)
    with pytest.raises(LocalStorageError):
        with root_directory(root):
            pass
