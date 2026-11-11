"""Private immutable prediction sources; never cloud aliases or dataset membership."""
from contextlib import contextmanager, ExitStack
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

from app.services.local_storage import root_directory

MAX_BYTES = 100 * 1024 * 1024
_PATTERN = re.compile(r'local_predictions/([1-9][0-9]{0,18})/([0-9a-f]{32})/([0-9a-f]{64})/([1-9][0-9]{0,8})\.wav')


class LocalPredictionAudio:
    def __init__(self, root):
        self.root = Path(root).absolute()

    @staticmethod
    def _identity(owner, key):
        match = _PATTERN.fullmatch(key) if isinstance(key, str) else None
        if (type(owner) is not int or owner <= 0 or match is None
                or int(match[1]) != owner or int(match[4]) > MAX_BYTES):
            raise ValueError('Invalid private prediction source')
        return match[3], int(match[4])

    @contextmanager
    def _directory(self, parts, *, create=False):
        # Keep every directory open; a renamed ancestor cannot redirect an I/O.
        if not self.root.is_dir():
            raise FileNotFoundError('Prediction root unavailable')
        with root_directory(self.root) as root_fd, ExitStack() as stack:
            fd = root_fd
            for part in parts:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                stack.callback(os.close, child)
                info = os.fstat(child)
                if info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise ValueError('Prediction directory is not private')
                fd = child
            yield fd

    def save(self, owner, audio):
        if type(owner) is not int or owner <= 0 or not isinstance(audio, bytes) or not 0 < len(audio) <= MAX_BYTES:
            raise ValueError('Invalid private prediction audio')
        digest = hashlib.sha256(audio).hexdigest()
        key = f'local_predictions/{owner}/{uuid.uuid4().hex}/{digest}/{len(audio)}.wav'
        self._identity(owner, key)
        parts = key.split('/')
        with self._directory(parts[:-1], create=True) as directory:
            space = os.fstatvfs(directory)
            if space.f_bavail * space.f_frsize < len(audio) + 512 * 1024 * 1024:
                raise OSError('Insufficient prediction storage')
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(audio)
                    output.flush()
                    os.fchmod(output.fileno(), 0o400)
                    os.fsync(output.fileno())
                os.fsync(directory)
            except BaseException:
                os.unlink(parts[-1], dir_fd=directory)
                os.fsync(directory)
                raise
        return key

    def read(self, owner, key):
        digest, size = self._identity(owner, key)
        parts = key.split('/')
        with self._directory(parts[:-1]) as directory:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_size != size):
                    raise ValueError('Invalid private prediction file')
                audio = source.read(size + 1)
                after = os.fstat(source.fileno())
                if (len(audio) != size or hashlib.sha256(audio).hexdigest() != digest
                        or (info.st_mtime_ns, info.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)):
                    raise ValueError('Private prediction integrity mismatch')
        return audio

    def discard(self, owner, key):
        """Only a newly created, uncommitted source may be passed by the caller."""
        self._identity(owner, key)
        parts = key.split('/')
        with self._directory(parts[:-1]) as directory:
            os.unlink(parts[-1], dir_fd=directory)
            os.fsync(directory)
