"""Composition publication and execution use real persisted synthetic authority."""
import pytest
from tests.test_imported_triad_evaluation import bound, synthetic_audio, database_snapshot
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort
from tests.test_imported_triad_records import service
from app.services.registry import ModelRegistry, ModelNotFoundError


@pytest.fixture(autouse=True)
def usable_synthetic_checkpoints(monkeypatch):
    from tests import test_imported_training_evaluation as fixtures
    original = fixtures.checkpoint_payload
    monkeypatch.setattr(fixtures, 'checkpoint_payload',
        lambda: {**original(), 'synthetic_padding': 'x' * 12000})


def test_owner_publication_retains_instance_and_joint_pair(bound):
    records = service(bound)
    saved = records.create(1, bound[4]['id'])
    key = saved['predictor'].model_id
    registry = ModelRegistry(triad_records=records)
    before = database_snapshot(bound[0])
    with bound[0]() as db:
        pairs = {}
        registry.publish_from_db(db, bound[3], pairs, owner_id=1)
        predictor = registry.get(key, owner_id=1)
        assert predictor.metadata.checkpoint_sha256 == bound[4]['id']
        assert pairs[key] == saved['pair_ids']
        registry.publish_from_db(db, bound[3], pairs, owner_id=1)
        assert registry.get(key, owner_id=1) is predictor
        assert registry.get_default_model_id() is None
        for owner in (None, 2):
            with pytest.raises(ModelNotFoundError):
                registry.get(key, owner_id=owner)
        for alias in (str(saved['model'].id_modelo), bound[4]['id'], bound[4]['id'] + '.json'):
            with pytest.raises(ModelNotFoundError):
                registry.get(alias, owner_id=1)
    assert database_snapshot(bound[0]) == before


@pytest.fixture
def http(bound, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tests.test_api_model_catalogue import main
    from app.database import get_db
    from app.models import web_session, access_quota, security_audit
    from app.models.user import Usuario
    from app.services import auth
    from app.services.registry import get_model_registry
    from app.schemas.model_info import ModelListResponse
    from tests.test_model_registry import FakeAudioPredictor
    monkeypatch.setattr(auth, 'SECRET_KEY', 'synthetic-triad-registry-signing-key-2026')
    with bound[0].begin() as db:
        for uid in (1, 2):
            db.add(Usuario(id=uid, email=f'triad{uid}@example.test', password_hash='unused',
                nombre_completo='Synthetic', rol='investigador', activo=True))
    records = service(bound)
    saved = records.create(1, bound[4]['id'])
    registry = ModelRegistry(triad_records=records)
    registry.register(FakeAudioPredictor('ordinary', 'Ordinary'), is_default=True)
    monkeypatch.setattr(main.training_service, 'checkpoints_dir', bound[3])
    audio_root = tmp_path / 'private-audio'
    audio_root.mkdir(mode=0o700)
    monkeypatch.setattr(main.feedback_service, 'import_root', audio_root)
    app = FastAPI()
    app.add_api_route('/api/models', main.list_models, methods=['GET'], response_model=ModelListResponse)
    app.add_api_route('/api/predict', main.predict_audio, methods=['POST'])
    def database():
        with bound[0]() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_model_registry] = lambda: registry
    headers = lambda uid: {'Authorization': 'Bearer ' + auth.create_access_token({'sub': str(uid)})}
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, registry, saved, headers


def test_cold_owner_inference_is_one_composition_result(http, bound):
    from app.models.prediction import Prediccion
    from tests.test_imported_dataset_preparation import wav_bytes as synthetic_wav
    client, registry, saved, headers = http
    key = saved['predictor'].model_id
    response = client.post('/api/predict?model_id=' + key, headers=headers(1),
        files={'file': ('synthetic.wav', synthetic_wav(7), 'audio/wav')})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['modelo_id'] == key and result['gcp_upload'] is False
    assert result['clase'] == 'zebra' and result['confianza'] == pytest.approx(0.78)
    assert result['detalles']['loaded_checkpoint_sha256s'] == [c['checkpoint_sha256']
        for c in bound[4]['manifest']['components']]
    assert result['detalles']['composition_sha256'] == bound[4]['id']
    assert result['detalles']['weights'] == [0.1, 0.4, 0.5]
    assert result['detalles']['component_ids'] == [f"fama_trained_model_{c['model_id']}"
        for c in bound[4]['manifest']['components']]
    with bound[0]() as db:
        rows = db.query(Prediccion).all()
        assert len(rows) == 1 and rows[0].modelo_id == key
    assert registry.get_default_model_id() == 'ordinary'


