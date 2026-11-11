"""SHA-256 of checkpoint files, reused while the file identity is unchanged.

The cache key is the stat identity of the opened file: device, inode, size,
modification time and change time (nanoseconds). Any write updates ``ctime``,
which unprivileged processes cannot restore, so rewritten or replaced files
are always re-hashed; a digest read while the file changed is stored under an
identity that no longer exists. See ADR 0077 for the accepted trust boundary.

Callers that deserialize bytes (inference loads) must keep hashing the exact
snapshot they deserialize; this cache only replaces repeated identity checks.
"""
import hashlib
import os
from collections import OrderedDict
from pathlib import Path
from threading import Lock

_CHUNK_SIZE = 1024 * 1024
_MAX_ENTRIES = 512
_digests: "OrderedDict[tuple, str]" = OrderedDict()
_lock = Lock()


def _identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def file_sha256(path) -> str:
    """Return the hex SHA-256 of ``path``, hashing its bytes only when needed."""
    with Path(path).open("rb") as stream:
        before = _identity(os.fstat(stream.fileno()))
        with _lock:
            cached = _digests.get(before)
            if cached is not None:
                _digests.move_to_end(before)
                return cached
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
        value = digest.hexdigest()
    with _lock:
        _digests[before] = value
        _digests.move_to_end(before)
        while len(_digests) > _MAX_ENTRIES:
            _digests.popitem(last=False)
    return value
