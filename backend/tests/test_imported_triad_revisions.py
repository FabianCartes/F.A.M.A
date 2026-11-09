"""Weights-only revision of an admitted composition through the public service seam."""
import pytest
from tests.test_imported_triad_evaluation import bound, synthetic_audio, database_snapshot
from tests.test_imported_triad_records import service
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort

UNAVAILABLE = 'Composición importada no disponible'


def test_new_weights_create_new_version_and_keep_old_untouched(bound, monkeypatch):
    records = service(bound)
    first = records.create(1, bound[4]['id'])
    old = database_snapshot(bound[0])
    def forbidden(*args, **kwargs):
        raise AssertionError('revision must not prepare')
    monkeypatch.setattr(bound[2].preparations, 'create', forbidden)
    second = service(bound).revise_weights(1, first['model'].id_modelo, [1, 0, 0])
    assert second['model'].id_modelo != first['model'].id_modelo
    assert second['manifest']['weights'] == [1, 0, 0]
    assert second['manifest']['components'] == first['manifest']['components']
    assert second['pair_ids'] != first['pair_ids'] and not second['model'].activo
    now = database_snapshot(bound[0])
    for table, rows in old.items():
        assert now[table][:len(rows)] == rows
    again = service(bound).read_admitted(1, first['model'].id_modelo)
    assert again['pair_ids'] == first['pair_ids'] and again['manifest'] == first['manifest']
    assert bound[1].get(1, bound[4]['id'])['manifest'] == first['manifest']
    from app.models.training import ModelEvaluation
    with bound[0]() as db:
        report = db.get(ModelEvaluation, second['pair_ids'][1]).report
        assert report['confusion_matrix'] == [[1, 0, 0], [1, 0, 0]]


def test_identical_weights_are_idempotent(bound):
    records = service(bound)
    first = records.create(1, bound[4]['id'])
    before = database_snapshot(bound[0])
    same = service(bound).revise_weights(1, first['model'].id_modelo, [0.1, 0.4, 0.5])
    assert same['model'].id_modelo == first['model'].id_modelo
    assert database_snapshot(bound[0]) == before


@pytest.mark.parametrize('weights', [[1, 0], [0, 0, 0], [-0.1, 0.6, 0.5], [0.5, 0.5, 0.5],
    [float('nan'), 0.5, 0.5], [float('inf'), 0, 0], [True, 0, 0], 'abc', None, [0.2, 0.2, 0.5]])
def test_invalid_weights_fail_closed_without_side_effects(bound, weights):
    from app.services.imported_triad_evaluation import ImportedTriadEvaluationError
    first = service(bound).create(1, bound[4]['id'])
    before = database_snapshot(bound[0])
    with pytest.raises(ImportedTriadEvaluationError, match=UNAVAILABLE):
        service(bound).revise_weights(1, first['model'].id_modelo, weights)
    assert database_snapshot(bound[0]) == before


@pytest.mark.parametrize('case', ['foreign', 'missing', 'pending', 'third_owner'])
def test_unadmitted_sources_fail_closed_without_side_effects(bound, case):
    from app.models.training import Modelo
    from app.models.imported_training_source import ImportedModelSource
    from app.services.imported_triad_evaluation import ImportedTriadEvaluationError
    first = service(bound).create(1, bound[4]['id'])
    key = first['model'].id_modelo
    with bound[0].begin() as db:
        if case == 'pending':
            db.get(Modelo, key).estado = 'imported_triad_pending'
        elif case == 'third_owner':
            db.get(ImportedModelSource, first['manifest']['components'][2]['model_id']).owner_id = 2
    before = database_snapshot(bound[0])
    owner, target = (2, key) if case == 'foreign' else (1, 99999 if case == 'missing' else key)
    with pytest.raises(ImportedTriadEvaluationError, match=UNAVAILABLE):
        service(bound).revise_weights(owner, target, [1, 0, 0])
    assert database_snapshot(bound[0]) == before


def test_owner_catalogue_lists_both_versions_privately(bound):
    from app.models.training import ModelEvaluation
    from app.services.registry import ModelRegistry, ModelNotFoundError
    records = service(bound)
    first = records.create(1, bound[4]['id'])
    second = records.revise_weights(1, first['model'].id_modelo, [1, 0, 0])
    keys = [first['predictor'].model_id, second['predictor'].model_id]
    registry = ModelRegistry(triad_records=records)
    pairs = {}
    with bound[0]() as db:
        registry.publish_from_db(db, bound[3], pairs, owner_id=1)
        owner = {m.id: m for m in registry.list_models(owner_id=1, private_only=True)}
        assert set(keys) <= set(owner) and keys[0] != keys[1]
        assert pairs[keys[0]] == first['pair_ids'] and pairs[keys[1]] == second['pair_ids']
        assert tuple(registry.get(keys[0], owner_id=1).weights) == (0.1, 0.4, 0.5)
        assert tuple(registry.get(keys[1], owner_id=1).weights) == (1, 0, 0)
        for key, matrix, saved in ((keys[0], [[0, 1, 0], [0, 1, 0]], first),
                                   (keys[1], [[1, 0, 0], [1, 0, 0]], second)):
            assert owner[key].checkpoint_sha256 == saved['model'].hash_binario
            for attempt_id in pairs[key]:
                assert db.get(ModelEvaluation, attempt_id).report['confusion_matrix'] == matrix
        for who in (2, None):
            registry.publish_from_db(db, bound[3], {}, owner_id=who)
            assert not set(keys) & {m.id for m in registry.list_models(owner_id=who)}
            assert not set(keys) & {m.id for m in registry.list_models(owner_id=who, private_only=True)}
            for alias in keys + [str(first['model'].id_modelo), str(second['model'].id_modelo),
                                 first['model'].hash_binario, second['model'].hash_binario]:
                with pytest.raises(ModelNotFoundError):
                    registry.get(alias, owner_id=who)
        assert registry.get_default_model_id() is None