def test_catalogue_versions_include_pending_rows_and_compare_ordered_components(http, bound, monkeypatch, tmp_path):
    from app.models.dataset_import import ImportedDataset
    from app.models.training import Modelo
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.services.registry import get_model_registry

    client, registry, saved, headers = http
    records = registry.triad_records
    pending = records.revise_weights(1, saved['model'].id_modelo, [0.2, 0.3, 0.5])
    revised = records.revise_weights(1, saved['model'].id_modelo, [0.4, 0.3, 0.3])
    reordered = bound[1].create(1, list(reversed(bound[4]['manifest']['components'])), [0.1, 0.4, 0.5])
    trained = records.create(1, reordered['id'])
    with bound[0].begin() as db:
        db.get(ImportedDataset, bound[4]['manifest']['cohort']['dataset_id']).name = 'Birds'
        db.get(Modelo, pending['model'].id_modelo).estado = 'imported_triad_pending'

    def forbidden(*args, **kwargs):
        pytest.fail('catalogue must not load neural weights or reevaluate compositions')
    monkeypatch.setattr(TrainedModelPredictor, 'load_weights', forbidden)
    monkeypatch.setattr(records.evaluation, 'evaluate', forbidden)
    for _ in range(2):
        response = client.get('/api/models?private_only=true', headers=headers(1))
        assert response.status_code == 200, response.text
        models = {m['id']: m for m in response.json()['models'] if m['architecture'] == 'ImportedTriad'}
        original = models[saved['predictor'].model_id]
        revision = models[revised['predictor'].model_id]
        new_training = models[trained['predictor'].model_id]
        assert original['name'] == 'Birds · Tríada v1'
        assert revision['name'] == 'Birds · Tríada v3'
        assert new_training['name'] == 'Birds · Tríada v4'
        assert pending['predictor'].model_id not in models
        assert original['metrics']['triad_version'] == 1
        assert revision['metrics']['triad_version'] == 3
        assert revision['metrics']['same_components_as_version'] == 1
        assert not original['metrics'].get('same_components_as_version')
        assert not new_training['metrics'].get('same_components_as_version')
        # A new registry instance must derive the same identities, not count the visible cache.
        registry = ModelRegistry(triad_records=records)
        client.app.dependency_overrides[get_model_registry] = lambda: registry

    # A missing/corrupt earlier descriptor cannot be silently skipped: its
    # dataset is unknown, so later versions must lose unprovable claims.
    descriptor = bound[1].root / (pending['model'].hash_binario + '.json')
    assert not descriptor.is_symlink()
    assert descriptor.resolve(strict=True).is_relative_to(tmp_path.resolve(strict=True))
    original_mode = descriptor.stat().st_mode & 0o777
    descriptor.chmod(0o600)
    try:
        descriptor.write_bytes(b'corrupt synthetic descriptor')
    finally:
        descriptor.chmod(original_mode)
    response = client.get('/api/models?private_only=true', headers=headers(1))
    assert response.status_code == 200, response.text
    models = {m['id']: m for m in response.json()['models'] if m['architecture'] == 'ImportedTriad'}
    assert models[saved['predictor'].model_id]['name'] == 'Birds · Tríada v1'
    for key in (revised['predictor'].model_id, trained['predictor'].model_id):
        assert models[key]['name'] == 'Tríada importada'
        assert 'triad_version' not in models[key]['metrics']
        assert 'same_components_as_version' not in models[key]['metrics']


