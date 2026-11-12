"""Strict provenance and finite, coherent EVAL-1 reports (no inference)."""
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvaluationProvenance(BaseModel):
    """Evaluation identity usable without inventing a persisted database model."""
    model_config = ConfigDict(strict=True, extra='forbid')
    schema_version: Literal[1, 2]
    evaluator_version: str = Field(min_length=1, max_length=100)
    checkpoint_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    dataset: str = Field(min_length=1, max_length=255)
    split: Literal['val', 'test']
    manifest_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    classes: list
    predictor_config: dict
    preprocessing_config: dict
    aggregation_config: dict
    sample_count: int = Field(gt=0, le=2147483647)
    code_revision: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('schema_version must be an integer')
        return value

    @model_validator(mode='after')
    def validate_identity(self):
        for name in ('dataset', 'evaluator_version', 'code_revision'):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f'{name} must not be blank')
        classes = self.classes
        if not classes or type(classes[0]) not in (str, int):
            raise ValueError('classes must be nonempty string or integer labels')
        if any(type(c) is not type(classes[0]) or isinstance(c, str) and not c.strip() for c in classes):
            raise ValueError('classes must have homogeneous nonblank labels')
        if len(set(classes)) != len(classes):
            raise ValueError('classes must be unique')
        strict_json(self.model_dump())
        return self


class EvaluationIdentity(EvaluationProvenance):
    """Persisted evaluation provenance, requiring a real Modelo foreign key."""
    id_modelo: int = Field(gt=0)


def triad_ensemble_sha256(checkpoint_sha256s, weights, classes):
    """Digest of the ordered checkpoints, weights and classes of a whole composition."""
    import hashlib
    payload = json.dumps({'checkpoints': list(checkpoint_sha256s), 'weights': list(weights),
                          'classes': list(classes)}, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class TriadEvaluationIdentity(EvaluationProvenance):
    """Joint evaluation provenance of one exact composition version (no Modelo row)."""
    composition_id: int = Field(gt=0)
    composition_version: int = Field(ge=1)
    component_model_ids: list[int] = Field(min_length=3, max_length=3)
    checkpoint_sha256s: list[str] = Field(min_length=3, max_length=3)
    weights: list[float] = Field(min_length=3, max_length=3)

    @model_validator(mode='after')
    def validate_composition(self):
        if self.schema_version != 2:
            raise ValueError('Joint evaluation requires schema_version 2')
        if len(set(self.component_model_ids)) != 3 or any(i <= 0 for i in self.component_model_ids):
            raise ValueError('Three distinct component model ids are required')
        if any(re.fullmatch(r'[0-9a-f]{64}', value) is None for value in self.checkpoint_sha256s):
            raise ValueError('Invalid component checkpoint hash')
        if (any(not math.isfinite(w) or w < 0 for w in self.weights) or not any(self.weights)
                or not math.isclose(sum(self.weights), 1, rel_tol=0, abs_tol=1e-9)):
            raise ValueError('Invalid composition weights')
        if self.checkpoint_sha256 != triad_ensemble_sha256(
                self.checkpoint_sha256s, self.weights, self.classes):
            raise ValueError('Ensemble digest does not match its components')
        return self


def strict_json(value):
    """Reject non-JSON types/keys as well as NaN and infinity; detach input."""
    def check(item):
        if type(item) in (str, int, bool, type(None)):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError('Only finite strict JSON values and string keys are supported')
    check(value)
    return json.loads(json.dumps(value, allow_nan=False))


def validate_report(report, identity):
    """Validate versioned shape and algebra without expanding counts into samples."""
    report = strict_json(report)
    classes, count = identity.classes, identity.sample_count
    n = len(classes)
    version = identity.schema_version
    extra = {'prediction_columns', 'rejection'} if version == 2 else set()
    if type(report) is not dict or set(report) != extra | {
        'schema_version', 'classes', 'sample_count', 'metrics', 'per_class',
        'support', 'confusion_matrix', 'coverage'
    }:
        raise ValueError('Invalid report shape')
    if (type(report['schema_version']) is not int or report['schema_version'] != version or
            type(report['classes']) is not list or report['classes'] != classes or
            any(type(a) is not type(b) for a, b in zip(report['classes'], classes)) or
            type(report['sample_count']) is not int or report['sample_count'] != count):
        raise ValueError('Report identity/counts do not match evaluation')
    rejection_label = None
    if version == 2:
        rejection = report['rejection']
        if type(rejection) is not dict or set(rejection) != {'label', 'count', 'rate'}:
            raise ValueError('Invalid rejection shape')
        rejection_label = rejection['label']
        if (type(rejection_label) is not type(classes[0]) or
                isinstance(rejection_label, str) and not rejection_label.strip() or
                rejection_label in classes):
            raise ValueError('Invalid rejection label')
    matrix = report['confusion_matrix']
    if (type(matrix) is not list or len(matrix) != n or any(
            type(row) is not list or len(row) != n + (version == 2) or any(type(v) is not int or v < 0 for v in row)
            for row in matrix)):
        raise ValueError('Confusion matrix must contain aligned nonnegative integer counts')
    support = [sum(row) for row in matrix]
    if sum(support) != count:
        raise ValueError('Matrix count does not match sample_count')
    predicted = [sum(row[i] for row in matrix) for i in range(n)]
    rows = []
    for i, label in enumerate(classes):
        tp, actual, pred = matrix[i][i], support[i], predicted[i]
        rows.append(dict(label=label, precision=tp / pred if pred else 0.0,
                         recall=tp / actual if actual else 0.0,
                         f1=2 * tp / (actual + pred) if actual + pred else 0.0,
                         support=actual, zero_denominator=dict(
                             precision=pred == 0, recall=actual == 0, f1=actual + pred == 0)))
    metrics = {name + '_macro': sum(row[name] for row in rows) / n
               for name in ('precision', 'recall', 'f1')}
    metrics.update(accuracy=sum(matrix[i][i] for i in range(n)) / count,
                   f1_weighted=sum(row['f1'] * row['support'] for row in rows) / count,
                   balanced_accuracy=sum(row['recall'] for row in rows if row['support']) /
                   sum(bool(v) for v in support))
    absent = [c for c, s in zip(classes, support) if not s]
    expected = dict(schema_version=version, classes=classes, sample_count=count,
                    metrics=metrics, per_class=rows, support=support,
                    confusion_matrix=matrix, coverage=dict(absent_classes=absent, complete=not absent))

    if version == 2:
        rejected = sum(row[-1] for row in matrix)
        expected.update(prediction_columns=classes + [rejection_label],
                        rejection=dict(label=rejection_label, count=rejected, rate=rejected / count))

    def coherent(actual, wanted):
        if type(wanted) is float:
            return type(actual) in (int, float) and 0 <= actual <= 1 and math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-15)
        if type(actual) is not type(wanted):
            return False
        if type(wanted) is dict:
            return actual.keys() == wanted.keys() and all(coherent(actual[k], v) for k, v in wanted.items())
        if type(wanted) is list:
            return len(actual) == len(wanted) and all(coherent(a, b) for a, b in zip(actual, wanted))
        return actual == wanted
    if not coherent(report, expected):
        raise ValueError('Report rates/support/coverage are inconsistent with confusion matrix')
    return report
