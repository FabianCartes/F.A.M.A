"""Explicit, byte-verified checkpoint copies; no deserialization or activation."""
import hashlib
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage

from app.configuration import storage_bucket


class CheckpointConflict(ValueError):
    """A recoverable state requiring an explicit operator/user decision."""


def identity(path):
    size, digest = 0, hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


class CheckpointCopies:
    def __init__(self, model, root):
        self.model = model
        self.root = Path(root).absolute()
        self.bucket_name = storage_bucket()
        self.sha256 = model.hash_binario or ''
        reference = model.ruta_binario_gcp or ''
        dataset = model.conjunto_datos
        if (not re.fullmatch(r'[0-9a-f]{64}', self.sha256)
                or not 0 < model.tamano_bytes <= 1024**3
                or not re.fullmatch(r'models/[A-Za-z0-9][A-Za-z0-9_.-]{0,220}\.pt', reference)
                or dataset is None or not dataset.ruta_gcp.startswith(f'gs://{self.bucket_name}/')):
            raise CheckpointConflict('El modelo no tiene identidad, tamaño o destino verificables para esta instalación.')
        self.filename = reference.removeprefix('models/')
        self.key = f'models/checkpoints/sha256/{self.sha256}.pt'
        if self.root.resolve(strict=True) != self.root or not self.root.is_dir():
            raise CheckpointConflict('El directorio de checkpoints necesita revisión del operador.')
        self.path = self.root / self.filename

    def _local(self):
        if self.path.is_symlink() or getattr(self.path, 'is_junction', lambda: False)():
            return 'conflict'
        if not self.path.exists():
            return 'missing'
        if not self.path.is_file() or self.path.resolve() != self.path:
            return 'conflict'
        return 'valid' if identity(self.path) == (self.model.tamano_bytes, self.sha256) else 'conflict'

    def _remote_state(self, blob):
        if blob is None:
            return 'missing'
        if (blob.size != self.model.tamano_bytes or not blob.generation
                or blob.content_encoding not in (None, '', 'identity')):
            return 'conflict'
        return 'available'

    def _result(self, local, blob, verified=False):
        return {'model_id': self.model.id_modelo, 'filename': self.filename,
                'sha256': self.sha256, 'size_bytes': self.model.tamano_bytes,
                'local': local, 'cloud': self._remote_state(blob),
                'generation': str(blob.generation) if blob else None,
                'transfer_verified': verified}

    def status(self):
        local = self._local()
        blob = storage.Client().bucket(self.bucket_name).get_blob(self.key, timeout=30)
        return self._result(local, blob)

    @contextmanager
    def _temporary(self):
        with tempfile.NamedTemporaryFile(dir=self.root, prefix='.checkpoint-', delete=False) as stream:
            path = Path(stream.name)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    def _download(self, blob, destination):
        if self._remote_state(blob) != 'available':
            raise CheckpointConflict('No hay un respaldo compatible disponible en GCS.')
        blob.download_to_filename(str(destination), if_generation_match=int(blob.generation),
                                  raw_download=True, checksum='auto', timeout=60)
        if identity(destination) != (self.model.tamano_bytes, self.sha256):
            raise CheckpointConflict('El respaldo descargado no coincide con el tamaño y SHA-256 registrados. Se conserva la copia local.')

    def backup(self):
        if self._local() != 'valid':
            raise CheckpointConflict('Se necesita una copia local íntegra para respaldar este modelo.')
        with self._temporary() as snapshot, self._temporary() as verification:
            # Upload a stable snapshot, not a pathname that another process can change mid-transfer.
            with self.path.open('rb') as source, snapshot.open('wb') as target:
                size = 0
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    size += len(block)
                    if size > self.model.tamano_bytes:
                        raise CheckpointConflict('El checkpoint cambió durante la preparación del respaldo.')
                    target.write(block)
            if identity(snapshot) != (self.model.tamano_bytes, self.sha256):
                raise CheckpointConflict('El checkpoint cambió durante la preparación del respaldo.')
            bucket = storage.Client().bucket(self.bucket_name)
            blob = bucket.get_blob(self.key, timeout=30)
            if blob is None:
                try:
                    bucket.blob(self.key).upload_from_filename(str(snapshot), if_generation_match=0,
                        content_type='application/octet-stream', checksum='auto', timeout=60)
                except PreconditionFailed:
                    pass  # A concurrent retry may have published the same content-addressed object.
                blob = bucket.get_blob(self.key, timeout=30)
            self._download(blob, verification)
            return self._result(self._local(), blob, verified=True)

    def restore(self):
        local = self._local()
        if local == 'conflict':
            raise CheckpointConflict('Ya existe un archivo local distinto. El operador debe preservarlo y revisar el conflicto antes de recuperar.')
        blob = storage.Client().bucket(self.bucket_name).get_blob(self.key, timeout=30)
        with self._temporary() as temporary:
            self._download(blob, temporary)
            if local == 'missing':
                with temporary.open('r+b') as stream:
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, self.path)
                except FileExistsError:
                    if self._local() != 'valid':
                        raise CheckpointConflict('Apareció otro archivo local durante la recuperación; se conserva sin reemplazarlo.') from None
                if hasattr(os, 'O_DIRECTORY'):
                    descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            return self._result(self._local(), blob, verified=True)
