"""Public recording evaluation contract; synthetic local WAVs only."""
from pathlib import Path
import hashlib

import numpy as np
import torch
from types import SimpleNamespace
import wave

import pytest

from app.services.recording_evaluator import (
    LabelledRecording, RecordingEvaluator, validate_recording_splits,
)


def audio(path, value=100):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(22050)
        out.writeframes(value.to_bytes(2, 'little', signed=True) * 2205)
    return path


class Predictor:
    classes = ['b', 'a']

    def __init__(self, results):
        self.results = iter(results)
        self.paths = []

    def predict(self, path):
        self.paths.append(path)
        return next(self.results)


def result(label, status='classified'):
    return SimpleNamespace(clase=label, detalles={'status': status})


def prepare(tmp_path, predictor, labels=('b', 'a')):
    records = tuple(LabelledRecording(str(i), label, audio(tmp_path / f'{i}.wav'),
                                     f'raw/{i}.wav', 'raw', f'g{i}')
                    for i, label in enumerate(labels))
    return RecordingEvaluator(records, predictor, id_modelo=1, dataset='AvesChilenas',
                              split='val', checkpoint_sha256='a' * 64,
                              predictor_config={'version': 'published-v1'},
                              preprocessing_config={'crop': 'center'},
                              aggregation_config={'unit': 'recording'}), records


def test_real_predictor_restores_saved_weights_and_counts_local_recording(tmp_path):
    from app.services.predictors.trained_predictor import TrainedModelPredictor, AudioCNN
    model = AudioCNN(num_classes=2)
    for parameter in model.parameters():
        torch.nn.init.zeros_(parameter)
    checkpoint = tmp_path / 'saved.pt'
    torch.save({'architecture': 'AudioCNN', 'classes': ['b', 'a'],
                'state_dict': model.state_dict()}, checkpoint)
    # Mutating live weights must not affect the separately restored predictor.
    for parameter in model.parameters():
        parameter.data.fill_(1)
    path = tmp_path / 'tone.wav'
    samples = (np.sin(2 * np.pi * 1500 * np.arange(110250) / 22050) * 10000).astype('<i2')
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(22050)
        out.writeframes(samples.tobytes())
    predictor = TrainedModelPredictor(checkpoint, dataset_name='AvesChilenas')
    evaluator = RecordingEvaluator(
        (LabelledRecording('tone', 'b', path, 'tone.wav', 'raw'),), predictor,
        id_modelo=1, dataset='AvesChilenas', split='test',
        checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        predictor_config={'version': 'TrainedModelPredictor'},
        preprocessing_config={'target_sr': 22050, 'duration_seconds': 5.0},
        aggregation_config={'unit': 'recording'})
    assert not predictor.model.training
    assert all(torch.count_nonzero(p) == 0 for p in predictor.model.parameters())
    report = evaluator.evaluate()
    assert report['confusion_matrix'] == [[1, 0, 0], [0, 0, 0]]
    assert report['rejection']['count'] == 0


@pytest.mark.parametrize('fail_inference', [False, True])
def test_evaluator_identity_and_report_persist_through_sqlite(tmp_path, fail_inference):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models.training import Modelo
    from app.services.evaluations import EvaluationService

    engine = create_engine(f'sqlite:///{tmp_path / "reports.sqlite"}')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Modelo(id_modelo=1, arquitectura='AudioCNN', epocas=1,
                      tasa_aprendizaje=.01, tamano_lote=1, activo=False,
                      ruta_binario_gcp='synthetic.pt', estado='entrenado'))
        db.commit()
        predictor = Predictor([result('alien') if fail_inference else result('b')])
        evaluator, _ = prepare(tmp_path, predictor, labels=('b',))
        service = EvaluationService(db)
        attempt = service.create(evaluator.identity)
        attempt_id = attempt['id_evaluation']
        assert attempt['status'] == 'pending'
        assert service.start(attempt_id)['status'] == 'running'
        if fail_inference:
            with pytest.raises(ValueError, match='Unknown predictor') as error:
                evaluator.evaluate()
            service.fail(attempt_id, str(error.value))
        else:
            service.complete(attempt_id, evaluator.evaluate())
        db.expire_all()
        stored = service.read(attempt_id)
        assert stored['status'] == ('failed' if fail_inference else 'completed')
        assert stored['checkpoint_sha256'] == 'a' * 64
        assert stored['manifest_sha256'] == evaluator.identity.manifest_sha256
        if fail_inference:
            assert stored['report'] is None
            assert stored['error_reason'] == 'Unknown predictor output/status'
        else:
            assert stored['report']['confusion_matrix'] == [[1, 0, 0], [0, 0, 0]]
        assert db.get(Modelo, 1).activo is False
    engine.dispose()


