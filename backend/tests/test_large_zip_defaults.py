"""Large defaults through public HTTP; declared sizes never allocate a GB blob."""
from dataclasses import replace

from tests.test_dataset_import_api import imports
from tests.test_dataset_import_receipts import BASE, create, migrate, start


REFERENCE_ARCHIVE_BYTES = 5_620_955_136


def test_default_large_archive_policy_admits_reference_and_enforces_boundary(imports, monkeypatch):
    from types import SimpleNamespace

    # Admission tests declare GB sizes but allocate only synthetic small files.
    # Capacity is a controlled prerequisite, not the developer disk's free space.
    monkeypatch.setattr("app.services.dataset_imports.shutil.disk_usage",
                        lambda _: SimpleNamespace(free=64 * 1024**3))
    client, _, _, sessions = imports
    response = client.get(BASE + '/limits')
    assert response.status_code == 200, response.text
    policy = response.json()
    assert policy['received_bytes'] == 6_442_450_944
    assert policy['expanded_bytes'] == 10_737_418_240
    assert policy['audio_bytes'] == 100_663_296
    assert policy['validation_seconds'] == 900
    assert policy['entries'] == 2000
    assert policy['audio_seconds'] == 600

    migrate(sessions)
    identity = create(client, 'reference-large')
    accepted = start(client, identity, size=REFERENCE_ARCHIVE_BYTES, name='reference.zip')
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {
        'import_id': identity, 'name': 'reference.zip',
        'size_bytes': REFERENCE_ARCHIVE_BYTES, 'reserved_bytes': 16_358_373_376,
        'received_bytes': 0, 'chunk_bytes': 16_777_216, 'status': 'receiving',
    }
    assert client.get(f'{BASE}/{identity}/receipt').json() == accepted.json()
    assert client.post(f'{BASE}/{identity}/cancel').status_code == 200
    assert client.get(f'{BASE}/{identity}/receipt').json()['reserved_bytes'] == 0

    boundary = create(client, 'large-boundary')
    before = client.get(f'{BASE}/{boundary}').json()
    rejected = start(client, boundary, size=6_442_450_945)
    assert rejected.status_code == 413
    assert rejected.json() == {'detail': 'El ZIP supera el límite recibido. Reduce el archivo.'}
    assert client.get(f'{BASE}/{boundary}').json() == before
    assert client.get(f'{BASE}/{boundary}/receipt').status_code == 404
    # Rejection must not retain a receipt or consume the owner's reservation.
    accepted_boundary = start(client, boundary, size=6_442_450_944)
    assert accepted_boundary.status_code == 200, accepted_boundary.text
    assert accepted_boundary.json()['reserved_bytes'] == 17_179_869_184
    assert accepted_boundary.json()['received_bytes'] == 0


def test_worker_default_budget_covers_large_validation_and_explicit_bound_still_wins(imports, tmp_path, capsys):
    import pytest
    from app.services.dataset_import_worker import ImportJobWorker
    from scripts.run_dataset_import_worker import main

    client, _, _, _ = imports
    worker = ImportJobWorker(client.execution.queue, tmp_path, lambda *_: {})
    assert worker.execution_seconds == 1800
    assert worker.lease_seconds == 60
    assert worker.execution_seconds > client.get(BASE + '/limits').json()['validation_seconds']
    explicit = ImportJobWorker(client.execution.queue, tmp_path, lambda *_: {}, execution_seconds=900)
    assert explicit.execution_seconds == 900
    with pytest.raises(SystemExit) as result:
        main(['--help'])
    assert result.value.code == 0
    output = capsys.readouterr()
    assert 'default 1800' in ' '.join(output.out.split())
    assert output.err == ''


def test_explicit_small_environment_policy_still_controls_public_admission(imports, monkeypatch):
    from app.services.dataset_zip import ImportLimits

    client, service, _, sessions = imports
    for name, value in {'RECEIVED_BYTES': 1024, 'EXPANDED_BYTES': 2048,
                        'AUDIO_BYTES': 512, 'VALIDATION_SECONDS': 2}.items():
        monkeypatch.setenv('FAMA_IMPORT_' + name, str(value))
    service.limits = replace(ImportLimits.from_environment(), free_bytes=1)
    limits = client.get(BASE + '/limits')
    assert limits.status_code == 200
    assert {key: limits.json()[key] for key in
            ('received_bytes', 'expanded_bytes', 'audio_bytes', 'validation_seconds')} == {
        'received_bytes': 1024, 'expanded_bytes': 2048,
        'audio_bytes': 512, 'validation_seconds': 2,
    }
    migrate(sessions)
    identity = create(client, 'explicit-small')
    before = client.get(f'{BASE}/{identity}').json()
    rejected = start(client, identity, size=1025)
    assert rejected.status_code == 413
    assert rejected.json() == {'detail': 'El ZIP supera el límite recibido. Reduce el archivo.'}
    assert client.get(f'{BASE}/{identity}').json() == before
    assert client.get(f'{BASE}/{identity}/receipt').status_code == 404
    accepted = start(client, identity, size=1024)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['reserved_bytes'] == 3072
