"""Real SQLite, immutable synthetic sources, guards and joint recording evaluation."""
from copy import deepcopy
import hashlib
import pytest
import torch
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create


@pytest.fixture(autouse=True)
def synthetic_audio(monkeypatch, request):
    import io
    import wave
    import numpy as np
    from tests import test_imported_dataset_preparation as fixtures
    def audio(sample):
        mode = getattr(request, 'param', 'tone')
        values = (np.eye(1, 8000).ravel() * sample / 32767 if mode == 'silence' else
                  np.random.default_rng(sample).normal(0, 0.1, 8000) if mode == 'noise' else
                  0.2 * np.sin(2 * np.pi * (440 + sample) * np.arange(8000) / 8000))
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes((values * 32767).astype('<i2').tobytes())
        return stream.getvalue()
    monkeypatch.setattr(fixtures, 'wav_bytes', audio)


@pytest.fixture
def bound(synthetic_audio, cohort, tmp_path, monkeypatch, request):
    from app.models.training import Modelo
    from app.models.imported_training_source import ImportedModelSource
    from app.services.imported_training_source import ImportedTrainingSource
    from app.services.imported_triad_manifests import ImportedTriadManifests
    from app.services.imported_evaluation import evaluation_recordings
    from app.services.recording_evaluator import RecordingEvaluator
    from app.services.standard_evaluation_guard import (
        inspect_checkpoint, admitted_manifest_pair_provenance, ADMITTED_MANIFEST_PAIR_KEY)
    from app.services.evaluations import EvaluationService
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from tests.test_imported_training_evaluation import checkpoint_payload
    from scripts.migrate_imported_training_source import migrate_imported_sources
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / 'prepared-joint')
    prepared = create(preparations, cohort)
    sources = ImportedTrainingSource(preparations)
    source = sources.resolve(1, cohort[5], cohort[1]['id'], prepared['version_id'], architecture='AudioCNN')
    sessions = cohort[0].sessions
    migrate_imported_sources(sessions.kw['bind'], writers_stopped=True)
    root = tmp_path / 'checkpoints-joint'
    root.mkdir()
    from app.services.predictors import trained_predictor
    # Only the external neural constructor is replaced, not audio/guards/evaluator.
    class Neural(torch.nn.Module):
        def __init__(self, num_classes, **kwargs):
            super().__init__()
            self.logits = torch.nn.Parameter(torch.zeros(num_classes))
        def forward(self, x):
            return self.logits.unsqueeze(0).expand(x.shape[0], -1)
    monkeypatch.setattr(trained_predictor, 'AudioCNN', Neural)
    components = []
    with evaluation_recordings(source) as recordings, sessions() as db:
        for index, probabilities in enumerate(([0.9, 0.1], [0.2, 0.8], [0.1, 0.9])):
            if index == 2 and getattr(request, 'param', None) == 'cohort_mismatch':
                alternate = preparations.create(1, cohort[1]['id'], mapping=cohort[2],
                    provenance={'source': 'independently valid different provenance'}, seed=42, profile=cohort[3])
                source = sources.resolve(1, cohort[5], cohort[1]['id'], alternate['version_id'], architecture='AudioCNN')
            payload = checkpoint_payload()
            payload.update(imported_source=source['identity'], classes=source['classes'],
                dataset_name='imported:' + cohort[5], audio_config=source['identity']['profile']['audio'])
            payload['state_dict'] = {'logits': torch.log(torch.tensor(probabilities))}
            path = root / f'component-{index}.pt'
            torch.save(payload, path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            model = Modelo(arquitectura='AudioCNN', clase_objetivo='private',
                ruta_binario_gcp=path.as_uri(), hash_binario=digest, tamano_bytes=path.stat().st_size,
                id_usuario=1, epocas=1, tasa_aprendizaje=0.001, tamano_lote=1,
                activo=False, estado='standard_eval_completed')
            db.add(model)
            db.flush()
            if not (index == 2 and getattr(request, 'param', None) == 'missing_association'):
                db.add(ImportedModelSource(model_id=model.id_modelo, owner_id=1,
                    dataset_id=cohort[5], snapshot_id=cohort[1]['id'], identity=source['identity']))
            db.commit()
            inspection = inspect_checkpoint(root, path, digest)
            individual = trained_predictor.TrainedModelPredictor(path, lazy_load=True,
                expected_checkpoint_sha256=digest)
            evaluators = {split: RecordingEvaluator(recordings[split], individual,
                id_modelo=model.id_modelo, dataset=payload['dataset_name'], split=split,
                checkpoint_sha256=digest, predictor_config=inspection.configurations[0],
                preprocessing_config=inspection.configurations[1],
                aggregation_config=inspection.configurations[2]) for split in ('val', 'test')}
            pair = admitted_manifest_pair_provenance(*(evaluators[s].identity.manifest_sha256 for s in ('val', 'test')))
            service = EvaluationService(db)
            for evaluator in evaluators.values():
                identity = evaluator.identity
                evaluator.identity = type(identity).model_validate({**identity.model_dump(),
                    'predictor_config': {**identity.predictor_config, ADMITTED_MANIFEST_PAIR_KEY: pair}})
                attempt = service.create(evaluator.identity)['id_evaluation']
                service.start(attempt)
                service.complete(attempt, evaluator.evaluate())
            components.append(dict(model_id=model.id_modelo, checkpoint_sha256=digest,
                                   imported_source=deepcopy(source['identity'])))
    manifests = ImportedTriadManifests(tmp_path / 'compositions-joint')
    composition = manifests.create(1, components, [0.1, 0.4, 0.5])
    return sessions, manifests, sources, root, composition, source


@pytest.mark.parametrize('bound', ['normal'], indirect=True)
def test_joint_reports_are_actual_weighted_predictions(bound):
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation
    sessions, manifests, sources, root, composition, _ = bound
    before = database_snapshot(sessions)
    result = ImportedTriadEvaluation(sessions, manifests, sources, root).evaluate(1, composition['id'])
    assert database_snapshot(sessions) == before
    assert result['composition_id'] == composition['id']
    assert result['predictor'].model_id == 'fama_triad_' + composition['id']
    assert len(set(p.model_id for p in result['predictor'].components)) == 3
    assert [p.metadata.loaded_checkpoint_sha256 for p in result['predictor'].components] == [
        c['checkpoint_sha256'] for c in composition['manifest']['components']]
    from app.services.imported_evaluation import evaluation_recordings
    with evaluation_recordings(bound[5]) as recordings:
        output = result['predictor'].predict(recordings['test'][0].path)
    assert output.clase == 'zebra'
    assert output.detalles['probabilities'] == pytest.approx([0.22, 0.78])
    for split in ('val', 'test'):
        report = result['reports'][split]
        assert report['classes'] == ['ants', 'zebra']
        assert report['sample_count'] == 2
        assert report['confusion_matrix'] == [[0, 1, 0], [0, 1, 0]]
        assert report['rejection']['count'] == 0
        identity = result['identities'][split]
        assert identity.checkpoint_sha256 == composition['id']
        assert identity.predictor_config['components'] == composition['manifest']['components']
        assert identity.predictor_config['weights'] == [0.1, 0.4, 0.5]


@pytest.mark.parametrize('synthetic_audio', ['silence', 'noise'], indirect=True)
def test_actual_rejections_remain_in_joint_denominator(bound, synthetic_audio):
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation
    sessions, manifests, sources, root, composition, _ = bound
    result = ImportedTriadEvaluation(sessions, manifests, sources, root).evaluate(1, composition['id'])
    for report in result['reports'].values():
        assert report['confusion_matrix'] == [[0, 0, 1], [0, 0, 1]]
        assert report['rejection']['count'] == report['sample_count'] == 2
        assert report['metrics']['accuracy'] == 0


def database_snapshot(sessions):
    from sqlalchemy import select
    from app.models.training import Modelo, ModelEvaluation
    from app.models.imported_training_source import ImportedModelSource
    with sessions() as db:
        return {model.__table__.name: [tuple(row) for row in db.execute(select(model.__table__)).all()]
                for model in (Modelo, ModelEvaluation, ImportedModelSource)}


@pytest.mark.parametrize('damage', ['foreign', 'missing_model', 'association', 'source_identity',
    'true_owner', 'hash', 'bytes', 'path', 'symlink', 'reports', 'report_cohort', 'preparation'])
def test_invalid_binding_is_private_and_never_backfills(bound, damage, tmp_path):
    from app.models.training import Modelo, ModelEvaluation
    from app.models.imported_training_source import ImportedModelSource
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation, ImportedTriadEvaluationError
    from app.services.standard_evaluation_guard import admitted_manifest_pair_provenance, ADMITTED_MANIFEST_PAIR_KEY
    from app.services.registry import ModelRegistry
    sessions, manifests, sources, root, composition, source = bound
    # The THIRD component is always required, not just the first identity.
    key = composition['manifest']['components'][2]['model_id']
    owner = 2 if damage == 'foreign' else 1
    with sessions.begin() as db:
        model = db.get(Modelo, key)
        association = db.get(ImportedModelSource, key)
        if damage == 'missing_model':
            # Change the reference, not delete fixture/live artifacts.
            components = deepcopy(composition['manifest']['components'])
            components[2]['model_id'] = 99999
            composition = manifests.create(1, components, composition['manifest']['weights'])
        elif damage == 'association':
            association.owner_id = 2
        elif damage == 'source_identity':
            association.identity = {**association.identity, 'provenance': {'source': 'stale'}}
        elif damage == 'true_owner':
            model.id_usuario = 2
        elif damage == 'hash':
            model.hash_binario = '0' * 64
        elif damage == 'bytes':
            (root / 'component-2.pt').write_bytes(b'corrupt synthetic checkpoint')
        elif damage == 'path':
            # An actual foreign file with matching bytes must not be basename-substituted.
            foreign = tmp_path / 'component-2.pt'
            foreign.write_bytes((root / 'component-2.pt').read_bytes())
            model.ruta_binario_gcp = foreign.as_uri()
        elif damage == 'symlink':
            foreign = tmp_path / 'foreign.pt'
            foreign.write_bytes((root / 'component-2.pt').read_bytes())
            (root / 'linked.pt').symlink_to(foreign)
            model.ruta_binario_gcp = (root / 'linked.pt').as_uri()
        elif damage == 'reports':
            for report in db.query(ModelEvaluation).filter_by(id_modelo=key):
                from sqlalchemy import null
                report.status = 'failed'
                report.report = null()
                report.error_reason = 'Synthetic invalidated attempt'
        elif damage == 'report_cohort':
            # Still internally coherent reports: only actual cohort binding can reject.
            rows = db.query(ModelEvaluation).filter_by(id_modelo=key).all()
            pair = admitted_manifest_pair_provenance('a' * 64, 'b' * 64)
            for report in rows:
                report.manifest_sha256 = ('a' if report.split == 'val' else 'b') * 64
                report.predictor_config = {**report.predictor_config, ADMITTED_MANIFEST_PAIR_KEY: pair}
        elif damage == 'preparation':
            # Content-addressed resolution must detect tampered historical bytes.
            version = source['identity']['preparation_version']
            manifest_path = sources.preparations.root / version / 'manifest.json'
            manifest_path.chmod(0o600)
            manifest_path.write_text('{}')
    before = database_snapshot(sessions)
    registry = ModelRegistry()
    catalogue = registry.list_models(owner_id=1)
    with pytest.raises(ImportedTriadEvaluationError) as failure:
        ImportedTriadEvaluation(sessions, manifests, sources, root).evaluate(owner, composition['id'])
    assert str(failure.value) == 'Composición importada no disponible.'
    assert failure.value.code == 'composition_unavailable'
    assert database_snapshot(sessions) == before
    assert registry.list_models(owner_id=1) == catalogue


def test_third_component_nonpositive_registered_sizes_fail_without_side_effects(bound):
    from app.models.training import Modelo
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation, ImportedTriadEvaluationError
    from app.services.registry import ModelRegistry
    sessions, manifests, sources, root, composition, _ = bound
    key = composition['manifest']['components'][2]['model_id']
    service = ImportedTriadEvaluation(sessions, manifests, sources, root)
    registry = ModelRegistry()
    catalogue = registry.list_models(owner_id=1)
    rejected = []
    for declared_size in (0, -1):
        with sessions.begin() as db:
            db.get(Modelo, key).tamano_bytes = declared_size
        before = database_snapshot(sessions)
        try:
            service.evaluate(1, composition['id'])
        except ImportedTriadEvaluationError as failure:
            assert failure.code == 'composition_unavailable'
            assert str(failure) == 'Composición importada no disponible.'
            rejected.append(declared_size)
        assert database_snapshot(sessions) == before
        assert registry.list_models(owner_id=1) == catalogue
    assert rejected == [0, -1], 'Both invalid registered sizes must be rejected'


@pytest.mark.parametrize('bound', ['missing_association', 'cohort_mismatch'], indirect=True)
def test_self_consistent_artifacts_do_not_replace_authoritative_source_admission(bound):
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation, ImportedTriadEvaluationError
    sessions, manifests, sources, root, composition, _ = bound
    before = database_snapshot(sessions)
    with pytest.raises(ImportedTriadEvaluationError):
        ImportedTriadEvaluation(sessions, manifests, sources, root).evaluate(1, composition['id'])
    assert database_snapshot(sessions) == before


def test_archived_historical_composition_evaluates_but_new_training_is_denied(bound, cohort):
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation
    from app.services.imported_training_source import ImportedSourceError
    sessions, manifests, sources, root, composition, source = bound
    dataset = cohort[4].get('/api/ingestion/imports/datasets').json()['datasets'][0]
    response = cohort[4].request('DELETE', '/api/ingestion/imports/datasets/' + cohort[5],
        json={'revision': dataset['revision']})
    assert response.status_code == 204
    before = database_snapshot(sessions)
    result = ImportedTriadEvaluation(sessions, manifests, sources, root).evaluate(1, composition['id'])
    assert result['reports']['test']['sample_count'] == 2
    options = [{'version': source['identity']['preparation_version'], 'architecture': 'AudioCNN'}] * 3
    with pytest.raises(ImportedSourceError):
        sources.resolve_triad_for_training(1, cohort[5], cohort[1]['id'], options)
    assert database_snapshot(sessions) == before
