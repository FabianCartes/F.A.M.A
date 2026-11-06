"""Owner-scoped history exercised only through the HTTP interface."""
from datetime import datetime, timezone
import pytest
from tests.test_api_feedback import client, test_db, fake_gcs
from tests.test_imported_feedback_api import owners
from app.models.dataset_import import ImportedDataset
from app.models.prediction import Prediccion


@pytest.fixture
def history_rows(test_db, owners):
    test_db.add(ImportedDataset(id='a' * 32, owner_id=1, name='Birds', revision=1))
    def row(identity, key=None, model='301', dataset=None):
        return Prediccion(id_prediccion=identity, nombre_original=f'call-{identity}.wav',
            ruta_audio_prueba=key or f'local_predictions/1/{identity:032x}/' + 'a' * 64 + '/44.wav',
            etiqueta_predicha='bird', confianza=.75, modelo_id=model,
            dataset_name=dataset or 'imported:' + 'a' * 32,
            fecha_prediccion=datetime(2026, 1, 1, tzinfo=timezone.utc))
    test_db.add_all([row(1), row(2, model='fama_trained_model_301'),
        row(3, key='local_predictions/2/' + 'c' * 32 + '/' + 'a' * 64 + '/44.wav'),
        row(4, key='raw_audios/legacy.wav'), row(5, model='302'),
        row(6, key='local_predictions/1/../secret.wav'),
        row(7, dataset='imported:' + 'e' * 32)])
    test_db.commit()
    return owners


def test_private_history_persists_and_pages_only_attributable_exact_model(client, history_rows):
    response = client.get('/api/inference/history?model_id=fama_trained_model_301&limit=1', headers=history_rows[1])
    assert response.status_code == 200, response.text
    assert response.json() == {'items': [{'id': 2, 'filename': 'call-2.wav',
        'timestamp': '2026-01-01T00:00:00Z', 'clase': 'bird', 'confianza': .75,
        'modelo_id': 'fama_trained_model_301'}], 'next_cursor': 2}
    page = client.get('/api/inference/history?model_id=301&limit=1&cursor=2', headers=history_rows[1])
    assert page.status_code == 200, page.text
    assert [r['id'] for r in page.json()['items']] == [1]
    assert page.json()['next_cursor'] is None
    assert client.get('/api/inference/history?model_id=301&limit=1', headers=history_rows[1]).json() == response.json()


@pytest.mark.parametrize('model', ['301', 'fama_trained_model_301', '302', 'public-model'])
def test_private_history_does_not_disclose_foreign_or_unknown_models(client, history_rows, model):
    response = client.get('/api/inference/history', params={'model_id': model}, headers=history_rows[2])
    assert response.status_code == 404, response.text
    assert response.json() == {'detail': 'Modelo no disponible.'}


def test_private_history_requires_authentication_and_bounds_pages(client, history_rows):
    response = client.get('/api/inference/history?model_id=301')
    assert response.status_code == 401
    assert response.json() == {'detail': 'Autenticación requerida. Token no provisto.'}
    for query in ('limit=0', 'limit=21', 'cursor=0', 'cursor=bad'):
        response = client.get('/api/inference/history?model_id=301&' + query, headers=history_rows[1])
        assert response.status_code == 422, response.text
    assert client.get('/api/inference/history?model_id=301', headers=history_rows[1]).json()['next_cursor'] is None


