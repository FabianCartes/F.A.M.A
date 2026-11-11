"""Link-safe access to private local storage roots."""
from contextlib import contextmanager
import os
from pathlib import PurePosixPath


class LocalStorageError(RuntimeError):
    """A local storage root or reference cannot be trusted."""


def _parts(value):
    if not isinstance(value, str) or not value or "\\" in value or any(p in ("", ".", "..") for p in value.split("/")) or PurePosixPath(value).is_absolute():
        raise LocalStorageError("Unsafe local reference")
    return value.split("/")


@contextmanager
def root_directory(path):
    """Create/open a trusted root without following any ancestor symlink."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in _parts(str(path).lstrip("/")):
            try:
                try:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        # Another creator may have won. Reopen without following
                        # links; the final root must still pass the privacy check.
                        pass
                    os.fsync(fd)
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as error:
                raise LocalStorageError("Unsafe local root") from error
            os.close(fd)
            fd = nxt
        if os.fstat(fd).st_mode & 0o077:
            raise LocalStorageError("Local root must be private")
        yield fd
    finally:
        os.close(fd)
