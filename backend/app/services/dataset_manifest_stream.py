"""Bound a manifest's actual output bytes before every physical write."""
from app.services.dataset_storage import _reject


class BoundedWriter:
    def __init__(self, destination, maximum, *, check):
        self.destination, self.maximum, self.check = destination, maximum, check
        self.size = 0
        self.stream = None

    def __enter__(self):
        self.check()
        self.stream = self.destination.open("xb")
        return self

    def write(self, data):
        if self.size + len(data) > self.maximum:
            _reject(507)
        self.check(len(data))
        written = self.stream.write(data)
        if written != len(data):
            raise OSError("Short manifest write")
        self.size += written
        return written

    def __exit__(self, *error):
        self.stream.close()
