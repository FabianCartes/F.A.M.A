import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml_core.classification_metrics import calculate_classification_report


@pytest.mark.parametrize('actual,predicted,classes', [
    ([], [], ['a']), (['a'], [], ['a']), (['a'], ['a'], []),
    (['a'], ['a', 'a'], ['a']), (['a'], ['a'], ['a', 'a']),
    (['unknown'], ['a'], ['a']), (['a'], ['unknown'], ['a']),
    ([True], [1], [1]), ([1], [False], [1]), ([1], [1], [True]),
    ([None], ['a'], ['a']), (['a'], [None], ['a']), (['a'], ['a'], [None]),
    ([1.0], [1], [1]), ([1], [1], [1.0]),
    (['a'], ['a'], ['a', 1]), ([''], [''], ['']),
    ([['a']], ['a'], ['a']), ('a', ['a'], ['a']),
    (None, ['a'], ['a']), (['a'], ['a'], {'a': 0}),
])
def test_invalid_inputs_are_rejected(actual, predicted, classes):
    with pytest.raises(ValueError):
        calculate_classification_report(actual, predicted, classes)


def test_rejections_count_as_errors_without_changing_targets():
    report = calculate_classification_report(
        ['a', 'a', 'a', 'b'], ['a', 'b', 'reject', 'b'],
        ['a', 'b'], rejection_label='reject')
    assert report['schema_version'] == 2
    assert report['prediction_columns'] == ['a', 'b', 'reject']
    assert report['confusion_matrix'] == [[1, 1, 1], [0, 1, 0]]
    assert report['support'] == [3, 1]
    assert report['rejection'] == {'label': 'reject', 'count': 1, 'rate': .25}
    assert report['metrics'] == pytest.approx(dict(
        accuracy=.5, precision_macro=.75, recall_macro=.6666666666666666,
        f1_macro=.5833333333333333, f1_weighted=.5416666666666666,
        balanced_accuracy=.6666666666666666))
    assert report['per_class'][0]['f1'] == .5
    assert json.loads(json.dumps(report, allow_nan=False)) == report


@pytest.mark.parametrize('classes,reject', [(['a', 'b', 'c'], 'reject'), ([2, 1, 3], -1)])
@pytest.mark.parametrize('abstain', [True, False])
def test_all_or_zero_abstentions_have_stable_columns(classes, reject, abstain):
    actual = [classes[0], classes[1]]
    report = calculate_classification_report(actual, [reject, reject] if abstain else actual,
                                            classes, rejection_label=reject)
    assert report['prediction_columns'] == classes + [reject]
    assert report['confusion_matrix'] == (
        [[0, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 0]] if abstain else
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0]])
    assert report['rejection'] == {'label': reject, 'count': 2 if abstain else 0,
                                   'rate': 1.0 if abstain else 0.0}
    assert report['metrics']['accuracy'] == (0.0 if abstain else 1.0)
    assert report['metrics']['balanced_accuracy'] == (0.0 if abstain else 1.0)
    assert report['metrics']['f1_macro'] == (0.0 if abstain else .6666666666666666)
    assert report['coverage'] == {'absent_classes': [classes[2]], 'complete': False}


@pytest.mark.parametrize('actual,predicted,classes,reject', [
    (['a'], ['a'], ['a'], 'a'),
    (['a'], ['reject'], ['a'], ' '),
    (['a'], ['reject'], ['a'], 1),
    ([1], [1], [1], True),
    ([1], [1], [1], 2.0),
    (['a'], ['unknown'], ['a'], 'reject'),
    (['reject'], ['a'], ['a'], 'reject'),
])
def test_invalid_rejection_inputs_fail_closed(actual, predicted, classes, reject):
    with pytest.raises(ValueError):
        calculate_classification_report(actual, predicted, classes, rejection_label=reject)


def test_single_class_tuple_inputs_and_input_preservation():
    actual, predicted, classes = (7, 7), [7, 7], [7]
    report = calculate_classification_report(actual, predicted, classes)
    assert set(report['metrics'].values()) == {1.0}
    assert report['per_class'] == [{
        'label': 7, 'precision': 1.0, 'recall': 1.0, 'f1': 1.0, 'support': 2,
        'zero_denominator': {'precision': False, 'recall': False, 'f1': False}}]
    report['classes'].append(9)
    assert actual == (7, 7) and predicted == [7, 7] and classes == [7]


def test_known_confusion_matrix_and_imbalanced_metrics():
    report = calculate_classification_report(
        ['a', 'a', 'a', 'b'], ['a', 'a', 'b', 'b'], ['b', 'a'])
    assert report['schema_version'] == 1
    assert report['classes'] == ['b', 'a']
    assert report['sample_count'] == 4
    assert report['confusion_matrix'] == [[1, 0], [1, 2]]
    assert report['support'] == [1, 3]
    assert report['metrics'] == pytest.approx({
        'accuracy': 0.75, 'precision_macro': 0.75,
        'recall_macro': 0.8333333333333333, 'f1_macro': 0.7333333333333334,
        'f1_weighted': 0.7666666666666667,
        'balanced_accuracy': 0.8333333333333333,
    })
    assert report['per_class'][1]['f1'] == 0.8
    assert report['coverage'] == {'absent_classes': [], 'complete': True}
    assert json.loads(json.dumps(report, allow_nan=False)) == report


def test_absent_predicted_only_and_never_predicted_classes():
    report = calculate_classification_report([2, 2, 1], [2, 3, 2], [3, 1, 2, 0])
    assert report['confusion_matrix'] == [[0, 0, 0, 0], [0, 0, 1, 0],
                                           [1, 0, 1, 0], [0, 0, 0, 0]]
    assert report['coverage'] == {'absent_classes': [3, 0], 'complete': False}
    assert report['metrics'] == pytest.approx({
        'accuracy': 0.3333333333333333, 'precision_macro': 0.125,
        'recall_macro': 0.125, 'f1_macro': 0.125,
        'f1_weighted': 0.3333333333333333, 'balanced_accuracy': 0.25})
    assert [row['zero_denominator'] for row in report['per_class']] == [
        {'precision': False, 'recall': True, 'f1': False},
        {'precision': True, 'recall': False, 'f1': False},
        {'precision': False, 'recall': False, 'f1': False},
        {'precision': True, 'recall': True, 'f1': True}]
    assert report['metrics']['accuracy'] == 0.3333333333333333
    assert json.loads(json.dumps(report, allow_nan=False)) == report
