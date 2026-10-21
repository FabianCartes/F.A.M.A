"""Bounded original-byte manifest I/O, matching the existing export wire limits."""
import hashlib

from app.services.dataset_import_storage import IntegrityConflict


MANIFEST_BYTES = 128 * 1024**2
RECORD_BYTES = 16384
MEMBERS = 50000


class BoundedWriter:
    """Measure BEFORE forwarding each write; never spool or allocate another file.

    The destination is owned synchronously by the caller. A physical writer
    supplies its pool's live free-space check; byte counting never refunds grants.
    """

    def __init__(self, destination, maximum, *, check=None):
        if type(maximum) is not int or not 0 < maximum <= MANIFEST_BYTES:
            raise IntegrityConflict("Invalid manifest byte bound")
        self.destination, self.maximum, self.check = destination, maximum, check
        self.size, self.digest = 0, hashlib.sha256()

    def write(self, data):
        if self.size + len(data) > self.maximum:
            raise IntegrityConflict("Manifest exceeds byte bound")
        if self.check is not None:
            self.check()
        written = self.destination.write(data)
        if written != len(data):
            raise OSError("Short manifest write")
        self.digest.update(data)
        self.size += len(data)
        return written

    def tell(self):
        return self.size

    def verify(self, size, digest):
        if self.size != size or self.digest.hexdigest() != digest:
            raise IntegrityConflict("Manifest integrity mismatch")
