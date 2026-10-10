"""Public persistence contract; isolated SQLite, never application startup."""
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with patch('dotenv.load_dotenv', return_value=False):
    from app.database import Base
    from app.models.training import Modelo, MetricaEntrenamiento
from ml_core.classification_metrics import calculate_classification_report


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "evaluation.sqlite"}')
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        model = Modelo(arquitectura='AudioCNN', epocas=1, tasa_aprendizaje=.01,
                       tamano_lote=2, ruta_binario_gcp='local.pt', precision=86.75,
                       perdida=.452, activo=True)
        db.add(model)
        db.flush()
        db.add(MetricaEntrenamiento(id_modelo=model.id_modelo, epoca=1,
                                   precision=55, perdida=1.25))
        db.commit()
        yield db
    engine.dispose()


def identity():
    return dict(id_modelo=1, schema_version=1, evaluator_version='fama-v1',
                checkpoint_sha256='a' * 64, dataset='AvesChilenas', split='test',
                manifest_sha256='b' * 64, classes=['a', 'b'], sample_count=3,
                predictor_config={'name': 'AudioCNN'}, preprocessing_config={'sr': 22050},
                aggregation_config={'mode': 'mean'}, code_revision=None)


def report():
    return calculate_classification_report(['a', 'a', 'b'], ['a', 'b', 'b'], ['a', 'b'])


def test_completed_roundtrip_preserves_fractional_report_and_history(session):
    from app.services.evaluations import EvaluationService
    service = EvaluationService(session)
    created = service.create(identity())
    assert created['status'] == 'pending' and created['report'] is None
    assert service.start(created['id_evaluation'])['status'] == 'running'
    completed = service.complete(created['id_evaluation'], report())
    assert completed['report'] == report()
    assert completed['report']['metrics']['accuracy'] == 2 / 3
    session.expire_all()
    assert service.read(created['id_evaluation']) == completed
    model = session.get(Modelo, 1)
    assert (model.precision, model.perdida, model.activo) == (86.75, .452, True)
    assert [(m.precision, m.perdida) for m in model.metricas] == [(55, 1.25)]


def test_failure_absence_retry_and_terminal_immutability(session):
    from app.services.evaluations import EvaluationService
    service = EvaluationService(session)
    assert service.read(999) is None
    first = service.create(identity())
    failed = service.fail(first['id_evaluation'], 'missing checkpoint')
    assert failed['status'] == 'failed' and failed['report'] is None
    assert failed['error_reason'] == 'missing checkpoint'
    for operation in (service.start, lambda i: service.complete(i, report()),
                      lambda i: service.fail(i, 'retry')):
        with pytest.raises(ValueError):
            operation(first['id_evaluation'])
    second = service.create(identity())
    assert second['id_evaluation'] != first['id_evaluation']
    service.start(second['id_evaluation'])
    completed = service.complete(second['id_evaluation'], report())
    for operation in (service.start, lambda i: service.complete(i, report()),
                      lambda i: service.fail(i, 'retry')):
        with pytest.raises(ValueError):
            operation(second['id_evaluation'])
    completed['classes'].append('mutated')
    completed['report']['metrics']['accuracy'] = 0
    assert service.read(second['id_evaluation'])['report'] == report()
    assert service.read(first['id_evaluation']) == failed
    json.dumps(service.read(second['id_evaluation']), allow_nan=False)


@pytest.mark.parametrize('field,value', [
    ('id_modelo', None), ('id_modelo', True), ('id_modelo', 999),
    ('schema_version', 3), ('schema_version', True), ('schema_version', 1.0), ('checkpoint_sha256', 'bad'), ('manifest_sha256', 'x'*64),
    ('dataset', ' '), ('evaluator_version', ' '), ('split', 'train'),
    ('classes', []), ('classes', ['a', 'a']), ('classes', ['a', 1]),
    ('classes', [True]), ('classes', [' ']), ('sample_count', 0),
    ('sample_count', True), ('sample_count', 1.2),
    ('predictor_config', {'n': float('nan')}),
    ('preprocessing_config', {'n': float('inf')}),
    ('aggregation_config', {1: 'non-string-key'}),
    ('predictor_config', {'not_json': (1, 2)}),
])
def test_invalid_provenance_rejected(session, field, value):
    from app.services.evaluations import EvaluationService
    data = identity()
    data[field] = value
    with pytest.raises(ValueError):
        EvaluationService(session).create(data)
    assert session.query(Modelo).count() == 1