def test_history_twenty_row_boundary_and_sparse_window_are_read_only(client, test_db, history_rows):
    from sqlalchemy import event
    for number in range(10, 231):
        test_db.add(Prediccion(id_prediccion=number, nombre_original=f'call-{number}.wav',
            ruta_audio_prueba=f'local_predictions/1/{number:032x}/' + 'b' * 64 + '/44.wav',
            etiqueta_predicha='bird', confianza=.75, modelo_id='301',
            dataset_name='imported:' + 'a' * 32))
    test_db.commit()
    statements = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())
    event.listen(test_db.get_bind(), 'before_cursor_execute', observe)
    try:
        response = client.get('/api/inference/history?model_id=301', headers=history_rows[1])
        assert response.status_code == 200
        body = response.json()
        assert [row['id'] for row in body['items']] == list(range(230, 210, -1))
        assert body['next_cursor'] == 211
        assert all(set(row) == {'id','filename','timestamp','clase','confianza','modelo_id'} for row in body['items'])
        assert 'local_predictions' not in response.text
        next_page = client.get('/api/inference/history?model_id=301&cursor=211', headers=history_rows[1])
        assert [row['id'] for row in next_page.json()['items']] == list(range(210, 190, -1))
        assert not ({'INSERT', 'UPDATE', 'DELETE', 'ALTER', 'CREATE', 'DROP'} & set(statements))
    finally:
        event.remove(test_db.get_bind(), 'before_cursor_execute', observe)
    # A long run of malformed references must be bounded but remain traversable.
    for row in test_db.query(Prediccion).filter(Prediccion.id_prediccion >= 10).all():
        row.ruta_audio_prueba = 'local_predictions/1/invalid'
    test_db.commit()
    sparse = client.get('/api/inference/history?model_id=301', headers=history_rows[1])
    assert sparse.json() == {'items': [], 'next_cursor': 31}
    continued = client.get('/api/inference/history?model_id=301&cursor=31', headers=history_rows[1])
    assert [row['id'] for row in continued.json()['items']] == [2, 1]
    assert continued.json()['next_cursor'] is None


def test_history_rejects_inconsistent_dataset_ownership(client, test_db, history_rows):
    dataset = test_db.get(ImportedDataset, 'a' * 32)
    dataset.owner_id = 2
    test_db.commit()
    response = client.get('/api/inference/history?model_id=301', headers=history_rows[1])
    assert response.status_code == 404
    assert response.json() == {'detail': 'Modelo no disponible.'}


@pytest.fixture
def web_history(client, test_db, history_rows, monkeypatch):
    from app.models.user import Usuario
    from app.services import auth
    monkeypatch.setenv('FAMA_WEB_ORIGIN', 'http://localhost:3000')
    monkeypatch.setenv('FAMA_ALLOW_INSECURE_LOOPBACK', '1')
    monkeypatch.setenv('FAMA_RATE_LIMIT_KEY', 'synthetic-history-rate-key-isolated-only')
    test_db.get(Usuario, 1).password_hash = auth.hash_password('SyntheticPass123!')
    test_db.commit()
    response = client.post('/api/auth/web/login', headers={'Origin': 'http://localhost:3000'},
        json={'email': 'owner1@example.test', 'password': 'SyntheticPass123!'})
    assert response.status_code == 200, response.text
    return history_rows


def test_private_history_accepts_existing_web_cookie_and_keeps_it_private(client, web_history):
    response = client.get('/api/inference/history?model_id=301')
    assert response.status_code == 200, response.text
    assert [row['id'] for row in response.json()['items']] == [2, 1]
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/api/auth/web/logout', headers={'Origin': 'http://localhost:3000'}).status_code == 204
    assert client.get('/api/inference/history?model_id=301').status_code == 401


@pytest.mark.parametrize('credential', ['invalid', 'foreign', 'foreign_origin', 'bad_cookie'])
def test_history_never_falls_back_from_conflicting_or_invalid_credentials(client, web_history, credential):
    headers = {}
    if credential == 'invalid':headers['Authorization'] = 'Bearer invalid'
    if credential == 'foreign':headers = web_history[2]
    if credential == 'foreign_origin':headers['Origin'] = 'https://foreign.example.test'
    if credential == 'bad_cookie':
        client.cookies.clear()
        client.cookies.set('fama_session_dev', 'x' * 43)
        headers = web_history[1]
    response = client.get('/api/inference/history?model_id=301', headers=headers)
    assert response.status_code == (403 if credential == 'foreign_origin' else 401), response.text
    assert 'call-2.wav' not in response.text
