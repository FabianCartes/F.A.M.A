"""Persistent local files bound to one database/bucket, independent of source and cwd."""
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from app.configuration import ConfigurationError, get_configuration


def runtime_root(configuration=None):
    configuration = configuration or get_configuration()
    if 'FAMA_RUNTIME_DIR' not in configuration.values:
        return None
    path = Path(configuration.values['FAMA_RUNTIME_DIR'])
    if (not path.is_absolute() or '..' in path.parts or path.resolve() != path
            or path == Path(path.anchor)):
        raise ConfigurationError('runtime_path_invalid')
    return path


class RuntimeDirectory:
    def __init__(self, configuration, directory=None):
        from sqlalchemy.engine import make_url

        self.configuration = configuration
        self.root = runtime_root(configuration) if directory is None else runtime_root(
            replace(configuration, values=dict(configuration.values, FAMA_RUNTIME_DIR=str(directory))))
        if self.root is None:
            raise ConfigurationError('runtime_not_configured')
        if not configuration.database_url or not configuration.bucket_name:
            raise ConfigurationError('runtime_identity_incomplete')
        from sqlalchemy.exc import ArgumentError
        try:
            url = make_url(configuration.database_url)
        except (ArgumentError, ValueError):
            raise ConfigurationError('runtime_identity_invalid') from None
        if url.drivername.startswith('sqlite') and (not url.database or url.database == ':memory:'
                                                   or not Path(url.database).is_absolute()):
            raise ConfigurationError('runtime_database_not_persistent')
        connection = configuration.values.get('FAMA_CLOUD_SQL_CONNECTION_NAME')
        identity = {'database': url.database, 'bucket': configuration.bucket_name,
                    'instance': connection or [url.drivername.split('+')[0], url.host, url.port]}
        self.binding = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.marker = self.root / '.fama-runtime.json'

    def _validate(self):
        if runtime_root(replace(self.configuration, values={'FAMA_RUNTIME_DIR': str(self.root)})) != self.root:
            raise ConfigurationError('runtime_path_invalid')
        try:
            if (self.marker.is_symlink() or self.marker.stat().st_size > 1024
                    or json.loads(self.marker.read_text(encoding='utf-8')) != {'version': 1, 'environment': self.binding}):
                raise ConfigurationError('runtime_identity_mismatch')
            for path in self.directories.values():
                if path.resolve() != path or not path.is_dir():
                    raise ConfigurationError('runtime_layout_invalid')
        except ConfigurationError:
            raise
        except (OSError, ValueError, TypeError):
            raise ConfigurationError('runtime_unprepared') from None

    @property
    def directories(self):
        return {'raw': self.root / 'data/raw', 'processed': self.root / 'data/processed',
                'checkpoints': self.root / 'checkpoints', 'logs': self.root / 'logs'}

    def prepare(self):
        if self.marker.exists():
            return self.describe()
        if self.root.exists() and any(self.root.iterdir()):
            raise ConfigurationError('runtime_directory_not_empty')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in self.directories.values():
            path.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix='.runtime-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps({'version': 1, 'environment': self.binding}).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, self.marker)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return self.describe()

    def describe(self):
        self._validate()
        return {'code': 'runtime_ready', 'root': str(self.root), 'environment': self.binding,
                'directories': {name: str(path) for name, path in self.directories.items()}}

    @contextmanager
    def lease(self):
        """One local process owns the tree while its node is alive; close releases ownership."""
        self._validate()
        path = self.root / '.fama-runtime.lock'
        if path.is_symlink() or path.resolve() != path:
            raise ConfigurationError('runtime_path_invalid')
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except OSError:
            raise ConfigurationError('runtime_lock_unavailable') from None
        try:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ConfigurationError('runtime_in_use') from None
            yield self
        finally:
            os.close(descriptor)
