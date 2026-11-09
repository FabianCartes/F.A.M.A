"""Automatic imported completion uses real DB admission and joint CPU reports."""
import pytest

from tests.test_imported_training_triad import triad
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create
from tests.test_training_flow import training_env
from tests.test_training_persistence import persistence_env, start as start_legacy


def inline(training_env):
    class Inline:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    training_env[3].side_effect = Inline


def test_completion_persists_own_pair_and_fresh_owner_catalog(triad, training_env):
    from app.models.training import Modelo, ModelEvaluation
    from app.services.registry import ModelRegistry, ModelNotFoundError
    runtime, arguments, _ = triad
    inline(training_env)
    phases = []
    runtime._progress_callback = lambda snapshot: phases.append(snapshot)
    runtime.start_training(**arguments)
    progress = runtime.get_progress(owner_id=1)
    assert progress['status'] == 'completed', progress
    assert progress['ensemble_available'] is True, progress
    assert progress['current_phase'] == 'completed'
    assert any(s['current_phase'] == 'joint_evaluation' and not s['ensemble_available'] for s in phases)
    key = progress['composition_model_id']
    sha = progress['composition_sha256']
    admitted = runtime.triad_records.read_admitted(1, key)
    assert admitted['model'].hash_binario == sha
    assert admitted['manifest']['weights'] == [0.2, 0.3, 0.5]
    assert admitted['manifest']['components'] == [dict(model_id=c['model_id'],
        checkpoint_sha256=c['sha256'], imported_source=c['source'])
        for c in progress['component_results']]
    with runtime.triad_records.sessions() as db:
        assert db.query(Modelo).count() == 4
        reports = db.query(ModelEvaluation).all()
        assert len(reports) == 8
        assert all(r.status == 'completed' for r in reports)
        assert not any(m.activo for m in db.query(Modelo).all())
        own = [r for r in reports if r.id_modelo == key]
        assert {r.split for r in own} == {'val', 'test'}
        assert all(r.checkpoint_sha256 == sha for r in own)
        for report in own:
            individual = [r for r in reports if r.id_modelo != key and r.split == report.split]
            assert {r.manifest_sha256 for r in individual} == {report.manifest_sha256}
        registry = ModelRegistry(triad_records=runtime.triad_records)
        pairs = {}
        registry.publish_from_db(db, runtime.checkpoints_dir, pairs, owner_id=1)
        predictor = registry.get(f'fama_trained_model_{key}', owner_id=1)
        assert predictor.metadata.checkpoint_sha256 == sha
        assert pairs[predictor.model_id] == admitted['pair_ids']
        assert registry.get_default_model_id() is None
        with pytest.raises(ModelNotFoundError):
            registry.get(predictor.model_id, owner_id=2)


