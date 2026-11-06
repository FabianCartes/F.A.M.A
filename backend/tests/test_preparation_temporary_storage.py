"""Public preparation remains usable when the global temporary volume is small."""
import errno
import io
import tempfile
import wave

from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_imported_dataset_preparation import cohort


def test_preparation_large_members_do_not_duplicate_global_temporary_storage(imports, cohort, tmp_path, monkeypatch):
    from app.services.training_snapshots import TrainingSnapshots
    from training.imported_dataset_preparation import ImportedDatasetPreparation

    client, source, _, sessions = imports
    entries = []
    for label_index, label in enumerate(('ants', 'zebra')):
        for group in range(3):
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes((group + 1 + label_index * 3).to_bytes(2, 'little') * (768 * 1024))
            entries.append((f'{label}/{group}.wav', buffer.getvalue()))
    job = prepare(client, tmp_path, key='large-spool', name='Large spool WAVs', entries=entries)
    confirmed = confirm(client, job)
    assert confirmed.status_code == 200, confirmed.text
    dataset = confirmed.json()['dataset_id']
    snapshots = TrainingSnapshots(sessions, source, tmp_path / 'large-snapshots')
    snapshot = snapshots.create(1, dataset)
    before_entries = set(snapshots.root.iterdir())
    members = {m['member_id']: m for m, _ in snapshots.iter_verified(1, snapshot['id'])}
    mapping = [dict(member_id=key, recording_id=key, group_id=key) for key in members]

    # Model a global temporary volume that fits one verified member, not two.
    # Real file contents, WAV parsing, hashing and the private fixture guard stay
    # active; only this environmental capacity boundary is deterministic.
    real_spool = tempfile.SpooledTemporaryFile
    global_sizes = {}
    peak = 0
    budget = 5 * 1024 * 1024 // 2

    class LimitedGlobalSpool:
        def __init__(self, *args, **kwargs):
            self.file = real_spool(*args, **kwargs)
            self.global_volume = kwargs.get('dir') is None
            self.threshold = kwargs.get('max_size', 0)
            self.length = 0
            global_sizes[id(self)] = 0

        def __getattr__(self, name):
            return getattr(self.file, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()
            global_sizes.pop(id(self))

        def write(self, data):
            nonlocal peak
            length = max(self.length, self.file.tell() + len(data))
            disk = length if self.global_volume and length > self.threshold else 0
            projected = sum(global_sizes.values()) - global_sizes[id(self)] + disk
            if projected > budget:
                raise OSError(errno.ENOSPC, 'Synthetic global temporary capacity exhausted')
            result = self.file.write(data)
            self.length = length
            global_sizes[id(self)] = disk
            peak = max(peak, projected)
            return result

        def truncate(self, size=None):
            result = self.file.truncate(size)
            self.length = self.file.tell() if size is None else size
            global_sizes[id(self)] = self.length if self.global_volume and self.file._rolled else 0
            return result

    monkeypatch.setattr(tempfile, 'SpooledTemporaryFile', LimitedGlobalSpool)
    preparations = ImportedDatasetPreparation(snapshots, tmp_path / 'large-prepared')
    result = preparations.create(1, snapshot['id'], mapping=mapping,
        provenance={'source': 'per-wav-independent-assumption-v1'}, seed=42, profile=cohort[3])
    assert result['state'] == 'ready'
    assert result['file_count'] == 6
    assert result['policy']['name'] == 'per-wav-stratified-70-15-15-v1'
    assert preparations.get(1, snapshot['id'], result['version_id']) == result
    assert snapshot == snapshots.get(1, snapshot['id'])
    assert sum(len(rows) for rows in (list(preparations.read_split(1, snapshot['id'], result['version_id'], name)) for name in ('train', 'val', 'test'))) == 6
    assert set(snapshots.root.iterdir()) == before_entries
    assert global_sizes == {}
    assert peak == 0  # Both verified and consumer spools use private snapshot storage.
