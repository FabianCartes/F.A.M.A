"""Discovery and grants through authenticated HTTP, isolated from cloud/files."""
from tests.test_resource_access import access, functional, assign
from tests.test_web_sessions import web, login, ORIGIN


def test_catalogue_requests_and_administrator_decision_keep_operations_scoped(functional):
    client, _ = functional
    assert client.get('/api/datasets/catalogue').status_code == 401
    assert login(client).status_code == 200
    page = client.get('/api/datasets/catalogue')
    assert page.status_code == 200
    assert page.json()['total'] == 2
    item = page.json()['datasets'][0]
    assert item == {'dataset_id': 10, 'name': 'AvesChilenas', 'audio_count': 0,
                    'size_bytes': 0, 'purpose': 'Entrenamiento bioacústico',
                    'assigned': False, 'request_status': None}
    assert 'ruta_gcp' not in page.text
    for _ in range(2):
        pending = client.post('/api/datasets/10/requests', headers={'Origin': ORIGIN})
        assert pending.status_code == 200
        assert pending.json()['status'] == 'pending'
    assert client.get('/api/ingestion/datasets/AvesChilenas/files').status_code == 404
    assert client.get('/api/access/requests').status_code == 403
    assert client.post('/api/access/requests/2/10/decision', json={'decision': 'approve'},
                       headers={'Origin': ORIGIN}).status_code == 403
    assert login(client, 'administrador').status_code == 200
    inbox = client.get('/api/access/requests').json()
    assert inbox['total'] == 1
    assert inbox['requests'][0]['user_id'] == 2
    for _ in range(2):
        accepted = client.post('/api/access/requests/2/10/decision', json={'decision': 'approve'},
                               headers={'Origin': ORIGIN})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()['status'] == 'approved'
    assert login(client).status_code == 200
    item = client.get('/api/datasets/catalogue').json()['datasets'][0]
    assert item['assigned'] is True
    assert item['request_status'] == 'approved'
    assert client.get('/api/ingestion/datasets/AvesChilenas/files').status_code == 200
    assert login(client, 'administrador').status_code == 200
    assert client.delete('/api/access/users/2/datasets/10', headers={'Origin': ORIGIN}).status_code == 204
    # Replaying an already decided request must not undo a subsequent revocation.
    replay = client.post('/api/access/requests/2/10/decision', json={'decision': 'approve'},
                         headers={'Origin': ORIGIN})
    assert replay.status_code == 200
    assert replay.json().get('assigned') is False
    assert login(client).status_code == 200
    assert client.get('/api/ingestion/datasets/AvesChilenas/files').status_code == 404
    assert client.post('/api/datasets/10/requests', headers={'Origin': ORIGIN}).json()['status'] == 'pending'


def test_rejection_does_not_grant_access_and_can_be_requested_again(functional):
    client, _ = functional
    assert login(client).status_code == 200
    assert client.post('/api/datasets/999/requests', headers={'Origin': ORIGIN}).status_code == 404
    assert client.post('/api/datasets/20/requests', headers={'Origin': ORIGIN}).status_code == 200
    assert login(client, 'administrador').status_code == 200
    response = client.post('/api/access/requests/2/20/decision', json={'decision': 'reject'}, headers={'Origin': ORIGIN})
    assert response.status_code == 200
    assert response.json()['status'] == 'rejected'
    assert client.get('/api/access/users/2/datasets/20').json()['assigned'] is False
    assert client.post('/api/access/requests/2/20/decision', json={'decision': 'approve'}, headers={'Origin': ORIGIN}).status_code == 409
    assert login(client).status_code == 200
    assert client.get('/api/datasets/catalogue').json()['datasets'][1]['request_status'] == 'rejected'
    assert client.post('/api/datasets/20/requests', headers={'Origin': ORIGIN}).json()['status'] == 'pending'


def test_request_routes_reject_untrusted_origin_and_bound_catalogue_pages(functional):
    client, _ = functional
    assert login(client).status_code == 200
    assert client.post('/api/datasets/10/requests', headers={'Origin': 'https://other.test'}).status_code == 403
    for query in ('limit=0', 'limit=101', 'offset=-1'):
        assert client.get('/api/datasets/catalogue?' + query).status_code == 422
    page = client.get('/api/datasets/catalogue?limit=1&offset=1').json()
    assert page['total'] == 2
    assert [item['dataset_id'] for item in page['datasets']] == [20]
