"""Weights-only composition revision through the public authenticated HTTP seam."""
import pytest
from tests.http_security import cookie_security  # noqa: F401 - configure the HTTP fixture in this module
from tests.test_imported_triad_evaluation import bound, synthetic_audio, database_snapshot
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort
from tests.test_imported_triad_registry import http, usable_synthetic_checkpoints  # noqa: F401

UNAVAILABLE = 'Composición importada no disponible.'


@pytest.fixture
def api(http):
    from tests.test_api_model_catalogue import main
    client, registry, saved, headers = http
    # The shared fixture mounts only catalogue/predict; add the route under test.
    client.app.add_api_route('/api/training/models/{model_id}/triad-weights',
                             main.revise_triad_weights, methods=['POST'])
    url = f'/api/training/models/{saved["model"].id_modelo}/triad-weights'
    return client, saved, headers, url, main


def listed(client, headers, uid):
    response = client.get('/api/models?private_only=true', headers=headers(uid))
    assert response.status_code == 200, response.text
    return {m['id']: m for m in response.json()['models']}


def test_owner_revises_and_new_version_is_listed_for_owner_only(api, bound):
    client, saved, headers, url, _ = api
    response = client.post(url, json={'weights': [1, 0, 0]}, headers=headers(1))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['weights'] == [1.0, 0.0, 0.0] and body['id'] != saved['predictor'].model_id
    assert body['name'] == 'Tríada importada'
    owner = listed(client, headers, 1)
    assert {body['id'], saved['predictor'].model_id} <= set(owner)
    assert owner[body['id']]['metrics']['weights'] == [1, 0, 0]
    assert body['id'] not in listed(client, headers, 2)
    assert body['id'] not in client.get('/api/models').text


def test_equivalent_int_and_float_weights_are_one_version(api, bound):
    client, saved, headers, url, _ = api
    first = client.post(url, json={'weights': [1, 0, 0]}, headers=headers(1)).json()
    before = database_snapshot(bound[0])
    second = client.post(url, json={'weights': [1.0, 0.0, 0.0]}, headers=headers(1))
    assert second.status_code == 200 and second.json() == first
    assert database_snapshot(bound[0]) == before


@pytest.mark.parametrize('weights', [[1, 0], [0.5, 0.5, 0, 0], [-0.1, 0.6, 0.5], [0.5, 0.5, 0.5],
    [0, 0, 0], [True, 0, 0], ['a', 0, 0], 'abc', None, [None, 0, 1]])
def test_invalid_weights_are_422_without_side_effects(api, bound, weights):
    client, _, headers, url, _ = api
    before = database_snapshot(bound[0])
    response = client.post(url, json={'weights': weights}, headers=headers(1))
    assert response.status_code == 422
    assert database_snapshot(bound[0]) == before


def test_owner_is_never_taken_from_the_body(api, bound):
    client, _, headers, url, _ = api
    before = database_snapshot(bound[0])
    response = client.post(url, json={'weights': [1, 0, 0], 'owner_id': 1}, headers=headers(2))
    assert response.status_code == 422  # an owner field is rejected, never honoured
    assert database_snapshot(bound[0]) == before


def test_unauthenticated_and_foreign_requests_are_denied_without_changes(api, bound):
    client, saved, headers, url, _ = api
    before = database_snapshot(bound[0])
    assert client.post(url, json={'weights': [1, 0, 0]}).status_code == 401
    foreign = client.post(url, json={'weights': [1, 0, 0]}, headers=headers(2))
    assert foreign.status_code == 404 and foreign.json()['detail'] == UNAVAILABLE
    assert bound[4]['id'] not in foreign.text
    assert database_snapshot(bound[0]) == before


@pytest.mark.parametrize('case', ['missing', 'component', 'pending'])
def test_non_composition_and_pending_are_uniform_errors(api, bound, case):
    from app.models.training import Modelo
    client, saved, headers, url, _ = api
    target = url
    if case == 'missing':
        target = url.replace(f'/models/{saved["model"].id_modelo}/', '/models/99999/')
    elif case == 'component':
        target = url.replace(f'/models/{saved["model"].id_modelo}/',
                             f'/models/{saved["manifest"]["components"][0]["model_id"]}/')
    else:
        with bound[0].begin() as db:
            db.get(Modelo, saved['model'].id_modelo).estado = 'imported_triad_pending'
    before = database_snapshot(bound[0])
    response = client.post(target, json={'weights': [1, 0, 0]}, headers=headers(1))
    assert response.status_code == 404 and response.json()['detail'] == UNAVAILABLE
    assert database_snapshot(bound[0]) == before


def test_active_training_blocks_revision_without_changes(api, bound, monkeypatch):
    client, _, headers, url, main = api
    monkeypatch.setattr(main.training_service, 'status', 'training')
    before = database_snapshot(bound[0])
    response = client.post(url, json={'weights': [1, 0, 0]}, headers=headers(1))
    assert response.status_code == 409
    assert database_snapshot(bound[0]) == before


def test_evaluation_runs_without_the_registry_publication_lock(api, bound, monkeypatch):
    from app.services.imported_triad_records import ImportedTriadRecords as Records
    client, saved, headers, url, _ = api
    original = Records.revise_weights
    held = []
    def spy(self, *args, **kwargs):
        registry = client.app.dependency_overrides
        from app.services.registry import get_model_registry
        reg = registry[get_model_registry]()
        held.append(reg._publication_lock._is_owned())
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Records, 'revise_weights', spy)
    assert client.post(url, json={'weights': [1, 0, 0]}, headers=headers(1)).status_code == 200
    assert held == [False]


def test_individual_catalogue_is_unchanged_by_revision(api, bound):
    client, saved, headers, url, _ = api
    before = {k: v for k, v in listed(client, headers, 1).items() if k != saved['predictor'].model_id}
    client.post(url, json={'weights': [1, 0, 0]}, headers=headers(1))
    after = listed(client, headers, 1)
    assert all(after[k] == v for k, v in before.items())
