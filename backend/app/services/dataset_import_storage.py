"""Conditional private GCS objects, verified by downloaded original-byte SHA-256."""
import hashlib
import os


class TransientSyncError(Exception):
    pass


class IntegrityConflict(Exception):
    pass


class _HashSink:
    def __init__(self, maximum, destination=None):
        self.digest = hashlib.sha256()
        self.size = 0
        self.maximum = maximum
        self.destination = destination

    def write(self, data):
        self.size += len(data)
        if self.size > self.maximum:
            raise IntegrityConflict("Remote object exceeds expected bytes")
        self.digest.update(data)
        if self.destination is not None:
            self.destination.write(data)
        return len(data)

    def tell(self):
        return self.size


class GCSImportStorage:
    def __init__(self, bucket_name=None, client=None):
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET_NAME")
        self.client = client

    def ensure(self, key, path, sha256, metadata):
        return self._ensure(key, path, sha256, metadata, "audio/wav")

    def ensure_manifest(self, key, path, sha256, metadata):
        return self._ensure(key, path, sha256, metadata, "application/json")

    def read_verified(self, key, generation, sha256, size_bytes, destination):
        """Caller supplies an authorized immutable reference and private sink."""
        from google.cloud import storage
        from google.api_core import exceptions
        if not self.bucket_name:
            raise ValueError("GCS bucket is not configured")
        try:
            client = self.client or storage.Client()
            blob = client.bucket(self.bucket_name).blob(key, generation=int(generation))
            sink = _HashSink(size_bytes, destination)
            blob.download_to_file(sink, if_generation_match=int(generation),
                                  raw_download=True, timeout=10, retry=None)
            if sink.size != size_bytes or sink.digest.hexdigest() != sha256:
                raise IntegrityConflict("Manifest digest mismatch")
        except (exceptions.NotFound, exceptions.PreconditionFailed):
            raise IntegrityConflict("Manifest generation unavailable") from None

    def _ensure(self, key, path, sha256, metadata, content_type):
        from google.cloud import storage
        from google.api_core import exceptions
        if not self.bucket_name:
            raise ValueError("GCS bucket is not configured")
        try:
            client = self.client or storage.Client()
            blob = client.bucket(self.bucket_name).blob(key)
            expected = dict(metadata, sha256=sha256)
            try:
                blob.reload(timeout=10, retry=None)
            except exceptions.NotFound:
                blob.metadata = expected
                try:
                    blob.upload_from_filename(str(path), content_type=content_type,
                        if_generation_match=0, timeout=10, retry=None)
                except exceptions.PreconditionFailed:
                    pass  # Another creator won; verify it, never overwrite.
                blob.reload(timeout=10, retry=None)
            if blob.metadata != expected or blob.size != path.stat().st_size:
                raise IntegrityConflict("Remote object identity mismatch")
            sink = _HashSink(path.stat().st_size)
            blob.download_to_file(sink, if_generation_match=int(blob.generation),
                                  raw_download=True, timeout=10, retry=None)
            if sink.size != path.stat().st_size or sink.digest.hexdigest() != sha256:
                raise IntegrityConflict("Remote original-byte digest mismatch")
            return str(blob.generation)
        except (exceptions.TooManyRequests, exceptions.ServiceUnavailable,
                exceptions.InternalServerError, exceptions.DeadlineExceeded,
                exceptions.GatewayTimeout, ConnectionError, TimeoutError) as error:
            raise TransientSyncError("Temporary storage failure") from error