@pytest.mark.parametrize('change', [
    lambda r: r.update(sample_count=4),
    lambda r: r.update(classes=['b', 'a']),
    lambda r: r.update(classes=None),
    lambda r: r.update(schema_version=True),
    lambda r: r.update(confusion_matrix=[[1, 1], [0, -1]]),
    lambda r: r.update(confusion_matrix=[[True, 1], [0, 1]]),
    lambda r: r.update(confusion_matrix=[[1, 1]]),
    lambda r: r.update(support=[1, 2]),
    lambda r: r['metrics'].update(accuracy=66.666),
    lambda r: r['metrics'].update(accuracy=float('nan')),
    lambda r: r['metrics'].update(f1_macro=.3),
    lambda r: r['per_class'][0].update(support=3),
    lambda r: r['per_class'][0]['zero_denominator'].update(precision=0),
    lambda r: r['coverage'].update(complete=False),
    lambda r: r.update(extra='not-v1'),
    lambda r: r.pop('metrics'),
])
def test_incoherent_reports_leave_running_attempt_unchanged(session, change):
    from app.services.evaluations import EvaluationService
    service = EvaluationService(session)
    evaluation = service.create(identity())
    before = service.start(evaluation['id_evaluation'])
    bad = copy.deepcopy(report())
    change(bad)
    with pytest.raises(ValueError):
        service.complete(evaluation['id_evaluation'], bad)
    assert service.read(evaluation['id_evaluation']) == before
    assert service.complete(evaluation['id_evaluation'], report())['status'] == 'completed'


def test_illegal_and_missing_transitions_are_rejected(session):
    from app.services.evaluations import EvaluationService
    service = EvaluationService(session)
    evaluation = service.create(identity())
    with pytest.raises(ValueError):
        service.complete(evaluation['id_evaluation'], report())
    for reason in (' ', None, 'x' * 2001):
        with pytest.raises(ValueError):
            service.fail(evaluation['id_evaluation'], reason)
    for operation in (service.start, lambda i: service.complete(i, report()), lambda i: service.fail(i, 'error')):
        with pytest.raises(ValueError):
            operation(999)
    service.start(evaluation['id_evaluation'])
    with pytest.raises(ValueError):
        service.start(evaluation['id_evaluation'])


@pytest.mark.parametrize('values', [
    {'status': 'unknown'}, {'split': 'train'}, {'sample_count': 0},
    {'schema_version': 3}, {'id_modelo': 999}, {'id_modelo': None},
    {'status': 'completed'}, {'status': 'failed'}, {'status': 'running'},
])
def test_database_rejects_invalid_state_and_identity(session, values):
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError
    from app.models.training import ModelEvaluation
    from app.services.evaluations import EvaluationService
    service = EvaluationService(session)
    created = service.create(identity())
    with pytest.raises(IntegrityError):
        session.execute(update(ModelEvaluation).where(
            ModelEvaluation.id_evaluation == created['id_evaluation']).values(**values))
        session.commit()
    session.rollback()
    assert service.read(created['id_evaluation']) == created


@pytest.mark.parametrize('classes,reject', [(['a', 'b'], 'reject'), ([2, 1], -1)])
def test_v2_roundtrip(session, classes, reject):
    from app.services.evaluations import EvaluationService
    data = identity()
    data.update(schema_version=2, classes=classes)
    expected = calculate_classification_report(
        [classes[0], classes[0], classes[1]],
        [classes[0], reject, classes[1]], classes, rejection_label=reject)
    service = EvaluationService(session)
    attempt = service.create(data)
    service.start(attempt['id_evaluation'])
    completed = service.complete(attempt['id_evaluation'], expected)
    session.expire_all()
    assert service.read(attempt['id_evaluation']) == completed
    assert completed['report'] == expected


@pytest.mark.parametrize('change', [
    lambda r: r.update(schema_version=1),
    lambda r: r.update(schema_version=2.0),
    lambda r: r.update(prediction_columns=['b', 'a', 'reject']),
    lambda r: r.update(confusion_matrix=[[1, 0], [0, 1]]),
    lambda r: r.update(confusion_matrix=[[1, 0, 1], [0, 1, 0], [0, 0, 0]]),
    lambda r: r['rejection'].update(count=0),
    lambda r: r['rejection'].update(count=True),
    lambda r: r['rejection'].update(rate=0),
    lambda r: r['rejection'].update(label='a'),
    lambda r: r['metrics'].update(recall_macro=1),
])
def test_malformed_v2_preserves_running_attempt(session, change):
    from app.services.evaluations import EvaluationService
    data = identity()
    data['schema_version'] = 2
    service = EvaluationService(session)
    attempt = service.create(data)
    before = service.start(attempt['id_evaluation'])
    expected = calculate_classification_report(
        ['a', 'a', 'b'], ['a', 'reject', 'b'], ['a', 'b'], rejection_label='reject')
    bad = copy.deepcopy(expected)
    change(bad)
    with pytest.raises(ValueError):
        service.complete(attempt['id_evaluation'], bad)
    assert service.read(attempt['id_evaluation']) == before
    assert service.complete(attempt['id_evaluation'], expected)['report'] == expected


def test_absent_classes_and_integer_labels_roundtrip(session):
    from app.services.evaluations import EvaluationService
    data = identity()
    data.update(classes=[2, 1, 3], sample_count=2, split='val')
    expected = calculate_classification_report([2, 2], [2, 1], [2, 1, 3])
    service = EvaluationService(session)
    attempt = service.create(data)
    service.start(attempt['id_evaluation'])
    result = service.complete(attempt['id_evaluation'], expected)
    assert result['report'] == expected
    assert result['report']['coverage'] == {'absent_classes': [1, 3], 'complete': False}
    assert result['report']['metrics']['balanced_accuracy'] == .5
