"""Concurrent verified readers do not compete for global audio spool space."""
import errno
import io
import tempfile
import wave

import pytest

from tests.test_dataset_import_api import imports, prepare, confirm


@pytest.mark.parametrize('finish_second', [True, False])
def test_verified_readers_share_small_global_temporary_volume(imports, tmp_path, monkeypatch, finish_second):
    from app.services.training_snapshots import TrainingSnapshots

    from app.database import Base

    client, source, _, sessions = imports
    Base.metadata.create_all(sessions.kw['bind'])
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x01\x00' * (768 * 1024))
    payload = buffer.getvalue()
    job = prepare(client, tmp_path, key='concurrent-spool', name='Concurrent WAV readers',
                  entries=[('birds/one.wav', payload)])
    confirmed = confirm(client, job)
    assert confirmed.status_code == 200, confirmed.text
    snapshots = TrainingSnapshots(sessions, source, tmp_path / 'reader-snapshots')
    snapshot = snapshots.create(1, confirmed.json()['dataset_id'])
    before = set(snapshots.root.iterdir())
    real_spool = tempfile.SpooledTemporaryFile
    allocations = {}
    budget = 5 * 1024 * 1024 // 2

    class CapacitySpool:
        def __init__(self, *args, **kwargs):
            self.file = real_spool(*args, **kwargs)
            self.global_volume = kwargs.get('dir') is None
            self.threshold = kwargs.get('max_size', 0)
            self.length = 0
            allocations[id(self)] = 0

        def __getattr__(self, name):
            return getattr(self.file, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()
            allocations.pop(id(self))

        def write(self, data):
            length = max(self.length, self.file.tell() + len(data))
            disk = length if self.global_volume and length > self.threshold else 0
            if sum(allocations.values()) - allocations[id(self)] + disk > budget:
                raise OSError(errno.ENOSPC, 'Synthetic global temporary capacity exhausted')
            result = self.file.write(data)
            self.length = length
            allocations[id(self)] = disk
            return result

    monkeypatch.setattr(tempfile, 'SpooledTemporaryFile', CapacitySpool)
    # One real member fits; retaining two global spills cannot fit.
    assert 1024 * 1024 < len(payload) <= budget < 2 * len(payload)
    first = snapshots.iter_verified(1, snapshot['id'])
    second = snapshots.iter_verified(1, snapshot['id'])
    try:
        first_meta, first_chunk = next(first)
        second_meta, second_chunk = next(second)
        assert first_meta == second_meta
        assert len(first_chunk) == len(second_chunk) == 1024 * 1024
        if finish_second:
            assert second_chunk + b''.join(chunk for _, chunk in second) == payload
        else:
            second.close()
        assert first_chunk + b''.join(chunk for _, chunk in first) == payload
    finally:
        first.close()
        second.close()
    assert allocations == {}
    assert snapshots.get(1, snapshot['id']) == snapshot
    assert set(snapshots.root.iterdir()) == before
