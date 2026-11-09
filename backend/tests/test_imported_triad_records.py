"""Durable joint evaluation through the public persistence/readmission seam."""
import pytest
from tests.test_imported_triad_evaluation import bound, synthetic_audio, database_snapshot
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort


def service(bound):
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation
    from app.services.imported_triad_records import ImportedTriadRecords
    sessions, manifests, sources, root, *_ = bound
    return ImportedTriadRecords(sessions, manifests,
        ImportedTriadEvaluation(sessions, manifests, sources, root))


def test_persist_actual_joint_pair_and_readmit_after_restart(bound, monkeypatch):
    from app.models.training import Modelo, ModelEvaluation
    records = service(bound)
    saved = records.evaluate_and_persist(1, bound[4]['id'])
    key = saved['model'].id_modelo
    assert saved['predictor'].model_id == f'fama_trained_model_{key}'
    assert saved['manifest'] == bound[4]['manifest']
    with bound[0]() as db:
        model = db.get(Modelo, key)
        assert model.arquitectura == 'ImportedTriad'
        assert model.estado == 'imported_triad_evaluated'
        assert model.id_usuario == 1 and model.id_conjunto_datos is None
        assert model.hash_binario == bound[4]['id'] and model.tamano_bytes > 0
        assert not model.activo and model.precision is None and model.perdida is None
        assert (model.epocas, model.tasa_aprendizaje, model.tamano_lote) == (0, 0, 0)
        rows = db.query(ModelEvaluation).filter_by(id_modelo=key).all()
        assert len(rows) == 2
        assert {r.id_evaluation for r in rows} == set(saved['pair_ids'])
        for row in rows:
            assert row.status == 'completed'
            assert row.report['confusion_matrix'] == [[0, 1, 0], [0, 1, 0]]
            assert row.checkpoint_sha256 == bound[4]['id']
            assert row.predictor_config['weights'] == [0.1, 0.4, 0.5]
    fresh = service(bound)
    def forbidden(*args, **kwargs):
        raise AssertionError('readmission must not evaluate/capture audio/load neural weights')
    monkeypatch.setattr(fresh.evaluation, 'evaluate', forbidden)
    monkeypatch.setattr(fresh.evaluation.sources, 'resolve_triad', forbidden)
    monkeypatch.setattr(fresh.evaluation.sources.preparations.snapshots, 'iter_verified', forbidden)
    from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    import app.services.imported_triad_evaluation as joint
    monkeypatch.setattr(joint, 'evaluation_recordings', forbidden)
    monkeypatch.setattr(ImportedTriadPredictor, 'load_weights', forbidden)
    monkeypatch.setattr(TrainedModelPredictor, 'load_weights', forbidden)
    monkeypatch.setattr(TrainedModelPredictor, 'predict', forbidden)
    before = database_snapshot(bound[0])
    reread = fresh.read_admitted(1, key)
    assert reread['pair_ids'] == saved['pair_ids']
    assert reread['provenance'] == saved['provenance']
    assert fresh.create(1, bound[4]['id'])['model'].id_modelo == key
    assert database_snapshot(bound[0]) == before


@pytest.mark.parametrize('damage', ['foreign', 'owner', 'third_owner', 'third_hash',
    'path', 'size', 'hash', 'marker', 'joint_cohort', 'joint_weights', 'joint_report',
    'incomplete', 'third_report', 'third_bytes', 'extra_attempt'])
