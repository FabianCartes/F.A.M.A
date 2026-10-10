"""Pure, ordered multiclass reports; no inference, persistence or rounding."""

from collections.abc import Sequence


def calculate_classification_report(y_true, y_pred, classes, *, rejection_label=None):
    """Return strict v1, or opt-in v2 with an explicit rejection prediction column.

    rejection_label=None retains v1; a distinct label of the target type enables
    v2 even with zero rejections. Rejections are errors, never true classes.

    Inputs are nonempty sequences of homogeneous built-in str or int labels.
    Classes are unique and ordered; every observed label must be declared.
    Invalid inputs raise ValueError. Macro averages include every declared
    class (zero division yields 0); balanced accuracy includes supported classes.
    Runtime is O(samples + classes²), including the dense confusion matrix.
    """
    for name, values in (('classes', classes), ('y_true', y_true), ('y_pred', y_pred)):
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
            raise ValueError(f'{name} must be a nonempty sequence of labels')
    classes = list(classes)
    y_true, y_pred = list(y_true), list(y_pred)
    if len(y_true) != len(y_pred):
        raise ValueError('y_true and y_pred must have equal lengths')
    label_type = type(classes[0])
    if label_type not in (str, int):
        raise ValueError('labels must be built-in strings or integers')
    for values in (classes, y_true, y_pred):
        if any(type(label) is not label_type or
               (label_type is str and not label.strip()) for label in values):
            raise ValueError('labels must have one coherent type and nonblank strings')
    if len(set(classes)) != len(classes):
        raise ValueError('classes must be unique')
    indices = {label: index for index, label in enumerate(classes)}
    columns = list(classes)
    if rejection_label is not None:
        if (type(rejection_label) is not label_type or
                (label_type is str and not rejection_label.strip()) or
                rejection_label in indices):
            raise ValueError('rejection_label must be a distinct coherent label')
        columns.append(rejection_label)
    prediction_indices = {label: index for index, label in enumerate(columns)}
    if (any(label not in indices for label in y_true) or
            any(label not in prediction_indices for label in y_pred)):
        raise ValueError('all observed labels must be declared in classes or prediction columns')
    matrix = [[0 for _ in columns] for _ in classes]
    for actual, predicted in zip(y_true, y_pred):
        matrix[indices[actual]][prediction_indices[predicted]] += 1
    support = [sum(row) for row in matrix]
    predicted_support = [sum(row[i] for row in matrix) for i in range(len(classes))]
    per_class = []
    for i, label in enumerate(classes):
        tp = matrix[i][i]
        actual, predicted = support[i], predicted_support[i]
        per_class.append({
            'label': label, 'precision': tp / predicted if predicted else 0.0,
            'recall': tp / actual if actual else 0.0,
            'f1': 2 * tp / (actual + predicted) if actual + predicted else 0.0,
            'support': actual,
            'zero_denominator': {'precision': predicted == 0,
                                 'recall': actual == 0,
                                 'f1': actual + predicted == 0},
        })
    count = len(y_true)
    metrics = {name + '_macro': sum(row[name] for row in per_class) / len(classes)
               for name in ('precision', 'recall', 'f1')}
    metrics.update({
        'accuracy': sum(matrix[i][i] for i in range(len(classes))) / count,
        'f1_weighted': sum(row['f1'] * row['support'] for row in per_class) / count,
        'balanced_accuracy': sum(row['recall'] for row in per_class if row['support'])
                             / sum(bool(n) for n in support),
    })
    absent = [label for label, n in zip(classes, support) if not n]
    report = {'schema_version': 1, 'classes': classes, 'sample_count': count,
            'metrics': metrics, 'per_class': per_class, 'support': support,
            'confusion_matrix': matrix,
            'coverage': {'absent_classes': absent, 'complete': not absent}}
    if rejection_label is not None:
        rejected = sum(row[-1] for row in matrix)
        report.update(schema_version=2, prediction_columns=columns,
                      rejection={'label': rejection_label, 'count': rejected,
                                 'rate': rejected / count})
    return report
