"""Read-only catalog date derived from durable import requests, not modifications."""
from tests.test_dataset_import_api import imports, prepare, confirm


def test_catalog_keeps_first_successful_import_date_after_more_audio(imports, tmp_path):
    from app.models.dataset_import import DatasetImport
    client, _, _, sessions = imports
    first = prepare(client, tmp_path)
    with sessions() as db:
        db.get(DatasetImport, first['id']).created_at = 1700000000
        db.commit()
    target = confirm(client, first).json()['dataset_id']
    second = prepare(client, tmp_path, key='later-audio', target_id=target, sample=2)
    with sessions() as db:
        db.get(DatasetImport, second['id']).created_at = 1800000000
        db.commit()
    assert confirm(client, second).json()['added_count'] == 1
    # Earlier requests without new content and foreign contributions are not this dataset's origin.
    duplicate = prepare(client, tmp_path, key='duplicate', target_id=target)
    assert confirm(client, duplicate).json()['added_count'] == 0
    with sessions() as db:
        db.get(DatasetImport, duplicate['id']).created_at = 1
        db.add(DatasetImport(id='f' * 32, owner_id=2, request_key='foreign', request={},
            status='imported', created_at=1, preview={}, added_count=1,
            sync_status='pending', dataset_id=target))
        db.add(DatasetImport(id='e' * 32, owner_id=1, request_key='failed', request={},
            status='failed', created_at=1, preview={}, added_count=1,
            sync_status='pending', dataset_id=target))
        db.commit()
    response = client.get('/api/ingestion/imports/datasets')
    assert response.status_code == 200, response.text
    assert len(response.json()['datasets']) == 1
    dataset = response.json()['datasets'][0]
    assert dataset['imported_at'] == 1700000000
    assert dataset['file_count'] == 2
    assert dataset['synced_file_count'] == 0
    assert dataset['revision'] == 2
    assert client.get('/api/ingestion/imports/datasets').json() == response.json()


def test_catalog_without_import_history_has_no_invented_date(imports):
    from app.models.dataset_import import ImportedDataset
    from app.models.dataset_import_metadata import DatasetSummary
    client, _, _, sessions = imports
    with sessions() as db:
        db.add(ImportedDataset(id='a' * 32, owner_id=1, name='Historical', description='', revision=0))
        db.flush()
        db.add(DatasetSummary(dataset_id='a' * 32, revision=0, file_count=0, class_count=0, total_size_bytes=0))
        db.commit()
    response = client.get('/api/ingestion/imports/datasets')
    assert response.status_code == 200, response.text
    assert response.json()['datasets'][0]['imported_at'] is None