def test_readmission_rejects_tampered_authority_without_writes(bound, damage):
    from app.models.training import Modelo, ModelEvaluation
    from app.models.imported_training_source import ImportedModelSource
    from app.services.imported_triad_evaluation import ImportedTriadEvaluationError
    records = service(bound)
    saved = records.create(1, bound[4]['id'])
    key = saved['model'].id_modelo
    third = bound[4]['manifest']['components'][2]['model_id']
    with bound[0].begin() as db:
        row = db.get(Modelo, key)
        attempt = db.get(ModelEvaluation, saved['pair_ids'][1])
        if damage == 'owner':
            row.id_usuario = 2
        elif damage == 'third_owner':
            db.get(ImportedModelSource, third).owner_id = 2
        elif damage == 'third_hash':
            db.get(Modelo, third).hash_binario = 'a' * 64
        elif damage == 'path':
            row.ruta_binario_gcp = (bound[3] / (row.hash_binario + '.json')).as_uri()
        elif damage == 'size':
            row.tamano_bytes = 0
        elif damage == 'hash':
            row.hash_binario = 'a' * 64
        elif damage == 'marker':
            row.arquitectura = 'AudioCNN'
        elif damage == 'joint_cohort':
            # A self-consistent saved pair still cannot substitute a different
            # cohort for the individually admitted source pair.
            from app.services.standard_evaluation_guard import admitted_manifest_pair_provenance, ADMITTED_MANIFEST_PAIR_KEY
            pair = [db.get(ModelEvaluation, i) for i in saved['pair_ids']]
            token = admitted_manifest_pair_provenance('a' * 64, 'b' * 64)
            for index, item in enumerate(pair):
                item.manifest_sha256 = ('a' if index == 0 else 'b') * 64
                item.predictor_config = {**item.predictor_config, ADMITTED_MANIFEST_PAIR_KEY: token}
        elif damage == 'joint_weights':
            for item in db.query(ModelEvaluation).filter_by(id_modelo=key):
                item.predictor_config = {**item.predictor_config, 'weights': [1, 0, 0]}
                item.aggregation_config = {**item.aggregation_config, 'weights': [1, 0, 0]}
        elif damage == 'joint_report':
            attempt.report = {**attempt.report, 'sample_count': 999}
        elif damage == 'incomplete':
            row.estado = 'imported_triad_pending'
        elif damage == 'third_report':
            item = db.query(ModelEvaluation).filter_by(id_modelo=third, split='test').one()
            item.report = {**item.report, 'sample_count': 999}
        elif damage == 'third_bytes':
            path = bound[3] / 'component-2.pt'
            with path.open('ab') as stream:
                stream.write(b'drift')
    if damage == 'extra_attempt':
        from app.services.evaluations import EvaluationService
        with bound[0]() as db:
            EvaluationService(db).create(saved['provenance']['test'])
    before = database_snapshot(bound[0])
    for owner in ([2, 0, True] if damage == 'foreign' else [1]):
        with pytest.raises(ImportedTriadEvaluationError, match='Composición importada no disponible'):
            service(bound).read_admitted(owner, key)
    assert database_snapshot(bound[0]) == before


@pytest.mark.parametrize('damage', ['foreign', 'third_owner', 'third_size', 'third_path'])
def test_invalid_create_has_no_persistence_side_effect(bound, damage):
    from app.models.training import Modelo
    from app.models.imported_training_source import ImportedModelSource
    from app.services.imported_triad_evaluation import ImportedTriadEvaluationError
    third = bound[4]['manifest']['components'][2]['model_id']
    with bound[0].begin() as db:
        if damage == 'third_owner':
            db.get(ImportedModelSource, third).owner_id = 2
        elif damage == 'third_size':
            db.get(Modelo, third).tamano_bytes = -1
        elif damage == 'third_path':
            db.get(Modelo, third).ruta_binario_gcp = 'models/../component-2.pt'
    before = database_snapshot(bound[0])
    with pytest.raises(ImportedTriadEvaluationError):
        service(bound).create(2 if damage == 'foreign' else 1, bound[4]['id'])
    assert database_snapshot(bound[0]) == before


def test_weight_revision_is_new_immutable_record_without_training(bound, monkeypatch):
    records = service(bound)
    first = records.create(1, bound[4]['id'])
    old = database_snapshot(bound[0])
    revision = bound[1].create(1, bound[4]['manifest']['components'], [1, 0, 0])
    def forbidden(*args, **kwargs):
        raise AssertionError('weight revision must not prepare or train')
    monkeypatch.setattr(bound[2].preparations, 'create', forbidden)
    second = service(bound).create(1, revision['id'])
    assert second['model'].id_modelo != first['model'].id_modelo
    assert second['pair_ids'] != first['pair_ids']
    assert second['model'].hash_binario != first['model'].hash_binario
    now = database_snapshot(bound[0])
    for table, rows in old.items():
        assert now[table][:len(rows)] == rows
    assert service(bound).admit(1, first['model'].id_modelo)['pair_ids'] == first['pair_ids']
    with bound[0]() as db:
        from app.models.training import ModelEvaluation
        report = db.get(ModelEvaluation, second['pair_ids'][1]).report
        assert report['confusion_matrix'] == [[1, 0, 0], [1, 0, 0]]