def test_owner_catalogue_has_actual_joint_reports_and_no_foreign_discovery(http, bound):
    client, registry, saved, headers = http
    key = saved['predictor'].model_id
    owner = client.get('/api/models?private_only=true', headers=headers(1))
    assert owner.status_code == 200, owner.text
    compositions = [m for m in owner.json()['models'] if m['id'] == key]
    assert len(compositions) == 1
    item = compositions[0]
    assert item['has_weights'] is True and item['architecture'] == 'ImportedTriad'
    assert 'epochs' not in item['metrics']
    assert item['metrics']['weights'] == [0.1, 0.4, 0.5]
    assert item['metrics']['components'] == bound[4]['manifest']['components']
    for index, split in enumerate(('val', 'test')):
        admitted = item['evaluations'][split]['admitted_completed']
        assert admitted['id_evaluation'] == saved['pair_ids'][index]
        assert admitted['report']['confusion_matrix'] == [[0, 1, 0], [0, 1, 0]]
        assert admitted['provenance']['checkpoint_sha256'] == bound[4]['id']
    for response in (client.get('/api/models'),
                     client.get('/api/models?private_only=true', headers=headers(2))):
        assert response.status_code == 200
        assert key not in response.text and bound[4]['id'] not in response.text
        assert 'Tríada importada' not in response.text
    assert client.get('/api/models?private_only=true').status_code == 401
    from tests.test_imported_dataset_preparation import wav_bytes as synthetic_wav
    for alias in (key, str(saved['model'].id_modelo), bound[4]['id'], bound[4]['id'] + '.json'):
        for uid in (1, 2):
            if alias == key and uid == 1:
                continue
            denied = client.post('/api/predict?model_id=' + alias, headers=headers(uid),
                files={'file': ('synthetic.wav', synthetic_wav(7), 'audio/wav')})
            assert denied.status_code == 404, denied.text
            assert bound[4]['id'] not in denied.text
    assert registry.get_default_model_id() == 'ordinary'


@pytest.mark.parametrize('damage', ['association', 'bytes', 'report', 'marker', 'pending', 'owner'])
def test_cached_composition_invalidates_without_retiring_valid_components(bound, damage):
    from app.models.training import Modelo, ModelEvaluation
    from app.models.imported_training_source import ImportedModelSource
    records = service(bound)
    saved = records.create(1, bound[4]['id'])
    registry = ModelRegistry(triad_records=records)
    with bound[0]() as db:
        registry.publish_from_db(db, bound[3], owner_id=1)
    key = saved['predictor'].model_id
    cached = registry.get(key, owner_id=1)
    component = registry.get('fama_trained_model_1', owner_id=1)
    # Exercise loaded, not just lazy, composites before damaging authority.
    cached.load_weights()
    with bound[0].begin() as db:
        if damage == 'association':
            db.get(ImportedModelSource, 3).owner_id = 2
        elif damage == 'bytes':
            path = bound[3] / 'component-2.pt'
            path.write_bytes(path.read_bytes() + b'drift')
        elif damage == 'report':
            db.get(ModelEvaluation, saved['pair_ids'][1]).report = {}
        elif damage == 'marker':
            db.get(Modelo, saved['model'].id_modelo).arquitectura = 'AudioCNN'
        elif damage == 'pending':
            db.get(Modelo, saved['model'].id_modelo).estado = 'imported_triad_pending'
        elif damage == 'owner':
            db.get(Modelo, saved['model'].id_modelo).id_usuario = 2
    before = database_snapshot(bound[0])
    with bound[0]() as db:
        registry.publish_from_db(db, bound[3], owner_id=2 if damage == 'owner' else 1)
    with pytest.raises(ModelNotFoundError):
        registry.get(key, owner_id=1)
    assert key not in {m.id for m in registry.list_models(owner_id=2)}
    assert registry.get('fama_trained_model_1', owner_id=1) is component
    assert registry.get_default_model_id() is None
    assert database_snapshot(bound[0]) == before


