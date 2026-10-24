"""Application-level audit guard, NOT an OS sandbox or native-write guarantee."""
import os
from pathlib import Path
import sys


def install_guard(writable_directories, writable_files=()):
    """Install an irreversible process-local hook in a dedicated process.

    Native writes, pre-opened descriptors, hard-link aliases and races remain
    outside this guard's guarantee. Roots must already exist.
    """
    roots = tuple(Path(root).resolve(strict=True) for root in writable_directories)
    files = frozenset(Path(path).resolve() for path in writable_files)
    if not roots or any(not root.is_dir() for root in roots):
        raise ValueError('Writable directories must exist.')

    def resolve(path, fd=None, entry=False):
        if isinstance(path, int):
            try:
                return Path(os.readlink(f'/proc/self/fd/{path}')).resolve()
            except OSError as error:
                raise RuntimeError('Invalid file descriptor') from error
        path = Path(os.fsdecode(path))
        if not path.is_absolute():
            if fd is None or fd == -1:
                base = Path.cwd()
            else:
                try:
                    base = Path(os.readlink(f'/proc/self/fd/{fd}'))
                    if not base.is_dir():
                        raise OSError('Not a directory')
                except OSError as error:
                    raise RuntimeError('Invalid directory descriptor') from error
            path = base / path
        if entry and path.name not in ('.', '..'):
            return path.parent.resolve() / path.name
        return path.resolve()

    def check(event, path, fd=None, entry=False):
        target = resolve(path, fd, entry)
        if target not in files and not any(target == root or root in target.parents for root in roots):
            raise RuntimeError(f'Mutation blocked: {event}')

    def audit(event, args):
        if event == 'open':
            path, mode, flags = args
            if (mode and any(character in mode for character in 'wax+')) or (
                flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            ):
                check(event, path)
        elif event in ('os.remove', 'os.rmdir', 'os.mkdir'):
            fd = args[2] if event == 'os.mkdir' else args[1]
            check(event, args[0], fd, entry=True)
        elif event == 'os.symlink':
            check(event, args[1], args[2], entry=True)
        elif event == 'os.truncate':
            check(event, args[0])
        elif event == 'os.chmod':
            check(event, args[0], args[2])
        elif event in ('os.rename', 'os.link'):
            check(event, args[0], args[2], entry=event == 'os.rename')
            check(event, args[1], args[3], entry=True)
        elif event in ('os.chown', 'os.utime'):
            check(event, args[0], args[3])
        elif event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec'):
            raise RuntimeError(f'Process launch blocked: {event}')
        elif event == 'socket.connect':
            address = args[1]
            if (not isinstance(address, tuple) or len(address) < 2
                    or address[0] not in ('localhost', '127.0.0.1', '::1') or address[1] != 5432):
                raise RuntimeError('Network connection blocked')

    sys.addaudithook(audit)
