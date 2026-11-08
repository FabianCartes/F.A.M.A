"""Private archival through the authenticated public HTTP interface."""
from tests.test_dataset_import_api import imports, prepare, confirm
import pytest
from types import SimpleNamespace
from tests.test_dataset_exports import exported_source


def test_archive_hides_catalog_but_preserves_files_and_history(imports, tmp_path):
    client, service, _, sessions = imports
    job = prepare(client, tmp_path)
    published = confirm(client, job).json()
    dataset = client.get('/api/ingestion/imports/datasets').json()['datasets'][0]
    url = f"/api/ingestion/imports/datasets/{dataset['id']}"
    files = client.get(url + '/files').json()
    before = {str(p.relative_to(service.root)): p.read_bytes()
              for p in (service.root / 'objects').rglob('*') if p.is_file()}
    response = client.request('DELETE', url, json={'revision': dataset['revision']})
    assert response.status_code == 204, response.text
    assert client.get('/api/ingestion/imports/datasets').json()['datasets'] == []
    assert client.get(url + '/files').json() == files
    assert client.get(f"/api/ingestion/imports/{published['id']}").json()['status'] == 'imported'
    assert {str(p.relative_to(service.root)): p.read_bytes()
            for p in (service.root / 'objects').rglob('*') if p.is_file()} == before
    assert client.request('DELETE', url, json={'revision': dataset['revision']}).status_code == 204
    assert confirm(client, job).status_code == 409
    for payload in ({'request_key': 'new-target', 'name': 'Other', 'target_id': dataset['id']},
                    {'request_key': 'reserved-name', 'name': 'Birds'}):
        assert client.post('/api/ingestion/imports', json=payload).status_code == 409
    from app.models.dataset_import import ImportedDataset
    from app.models.dataset_import_metadata import DatasetSummary
    with sessions() as db:
        row = db.get(ImportedDataset, dataset['id'])
        summary = db.get(DatasetSummary, row.id)
        assert row.archived is True and row.revision == dataset['revision']
        assert (summary.file_count, summary.total_size_bytes) == (dataset['file_count'], dataset['total_size_bytes'])


def test_archive_keeps_remote_objects_and_admitted_export(exported_source, tmp_path):
    from copy import deepcopy
    from tests.test_dataset_exports import admit
    from app.services.dataset_exports import ExportQueue, ExportExecution
    client, service, _, sessions, storage, dataset_id, _ = exported_source
    admitted = admit(client, dataset_id)
    before = deepcopy(storage.objects)
    url = f'/api/ingestion/imports/datasets/{dataset_id}'
    assert client.request('DELETE', url, json={'revision': 1}).status_code == 204
    assert storage.objects == before
    assert client.post(url + '/revisions/1/exports', json={'request_key': 'new'}).status_code == 409
    assert client.post(url + '/revisions/1/exports', json={'request_key': 'export-1'}).json() == admitted
    assert ExportExecution(ExportQueue(sessions, service), tmp_path / 'exports', storage=storage).run_once()
    assert client.get(admitted['status_url']).json()['status'] == 'succeeded'
    assert storage.objects == before


def test_archive_commit_failure_rolls_back_and_retry_succeeds(imports, tmp_path, monkeypatch):
    from sqlalchemy.orm import Session
    client, _, _, _ = imports
    confirm(client, prepare(client, tmp_path))
    catalog = client.get('/api/ingestion/imports/datasets').json()
    dataset = catalog['datasets'][0]
    url = f"/api/ingestion/imports/datasets/{dataset['id']}"
    with monkeypatch.context() as patch:
        def fail_commit(self):
            raise RuntimeError('synthetic commit failure')
        patch.setattr(Session, 'commit', fail_commit)
        assert client.request('DELETE', url, json={'revision': dataset['revision']}).status_code == 500
    assert client.get('/api/ingestion/imports/datasets').json() == catalog
    assert client.request('DELETE', url, json={'revision': dataset['revision']}).status_code == 204


def test_archive_rejections_do_not_change_catalog(imports, tmp_path):
    from app.routes.dataset_imports import get_import_user
    client, _, app, _ = imports
    confirm(client, prepare(client, tmp_path))
    catalog = client.get('/api/ingestion/imports/datasets').json()
    dataset = catalog['datasets'][0]
    url = f"/api/ingestion/imports/datasets/{dataset['id']}"
    assert client.request('DELETE', url, json={'revision': dataset['revision'] + 1}).status_code == 409
    assert client.request('DELETE', url, json={'revision': True}).status_code == 422
    for identity in ('missing', 'AvesChilenas'):
        assert client.request('DELETE', '/api/ingestion/imports/datasets/' + identity, json={'revision': 0}).status_code == 404
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=2)
    assert client.request('DELETE', url, json={'revision': dataset['revision']}).status_code == 404
    app.dependency_overrides[get_import_user] = lambda: SimpleNamespace(id=1)
    assert client.get('/api/ingestion/imports/datasets').json() == catalog
    del app.dependency_overrides[get_import_user]
    assert client.request('DELETE', url, json={'revision': dataset['revision']}).status_code == 401


def test_admitted_confirmation_and_replay_survive_archive(imports, tmp_path):
    client, _, _, _ = imports
    first = prepare(client, tmp_path)
    dataset_id = confirm(client, first).json()['dataset_id']
    second = prepare(client, tmp_path, key='second', target_id=dataset_id, sample=2)
    payload = {'request_key': 'admitted', 'preview_token': second['preview_token']}
    endpoint = f"/api/ingestion/imports/{second['id']}/confirm"
    admitted = client.post(endpoint, json=payload)
    assert admitted.status_code == 202
    dataset = client.get('/api/ingestion/imports/datasets').json()['datasets'][0]
    assert client.request('DELETE', f'/api/ingestion/imports/datasets/{dataset_id}', json={'revision': dataset['revision']}).status_code == 204
    assert client.post(endpoint, json=payload).json() == admitted.json()
    assert client.execution.run_once()
    assert client.get(admitted.json()['status_url']).json()['status'] == 'succeeded'
    assert client.get('/api/ingestion/imports/datasets').json()['datasets'] == []
    assert len(client.get(f'/api/ingestion/imports/datasets/{dataset_id}/files').json()['files']) == 2
