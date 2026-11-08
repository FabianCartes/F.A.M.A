"""Latest-ten opt-in history over the public HTTP interface; no cloud or ZIP IO."""
from tests.test_dataset_import_api import imports
from app.models.dataset_import_receipt import ImportReceipt


def test_latest_history_names_dates_owner_scope_and_legacy_pagination(imports):
    from app.models.dataset_import import DatasetImport
    from app.models.dataset_import_receipt import ImportReceipt
    client, service, app, sessions = imports
    ids = []
    for index in range(12):
        response = client.post('/api/ingestion/imports', json={
            'request_key': f'history-{index}', 'name': f'Dataset {index}', 'description': ''})
        assert response.status_code == 200, response.text
        ids.append(response.json()['id'])
        with sessions() as db:
            db.get(DatasetImport, ids[-1]).status = 'cancelled'
            db.commit()
    with sessions() as db:
        for index, identity in enumerate(ids):
            row = db.get(DatasetImport, identity)
            row.created_at = 1700000000 + index
            db.add(ImportReceipt(import_id=identity, name=f'original_{index}.zip', size_bytes=1,
                reserved_bytes=1, reservation_active=False, received_bytes=1,
                chunk_bytes=1, status='sealed'))
        db.get(DatasetImport, ids[-1]).owner_id = 2  # Newest foreign row cannot consume the limit.
        db.commit()
    response = client.get('/api/ingestion/imports?latest=true')
    assert response.status_code == 200, response.text
    result = response.json()
    assert [row['id'] for row in result['imports']] == list(reversed(ids[1:11]))
    assert [row['archive_name'] for row in result['imports']] == [f'original_{index}.zip' for index in range(10, 0, -1)]
    assert [row['created_at'] for row in result['imports']] == list(reversed(range(1700000001, 1700000011)))
    assert result['next_cursor'] is None
    assert result['total'] == 11
    assert 'original_11.zip' not in response.text
    # Optional mode never changes legacy ID-ordered paging or detail recovery.
    legacy = client.get('/api/ingestion/imports?limit=2').json()
    assert [row['id'] for row in legacy['imports']] == sorted(ids[:-1])[:2]
    assert legacy['next_cursor'] is not None
    assert client.get('/api/ingestion/imports?latest=true&cursor=' + legacy['next_cursor']).status_code == 422
    capped = client.get('/api/ingestion/imports?latest=true&limit=200').json()
    assert len(capped['imports']) == 10
    detail = client.get('/api/ingestion/imports/' + ids[10])
    assert detail.status_code == 200
    assert detail.json()['archive_name'] == 'original_10.zip'
    with sessions() as db:
        assert db.query(DatasetImport).count() == 12
        assert db.query(ImportReceipt).count() == 12
        assert all(row.status == 'cancelled' and row.sync_status == 'pending' for row in db.query(DatasetImport))


def test_history_missing_receipt_and_equal_dates_have_stable_order(imports):
    client, service, app, sessions = imports
    from app.models.dataset_import import DatasetImport
    ids = []
    for index in range(2):
        row = client.post('/api/ingestion/imports', json={
            'request_key': f'empty-{index}', 'name': f'Name not a ZIP {index}', 'description': ''})
        assert row.status_code == 200
        ids.append(row.json()['id'])
    with sessions() as db:
        for row in db.query(DatasetImport):
            row.created_at = 1700000000
        db.commit()
    response = client.get('/api/ingestion/imports?latest=true')
    assert response.status_code == 200
    rows = response.json()['imports']
    assert [row['id'] for row in rows] == sorted(ids, reverse=True)
    assert all(row['archive_name'] is None for row in rows)