def test_served_engine_ensemble_status_is_classified_once_per_recording(tmp_path):
    from app.schemas.evaluation import EvaluationProvenance

    path = audio(tmp_path / 'ensemble.wav')
    predictor = Predictor([result('b', 'classified_super_ensemble')])
    evaluator = RecordingEvaluator(
        (LabelledRecording('engine-1', 'b', path, 'engine.wav', 'raw', 'recordist-1'),),
        predictor, dataset='engine_diagnostics', split='test', checkpoint_sha256='a' * 64,
        predictor_config={'component_order': ['resnet', 'efficientnet', 'panns']},
        preprocessing_config={'frontend': 'hpss-3ch'},
        aggregation_config={'weights': [.6, .1, .3]},
    )
    report = evaluator.evaluate()
    assert report['confusion_matrix'] == [[1, 0, 0], [0, 0, 0]]
    assert predictor.paths == [path]
    assert isinstance(evaluator.identity, EvaluationProvenance)
    assert 'id_modelo' not in evaluator.identity.model_dump()


def test_standalone_provenance_has_no_database_model_id_and_accepts_bundle_status(tmp_path):
    from app.schemas.evaluation import EvaluationIdentity, EvaluationProvenance

    evaluator, _ = prepare(tmp_path, Predictor([result('b', 'bundle_classified')]), labels=('b',))
    # MAIN's consumer still explicitly requests the persisted FK identity; a
    # standalone evaluator can instead carry generic, non-persisted provenance.
    audio_path = tmp_path / 'standalone.wav'
    audio(audio_path)
    standalone = RecordingEvaluator(
        (LabelledRecording('local-1', 'b', audio_path, 'local.wav', 'raw'),),
        Predictor([result('b', 'bundle_classified')]), dataset='fixture', split='test',
        checkpoint_sha256='a' * 64, predictor_config={}, preprocessing_config={},
        aggregation_config={},
    )
    assert isinstance(standalone.identity, EvaluationProvenance)
    assert 'id_modelo' not in standalone.identity.model_dump()
    with pytest.raises(ValueError):
        EvaluationIdentity.model_validate(standalone.identity.model_dump())
    assert standalone.evaluate()['confusion_matrix'] == [[1, 0, 0], [0, 0, 0]]
    assert evaluator.evaluate()['confusion_matrix'] == [[1, 0, 0], [0, 0, 0]]


def test_recordings_count_once_with_rejection_and_ordered_classes(tmp_path):
    predictor = Predictor([result('b'), result('ignored', 'silence')])
    evaluator, records = prepare(tmp_path, predictor)
    report = evaluator.evaluate()
    assert report['confusion_matrix'] == [[1, 0, 0], [0, 0, 1]]
    assert report['metrics']['accuracy'] == 0.5
    assert report['rejection']['count'] == 1
    assert predictor.paths == [r.path for r in records]
    assert evaluator.identity.sample_count == 2
    assert evaluator.identity.schema_version == 2
    assert len(evaluator.identity.manifest_sha256) == 64


@pytest.mark.parametrize('kind', ['identity', 'group', 'path'])
def test_splits_reject_overlap(tmp_path, kind):
    path = audio(tmp_path / 'one.wav')
    other = audio(tmp_path / 'two.wav')
    a = LabelledRecording('1', 'a', path, 'one.wav', 'raw', 'g1')
    b = LabelledRecording('1' if kind == 'identity' else '2', 'a',
                         path if kind == 'path' else other, 'two.wav', 'raw',
                         'g1' if kind == 'group' else 'g2')
    with pytest.raises(ValueError, match='overlap'):
        validate_recording_splits({'train': (a,), 'val': (b,), 'test': (b,)})