def test_restart_prewarm_is_metadata_only_and_fresh_publication_is_lazy(bound, monkeypatch):
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    records = service(bound)
    saved = records.create(1, bound[4]['id'])
    def forbidden(*args, **kwargs):
        pytest.fail('readers must not load neural weights, evaluate or iterate audio')
    monkeypatch.setattr(TrainedModelPredictor, 'load_weights', forbidden)
    monkeypatch.setattr(records.evaluation, 'evaluate', forbidden)
    monkeypatch.setattr(records.evaluation.sources.preparations.snapshots, 'iter_verified', forbidden)
    before = database_snapshot(bound[0])
    registry = ModelRegistry(triad_records=service(bound))
    with bound[0]() as db:
        assert registry.prewarm_from_db(db, bound[3]) == 0
        assert registry.list_models(owner_id=1) == []
        registry.publish_from_db(db, bound[3], owner_id=1)
    pred = registry.get(saved['predictor'].model_id, owner_id=1)
    assert all(p.model is None for p in pred.components)
    with pytest.raises(ValueError):
        ModelRegistry().register(saved['predictor'])
    assert registry.get_default_model_id() is None
    assert database_snapshot(bound[0]) == before


def test_lazy_configured_factory_uses_existing_private_preparation_child(bound, monkeypatch):
    from app import database
    from app.services.imported_triad_manifests import ImportedTriadManifests
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation
    from app.services.imported_triad_records import ImportedTriadRecords
    sources = bound[2]
    monkeypatch.setattr(database, 'SessionLocal', bound[0])
    for name, root in (
        ('FAMA_IMPORT_ROOT', sources.preparations.snapshots.source.root),
        ('FAMA_TRAINING_SNAPSHOT_ROOT', sources.preparations.snapshots.root),
        ('FAMA_IMPORTED_PREPARED_ROOT', sources.preparations.root)):
        monkeypatch.setenv(name, str(root))
    root = sources.preparations.root / 'triad-manifests'
    # A reader must not create an empty composition store as a side effect.
    existing = service(bound).create(1, bound[4]['id'])
    registry = ModelRegistry()
    with bound[0]() as db:
        registry.publish_from_db(db, bound[3], owner_id=1)
    assert not root.exists()
    with pytest.raises(ModelNotFoundError):
        registry.get(existing['predictor'].model_id, owner_id=1)
    manifests = ImportedTriadManifests(root)
    revision = manifests.create(1, bound[4]['manifest']['components'], [0.2, 0.3, 0.5])
    records = ImportedTriadRecords(bound[0], manifests,
        ImportedTriadEvaluation(bound[0], manifests, sources, bound[3]))
    saved = records.create(1, revision['id'])
    restarted = ModelRegistry()
    with bound[0]() as db:
        restarted.publish_from_db(db, bound[3], owner_id=1)
    assert restarted.get(saved['predictor'].model_id, owner_id=1).metadata.checkpoint_sha256 == revision['id']


