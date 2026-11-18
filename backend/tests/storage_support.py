"""Synthetic storage configuration for tests that fake the GCS client.

Since explicit configuration (ADR 0058) there is no default bucket, so code that resolves a
bucket raises ``storage_configuration_missing`` before reaching a faked client. Tests that
fake ``storage.Client`` use this name; it never authorizes real cloud access.
"""
from contextlib import contextmanager
from dataclasses import replace

TEST_BUCKET = "fama-pruebas"


@contextmanager
def synthetic_bucket(name=TEST_BUCKET):
    """Activate a configuration whose bucket is ``name`` and restore the previous one."""
    from app.configuration import activate_configuration, get_configuration

    previous = get_configuration()
    activate_configuration(replace(previous, bucket_name=name))
    try:
        yield name
    finally:
        activate_configuration(previous)


SYNTHETIC_FREE_BYTES = 64 * 1024**3


def synthetic_disk_capacity(monkeypatch, free=SYNTHETIC_FREE_BYTES):
    """Make admission capacity a controlled prerequisite, not the developer disk's free space.

    Default import reservations promise more than 10 GiB, so the real free space of the
    test temporary directory would decide the result. Tests of the rejection set their own value.
    """
    from types import SimpleNamespace

    monkeypatch.setattr("app.services.dataset_imports.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=free))