def test_rejection_sentinel_cannot_be_a_real_class(tmp_path):
    predictor = Predictor([])
    predictor.classes = ['__recording_rejected__']
    with pytest.raises(ValueError, match='rejection'):
        prepare(tmp_path, predictor, labels=('__recording_rejected__',))


@pytest.mark.parametrize('output', [result('alien'), result('b', 'mystery')])
def test_unknown_output_is_not_rejection(tmp_path, output):
    evaluator, _ = prepare(tmp_path, Predictor([output]), labels=('b',))
    with pytest.raises(ValueError, match='Unknown predictor'):
        evaluator.evaluate()


@pytest.mark.parametrize('timing', ['before', 'during'])
def test_audio_mutation_invalidates_report(tmp_path, timing):
    class MutatingPredictor(Predictor):
        def predict(self, path):
            if timing == 'during':
                audio(path, value=300)
            return super().predict(path)
    predictor = MutatingPredictor([result('b')])
    evaluator, records = prepare(tmp_path, predictor, labels=('b',))
    if timing == 'before':
        audio(records[0].path, value=300)
    with pytest.raises(ValueError, match='Audio changed'):
        evaluator.evaluate()
    if timing == 'before':
        assert predictor.paths == []


def test_predict_failure_propagates(tmp_path):
    class FailingPredictor(Predictor):
        def predict(self, path):
            raise RuntimeError('inference failed')
    evaluator, _ = prepare(tmp_path, FailingPredictor([]), labels=('b',))
    with pytest.raises(RuntimeError, match='inference failed'):
        evaluator.evaluate()


def test_manifest_tracks_content_and_labels(tmp_path):
    first, _ = prepare(tmp_path, Predictor([]))
    second, _ = prepare(tmp_path, Predictor([]), labels=('a', 'b'))
    assert first.identity.manifest_sha256 != second.identity.manifest_sha256
    audio(tmp_path / '0.wav', value=300)
    records = (LabelledRecording('0', 'b', tmp_path / '0.wav', 'raw/0.wav', 'raw', 'g0'),)
    changed = RecordingEvaluator(records, Predictor([]), **{
        k: v for k, v in first.identity.model_dump().items()
        if k in ('id_modelo', 'dataset', 'split', 'checkpoint_sha256',
                 'predictor_config', 'preprocessing_config', 'aggregation_config')})
    assert changed.identity.manifest_sha256 != first.identity.manifest_sha256


def test_val_and_test_reports_remain_independent(tmp_path):
    val, records = prepare(tmp_path, Predictor([result('b')]), labels=('b',))
    test = RecordingEvaluator(records, Predictor([result('ignored', 'noise')]), **{
        **{k: v for k, v in val.identity.model_dump().items()
           if k in ('id_modelo', 'dataset', 'checkpoint_sha256', 'predictor_config',
                    'preprocessing_config', 'aggregation_config')}, 'split': 'test'})
    assert val.evaluate()['metrics']['accuracy'] == 1.0
    assert test.evaluate()['metrics']['accuracy'] == 0.0
    assert test.identity.split == 'test'


@pytest.mark.parametrize('fault', ['label', 'missing', 'decode'])
def test_invalid_recording_fails_preflight(tmp_path, fault):
    path = audio(tmp_path / 'input.wav')
    if fault == 'missing':
        path = tmp_path / 'absent.wav'
    if fault == 'decode':
        path.write_bytes(b'not audio')
    record = LabelledRecording('1', 'unknown' if fault == 'label' else 'b',
                               path, 'input.wav', 'raw')
    with pytest.raises((ValueError, RuntimeError, OSError)):
        RecordingEvaluator((record,), Predictor([]), id_modelo=1,
                           dataset='AvesChilenas', split='val', checkpoint_sha256='a' * 64,
                           predictor_config={}, preprocessing_config={}, aggregation_config={})