@pytest.mark.parametrize('failure', ['stop', 'joint_bind', 'persistence', 'stop_inflight'])
def test_joint_failure_or_stop_never_announces_availability(triad, training_env, monkeypatch, failure):
    from app.models.training import Modelo, ModelEvaluation
    from app.services.evaluations import EvaluationService
    from app.services.imported_triad_evaluation import ImportedTriadEvaluationError
    runtime, arguments, _ = triad
    inline(training_env)
    records = runtime.triad_records
    # A pre-existing active checkpoint must survive every late failure/stop.
    prior_path = runtime.checkpoints_dir / 'previous.pt'
    prior_path.write_bytes(b'synthetic prior artifact, never loaded')
    with records.sessions.begin() as db:
        prior = Modelo(arquitectura='fixture', clase_objetivo='previous', epocas=1,
            tasa_aprendizaje=0.01, tamano_lote=1, ruta_binario_gcp='models/previous.pt',
            hash_binario='b' * 64, tamano_bytes=prior_path.stat().st_size,
            activo=True, estado='standard_eval_completed')
        db.add(prior)
        db.flush()
        prior_id = prior.id_modelo
    original_complete = EvaluationService.complete
    def complete(self, attempt_id, report):
        # Preserve the real lifecycle, but inject a storage failure on joint test.
        with records.sessions() as db:
            attempt = db.get(ModelEvaluation, attempt_id)
            joint = db.get(Modelo, attempt.id_modelo).arquitectura == 'ImportedTriad'
            split = attempt.split
        if joint and split == 'test':
            if failure == 'persistence':
                raise RuntimeError('synthetic joint persistence failure')
            if failure == 'stop_inflight':
                runtime.stop_training(owner_id=1)
        return original_complete(self, attempt_id, report)
    monkeypatch.setattr(EvaluationService, 'complete', complete)
    phases = []
    def observe(snapshot):
        phases.append(snapshot)
        if snapshot['current_phase'] == 'joint_evaluation':
            if failure == 'stop':
                runtime.stop_training(owner_id=1)
            elif failure == 'joint_bind':
                with records.sessions.begin() as db:
                    db.get(Modelo, snapshot['component_results'][2]['model_id']).hash_binario = '0' * 64
    runtime._progress_callback = observe
    runtime.start_training(**arguments)
    progress = runtime.get_progress(owner_id=1)
    assert progress['status'] == ('stopped' if failure.startswith('stop') else 'failed'), progress
    assert not progress['ensemble_available']
    assert all(not s['ensemble_available'] for s in phases)
    assert len(progress['component_results']) == 3
    assert all((runtime.checkpoints_dir / c['filename']).is_file() for c in progress['component_results'])
    with records.sessions() as db:
        rows = db.query(Modelo).all()
        assert [m.id_modelo for m in rows if m.activo] == [prior_id]
        assert prior_path.read_bytes() == b'synthetic prior artifact, never loaded'
        joint = [m for m in rows if m.arquitectura == 'ImportedTriad']
        assert len(joint) == (1 if failure in ('persistence', 'stop_inflight') else 0)
        reports = db.query(ModelEvaluation).all()
        assert len([r for r in reports if r.status == 'completed' and r.id_modelo in
                    [c['model_id'] for c in progress['component_results']]]) == 6
        if failure in ('persistence', 'stop_inflight'):
            assert joint[0].estado == 'imported_triad_pending'
            before = [(r.id_evaluation, r.status) for r in reports]
            with pytest.raises(ImportedTriadEvaluationError):
                records.read_admitted(1, joint[0].id_modelo)
            with pytest.raises(ImportedTriadEvaluationError):
                records.evaluate_and_persist(1, joint[0].hash_binario)
            assert [(r.id_evaluation, r.status) for r in db.query(ModelEvaluation).all()] == before
        assert [h['id'] for h in runtime.get_history(db, owner_id=2)] == [prior_id]


@pytest.mark.parametrize('weights', [(0.2, 0.3, 0.5), (0.0, 0.5, 0.5)])
def test_joint_callback_snapshot_cannot_rewrite_requested_composition(triad, training_env, weights):
    from copy import deepcopy
    runtime, arguments, _ = triad
    inline(training_env)
    for model, weight in zip(arguments['models'], weights):
        model['weight'] = weight
    expected_weights = list(weights)
    captured = []
    def mutate_snapshot(snapshot):
        if snapshot['current_phase'] != 'joint_evaluation':
            return
        original = deepcopy(snapshot['component_results'])
        captured.append(original)
        # Still-valid weights/order: DB admission alone cannot detect job drift.
        snapshot['component_results'].reverse()
        for component, weight in zip(snapshot['component_results'], [0.5, 0.2, 0.3]):
            component['weight'] = weight
        snapshot['models_config'][0]['weight'] = 0.9
    runtime._progress_callback = mutate_snapshot
    runtime.start_training(**arguments)
    progress = runtime.get_progress(owner_id=1)
    assert progress['status'] == 'completed', progress
    assert captured
    admitted = runtime.triad_records.read_admitted(1, progress['composition_model_id'])
    assert admitted['manifest']['weights'] == expected_weights
    assert progress['component_results'] == captured[0]
    assert [m['weight'] for m in progress['models_config']] == expected_weights
    assert admitted['manifest']['components'] == [dict(model_id=c['model_id'],
        checkpoint_sha256=c['sha256'], imported_source=c['source']) for c in captured[0]]
    # Deeper source identity containers are detached too, not merely each dict.
    progress['component_results'][0]['source']['classes'].reverse()
    assert runtime.get_progress(owner_id=1)['component_results'] == captured[0]