def test_catalogue_during_leased_forward_retains_predictor_and_execution_slot(bound, monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.services.inference_execution import InferenceExecution
    from app.services.predictors import trained_predictor
    from tests.test_imported_dataset_preparation import wav_bytes as synthetic_wav
    records = service(bound)
    saved = records.create(1, bound[4]['id'])
    registry = ModelRegistry(triad_records=records)
    with bound[0]() as db:
        registry.publish_from_db(db, bound[3], owner_id=1)
    predictor = registry.get(saved['predictor'].model_id, owner_id=1)
    started, resume = Event(), Event()
    original = trained_predictor.AudioCNN.forward
    def forward(neural, audio):
        started.set()
        assert resume.wait(5), 'catalogue blocked behind neural forward'
        return original(neural, audio)
    monkeypatch.setattr(trained_predictor.AudioCNN, 'forward', forward)
    execution = InferenceExecution()
    lease = execution.acquire()
    def predict():
        try:
            return asyncio.run(lease.predict(predictor, synthetic_wav(7),
                admission=lambda: registry.readmit_composition(predictor, 1, bound[3])))
        finally:
            lease.release()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(predict)
        try:
            assert started.wait(5)
            assert execution.acquire() is None
            with bound[0]() as db:
                registry.publish_from_db(db, bound[3], owner_id=1)
            assert registry.get(predictor.model_id, owner_id=1) is predictor
        finally:
            resume.set()
        assert future.result(timeout=5).detalles['model_id'] == predictor.model_id
    next_lease = execution.acquire()
    assert next_lease is not None
    next_lease.release()


@pytest.mark.parametrize('damage', ['association', 'report', 'sha'])
def test_http_rechecks_authority_after_validation_before_forward(http, bound, monkeypatch, damage):
    from tests.test_api_model_catalogue import main
    from tests.test_imported_dataset_preparation import wav_bytes as synthetic_wav
    from app.models.training import Modelo, ModelEvaluation
    from app.models.imported_training_source import ImportedModelSource
    from app.models.prediction import Prediccion
    client, registry, saved, headers = http
    key = saved['predictor'].model_id
    files = {'file': ('synthetic.wav', synthetic_wav(7), 'audio/wav')}
    first = client.post('/api/predict?model_id=' + key, headers=headers(1), files=files)
    assert first.status_code == 200, first.text
    original = main.validate_audio
    def validate_then_invalidate(audio):
        original(audio)
        with bound[0].begin() as db:
            if damage == 'association':
                db.get(ImportedModelSource, 3).owner_id = 2
            elif damage == 'report':
                db.get(ModelEvaluation, saved['pair_ids'][1]).report = {}
            else:
                db.get(Modelo, 3).hash_binario = 'f' * 64
    monkeypatch.setattr(main, 'validate_audio', validate_then_invalidate)
    denied = client.post('/api/predict?model_id=' + key, headers=headers(1), files=files)
    assert denied.status_code == 503, denied.text
    assert 'Composición importada no disponible.' in denied.text
    assert str(bound[3]) not in denied.text
    with bound[0]() as db:
        assert db.query(Prediccion).count() == 1
    with pytest.raises(ModelNotFoundError):
        registry.get(key, owner_id=1)
    assert registry.get_default_model_id() == 'ordinary'


@pytest.mark.parametrize('failure,status', [('weights', 503), ('runtime', 500)])
def test_composition_neural_failure_is_private_and_does_not_write_history(http, bound, monkeypatch, failure, status):
    from app.services.predictors import trained_predictor
    from app.services.predictors.base import ModelWeightsError
    from app.models.prediction import Prediccion
    from tests.test_imported_dataset_preparation import wav_bytes
    client, registry, saved, headers = http
    def fail(neural, audio):
        error = ModelWeightsError if failure == 'weights' else RuntimeError
        raise error('/private/synthetic-component/checkpoint.pt')
    monkeypatch.setattr(trained_predictor.AudioCNN, 'forward', fail)
    response = client.post('/api/predict?model_id=' + saved['predictor'].model_id,
        headers=headers(1), files={'file': ('synthetic.wav', wav_bytes(7), 'audio/wav')})
    assert response.status_code == status
    assert response.json() == {'detail': 'Composición importada no disponible.'}
    assert '/private/synthetic-component/checkpoint.pt' not in response.text
    with bound[0]() as db:
        assert db.query(Prediccion).count() == 0
    assert registry.get_default_model_id() == 'ordinary'


def test_lease_rejects_lost_authority_after_publication(bound):
    import asyncio
    from app.models.training import ModelEvaluation
    from app.services.inference_execution import InferenceExecution
    from app.services.predictors.base import ModelWeightsError
    records = service(bound)
    saved = records.create(1, bound[4]['id'])
    registry = ModelRegistry(triad_records=records)
    with bound[0]() as db:
        registry.publish_from_db(db, bound[3], owner_id=1)
    predictor = registry.get(saved['predictor'].model_id, owner_id=1)
    with bound[0].begin() as db:
        db.get(ModelEvaluation, saved['pair_ids'][1]).report = {}
    lease = InferenceExecution().acquire()
    try:
        with pytest.raises(ModelWeightsError):
            asyncio.run(lease.predict(predictor, b'not even audio',
                admission=lambda: registry.readmit_composition(predictor, 1, bound[3])))
    finally:
        lease.release()
    with pytest.raises(ModelNotFoundError):
        registry.get(predictor.model_id, owner_id=1)
