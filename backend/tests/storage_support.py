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
