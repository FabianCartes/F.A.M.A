"""Conditional private GCS objects, verified by downloaded original-byte SHA-256."""
import hashlib
import os


class TransientSyncError(Exception):
    pass


class IntegrityConflict(Exception):
    pass


class _HashSink:
    def __init__(self, maximum):
        self.digest = hashlib.sha256()
        self.size = 0
        self.maximum = maximum

    def write(self, data):
        self.size += len(data)
        if self.size > self.maximum:
            raise IntegrityConflict("Remote object exceeds expected bytes")
        self.digest.update(data)
        return len(data)

    def tell(self):
        return self.size


class GCSImportStorage:
    def __init__(self, bucket_name=None, client=None):
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET_NAME")
        self.client = client

    def ensure(self, key, path, sha256, metadata):
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
                    blob.upload_from_filename(str(path), content_type="audio/wav",
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
