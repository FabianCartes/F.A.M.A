"""Archival separates new admission from retained historical preparations."""
import pytest
from fastapi import HTTPException
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create


@pytest.mark.parametrize('boundary', ['snapshot', 'preparation', 'training'])
def test_archive_schema_unavailable_keeps_503(cohort, tmp_path, monkeypatch, boundary):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from app.services.imported_training_source import ImportedTrainingSource
    from app.routes import imported_training
    from scripts.migrate_imported_training_source import migrate_imported_sources
    from scripts import migrate_dataset_import_archive
    snapshots, snapshot, mapping, profile, _, dataset_id = cohort
    preparations = ImportedDatasetPreparation(snapshots, tmp_path / 'prepared')
    prepared = create(preparations, cohort)
    migrate_imported_sources(snapshots.sessions.kw['bind'], writers_stopped=True)
    def incompatible(connection):
        raise RuntimeError('synthetic incompatible archive default')
    monkeypatch.setattr(migrate_dataset_import_archive, 'validate_archive', incompatible)
    if boundary == 'training':
        with pytest.raises(HTTPException) as failure:
            ImportedTrainingSource(preparations).resolve_for_training(
                1, dataset_id, snapshot['id'], prepared['version_id'], architecture='AudioCNN')
        assert failure.value.status_code == 503
    else:
        app = FastAPI()
        app.include_router(imported_training.router)
        app.dependency_overrides[imported_training.get_user] = lambda: SimpleNamespace(id=1)
        app.dependency_overrides[imported_training.get_preparations] = lambda: preparations
        with TestClient(app, raise_server_exceptions=False) as client:
            if boundary == 'snapshot':
                response = client.post('/api/training/imported/snapshots', json={'dataset_id': dataset_id})
            else:
                response = client.post(f"/api/training/imported/snapshots/{snapshot['id']}/preparations",
                    json={'mapping': mapping, 'profile': profile, 'provenance': {'source': 'synthetic'}, 'seed': 42})
            assert response.status_code == 503, response.text
    assert snapshots.get(1, snapshot['id']) == snapshot
    assert preparations.get(1, snapshot['id'], prepared['version_id']) == prepared


@pytest.mark.parametrize('archive_first', [True, False])
def test_training_source_admission_orders_with_archive(cohort, tmp_path, monkeypatch, archive_first):
    """Force archive between admission and capture, then exercise the reverse order."""
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from app.services.imported_training_source import ImportedTrainingSource, ImportedSourceError
    snapshots, snapshot, _, _, client, dataset_id = cohort
    preparations = ImportedDatasetPreparation(snapshots, tmp_path / 'prepared')
    prepared = create(preparations, cohort)
    source = ImportedTrainingSource(preparations)
    dataset = client.get('/api/ingestion/imports/datasets').json()['datasets'][0]
    events = []
    def archive_now():
        response = client.request('DELETE', f'/api/ingestion/imports/datasets/{dataset_id}',
                                  json={'revision': dataset['revision']})
        assert response.status_code == 204
        events.append('archived')
    original = source.resolve
    def capture(*args, **kwargs):
        events.append('admitted')
        archive_now()  # A different public request/session, after the gate commits.
        result = original(*args, **kwargs)
        events.append('captured')
        return result
    monkeypatch.setattr(source, 'resolve', capture)
    args = (1, dataset_id, snapshot['id'], prepared['version_id'])
    if archive_first:
        archive_now()
        with pytest.raises(ImportedSourceError):
            source.resolve_for_training(*args, architecture='AudioCNN')
        assert events == ['archived']
    else:
        admitted = source.resolve_for_training(*args, architecture='AudioCNN')
        assert admitted['classes'] == ['ants', 'zebra']
        assert events == ['admitted', 'archived', 'captured']
    assert client.get('/api/ingestion/imports/datasets').json()['datasets'] == []


def test_archive_preserves_prepared_source_but_blocks_new_admission(cohort, tmp_path):
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from app.services.imported_training_source import ImportedTrainingSource, ImportedSourceError
    snapshots, snapshot, _, _, client, dataset_id = cohort
    preparations = ImportedDatasetPreparation(snapshots, tmp_path / 'prepared')
    prepared = create(preparations, cohort)
    sources = ImportedTrainingSource(preparations)
    dataset = client.get('/api/ingestion/imports/datasets').json()['datasets'][0]
    url = f'/api/ingestion/imports/datasets/{dataset_id}'
    assert client.request('DELETE', url, json={'revision': dataset['revision']}).status_code == 204
    assert sources.catalog(1) == []
    assert preparations.get(1, snapshot['id'], prepared['version_id']) == prepared
    assert sources.resolve(1, dataset_id, snapshot['id'], prepared['version_id'], architecture='AudioCNN')['classes'] == ['ants', 'zebra']
    with pytest.raises(ImportedSourceError):
        sources.resolve_for_training(1, dataset_id, snapshot['id'], prepared['version_id'], architecture='AudioCNN')
    with pytest.raises(HTTPException) as failure:
        snapshots.create(1, dataset_id)
    assert failure.value.status_code == 409
    with pytest.raises(HTTPException):
        snapshots.admit_preparation(1, snapshot['id'])
    assert snapshots.get(1, snapshot['id']) == snapshot