def test_persistence_failure_keeps_pending_unavailable_and_old_pair_untouched(bound, monkeypatch):
    from sqlalchemy import event
    from app.models.training import Modelo, ModelEvaluation
    from app.services.imported_triad_evaluation import ImportedTriadEvaluationError
    records = service(bound)
    first = records.create(1, bound[4]['id'])
    old = database_snapshot(bound[0])
    revision = bound[1].create(1, bound[4]['manifest']['components'], [1, 0, 0])
    # Real persistence fault at the DB adapter, not a mocked report validator.
    def fail_test_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('UPDATE model_evaluation') and 'report=' in statement:
            raise RuntimeError('injected storage failure')
    engine = bound[0].kw['bind']
    event.listen(engine, 'before_cursor_execute', fail_test_update)
    try:
        with pytest.raises(ImportedTriadEvaluationError):
            records.create(1, revision['id'])
    finally:
        event.remove(engine, 'before_cursor_execute', fail_test_update)
    now = database_snapshot(bound[0])
    for table, rows in old.items():
        assert now[table][:len(rows)] == rows
    with bound[0]() as db:
        pending = db.query(Modelo).filter_by(hash_binario=revision['id']).one()
        key = pending.id_modelo
        assert pending.estado == 'imported_triad_pending' and not pending.activo
        assert db.query(ModelEvaluation).filter_by(id_modelo=key).one().status == 'running'
    before = database_snapshot(bound[0])
    with pytest.raises(ImportedTriadEvaluationError):
        records.admit(1, key)
    with pytest.raises(ImportedTriadEvaluationError):
        service(bound).create(1, revision['id'])
    assert database_snapshot(bound[0]) == before
    assert records.admit(1, first['model'].id_modelo)['pair_ids'] == first['pair_ids']


def test_archived_dataset_can_persist_and_readmit_historical_composition(bound, cohort):
    from app.services.imported_training_source import ImportedSourceError
    dataset = cohort[4].get('/api/ingestion/imports/datasets').json()['datasets'][0]
    response = cohort[4].request('DELETE', '/api/ingestion/imports/datasets/' + cohort[5],
        json={'revision': dataset['revision']})
    assert response.status_code == 204
    saved = service(bound).create(1, bound[4]['id'])
    assert service(bound).admit(1, saved['model'].id_modelo)['pair_ids'] == saved['pair_ids']
    options = [{'version': bound[5]['identity']['preparation_version'], 'architecture': 'AudioCNN'}] * 3
    with pytest.raises(ImportedSourceError):
        bound[2].resolve_triad_for_training(1, cohort[5], cohort[1]['id'], options)


def test_ambiguous_duplicate_composition_cannot_be_readmitted(bound):
    from app.models.training import Modelo
    from app.services.imported_triad_evaluation import ImportedTriadEvaluationError
    saved = service(bound).create(1, bound[4]['id'])
    with bound[0].begin() as db:
        row = db.get(Modelo, saved['model'].id_modelo)
        values = {c.name: getattr(row, c.name) for c in Modelo.__table__.columns if c.name != 'id_modelo'}
        db.add(Modelo(**values))
    before = database_snapshot(bound[0])
    with pytest.raises(ImportedTriadEvaluationError):
        service(bound).read_admitted(1, saved['model'].id_modelo)
    with pytest.raises(ImportedTriadEvaluationError):
        service(bound).create(1, bound[4]['id'])
    assert database_snapshot(bound[0]) == before


def test_compositions_are_omitted_by_existing_public_owner_and_foreign_catalogues(bound):
    from app.services.registry import ModelRegistry
    records = service(bound)
    saved = records.create(1, bound[4]['id'])
    alias = saved['predictor'].model_id
    for owner in (None, 1, 2):
        registry = ModelRegistry()
        with bound[0]() as db:
            errors = registry.publish_from_db(db, checkpoints_root=bound[3], owner_id=owner)
        assert not any(error.get('model_id') == alias for error in errors)
        entries = registry.list_models(owner_id=owner)
        assert alias not in {entry.id for entry in entries}
        assert all(entry.checkpoint_sha256 != bound[4]['id'] for entry in entries)
        assert registry.get_default_model_id() is None