def test_single_imported_completion_never_requests_triad_factory(triad, training_env, monkeypatch):
    from app.services.imported_triad_records import ImportedTriadRecords
    runtime, arguments, _ = triad
    def forbidden(*args, **kwargs):
        pytest.fail('single-model completion must not configure a triad')
    monkeypatch.setattr(ImportedTriadRecords, 'for_training', forbidden)
    runtime.triad_records = None
    model = arguments.pop('models')[0]
    arguments.update(imported_prepared_version=model['imported_prepared_version'],
                     architecture='AudioCNN', epochs=1, batch_size=2)
    inline(training_env)
    runtime.start_training(**arguments)
    progress = runtime.get_progress(owner_id=1)
    assert progress['status'] == 'completed', progress
    assert progress['ensemble_available'] is False
    assert progress['composition_model_id'] is None
    with runtime.imported_sources.preparations.snapshots.sessions() as db:
        entry, = runtime.get_history(db, owner_id=1)
        assert entry['status'] == 'standard_eval_completed'


def test_legacy_ensemble_keeps_eval4_without_triad_factory(persistence_env, monkeypatch):
    from app.services.imported_triad_records import ImportedTriadRecords
    runtime, sessions, _, _ = persistence_env
    def forbidden(*args, **kwargs):
        pytest.fail('legacy ensemble must not configure a triad')
    monkeypatch.setattr(ImportedTriadRecords, 'for_training', forbidden)
    start_legacy(runtime, models=[dict(architecture='fixture', weight=0.5),
                                dict(architecture='fixture', weight=0.5)])
    progress = runtime.get_progress()
    assert progress['status'] == 'completed', progress
    assert not progress['ensemble_available']
    assert progress['composition_model_id'] is None
    with sessions() as db:
        history = runtime.get_history(db)
        assert len(history) == 2
        assert all(h['status'] == 'standard_component_evaluated' and not h['active'] for h in history)


def test_training_factory_creates_only_configured_child_and_catalogue_reads_it(triad, training_env, monkeypatch):
    from app import database
    from app.services.registry import ModelRegistry
    runtime, arguments, preparations = triad
    monkeypatch.setattr(database, 'SessionLocal', preparations.snapshots.sessions)
    for name, root in (
            ('FAMA_IMPORT_ROOT', preparations.snapshots.source.root),
            ('FAMA_TRAINING_SNAPSHOT_ROOT', preparations.snapshots.root),
            ('FAMA_IMPORTED_PREPARED_ROOT', preparations.root)):
        monkeypatch.setenv(name, str(root))
    root = preparations.root / 'triad-manifests'
    assert not root.exists()
    runtime.triad_records = None
    inline(training_env)
    runtime.start_training(**arguments)
    progress = runtime.get_progress(owner_id=1)
    assert progress['status'] == 'completed', progress
    assert progress['ensemble_available'] is True
    assert root.is_dir() and root.stat().st_mode & 0o777 == 0o700
    registry = ModelRegistry()
    with preparations.snapshots.sessions() as db:
        registry.publish_from_db(db, runtime.checkpoints_dir, owner_id=1)
    predictor = registry.get(f"fama_trained_model_{progress['composition_model_id']}", owner_id=1)
    assert predictor.metadata.checkpoint_sha256 == progress['composition_sha256']
    assert registry.get_default_model_id() is None


def test_supervisor_transports_composition_snapshot(triad):
    from queue import Queue
    runtime, arguments, _ = triad
    class SnapshotRunner:
        exitcode = 0
        def __init__(self, target, *, args, seed):
            self.events = Queue()
        def start(self):
            self.events.put(dict(type='progress', snapshot=dict(status='completed',
                ensemble_available=True, composition_model_id=17,
                composition_sha256='a' * 64, current_phase='completed')))
            self.events.put(dict(type='finished'))
        def receive(self, timeout=None):
            return self.events.get(timeout=timeout)
        def is_alive(self):
            return False
        def join(self):
            pass
        def close(self):
            pass
    runtime._process_factory = SnapshotRunner
    runtime.start_training(**arguments)
    progress = runtime.get_progress(owner_id=1)
    assert progress['status'] == 'completed'
    assert progress['ensemble_available'] is True
    assert progress['composition_model_id'] == 17
    assert progress['composition_sha256'] == 'a' * 64
    assert progress['current_phase'] == 'completed'
