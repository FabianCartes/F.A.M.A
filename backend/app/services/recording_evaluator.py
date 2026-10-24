"""Recording-level evaluation of an admitted snapshot, without publication effects."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import librosa
import numpy as np

from app.schemas.evaluation import EvaluationIdentity, EvaluationProvenance, validate_report
from ml_core.classification_metrics import calculate_classification_report

EVALUATOR_VERSION = 'recording-v1'
REJECTION_LABEL = '__recording_rejected__'


@dataclass(frozen=True)
class LabelledRecording:
    """Canonical admitted reference; id/group belong to the dataset, not windows."""
    identity: str
    label: str
    path: Path
    reference: str
    stage: str
    group: str | None = None


def validate_recording_splits(splits):
    """Reject membership/group/path overlap before training; no inference."""
    if set(splits) != {'train', 'val', 'test'}:
        raise ValueError('Exactly train/val/test splits required')
    seen_ids, seen_groups, seen_paths = set(), set(), set()
    for name in ('train', 'val', 'test'):
        records = tuple(splits[name])
        if not records:
            raise ValueError('Every split must contain recordings')
        ids = {r.identity for r in records}
        groups = {r.group for r in records if r.group is not None}
        paths = {r.path.resolve() for r in records}
        if len(ids) != len(records) or len(paths) != len(records):
            raise ValueError('Duplicate recording membership')
        if ids & seen_ids or groups & seen_groups or paths & seen_paths:
            raise ValueError('Recording splits overlap')
        seen_ids.update(ids)
        seen_groups.update(groups)
        seen_paths.update(paths)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class RecordingEvaluator:
    """Preflight then evaluate once per recording using the supplied predictor.

    Construction freezes membership, classes, configs and audio hashes, decodes
    every audio locally, and exposes `identity` for a pending persistence attempt.
    evaluate() returns a schema-2 report or raises; it never persists or activates.
    Caller must supply the *effective* published predictor configs, not substitute
    training configs. This helper does not attest that supplied provenance is true.
    Hash-before/after detects ordinary mutation, not malicious change-and-restore.
    """
    def __init__(self, recordings, predictor, *, id_modelo=None, dataset, split,
                 checkpoint_sha256, predictor_config, preprocessing_config,
                 aggregation_config, code_revision=None):
        self._records = tuple(recordings)
        self._predictor = predictor
        self._classes = list(predictor.classes)
        if REJECTION_LABEL in self._classes:
            raise ValueError('Reserved rejection sentinel cannot be a real class')
        manifest = []
        identities = set()
        if not self._records:
            raise ValueError('Recording snapshot must be nonempty')
        for record in self._records:
            if not isinstance(record, LabelledRecording):
                raise ValueError('Expected immutable LabelledRecording inputs')
            if any(type(v) is not str or not v.strip() for v in
                   (record.identity, record.reference, record.stage, record.label)):
                raise ValueError('Recording identity/reference/stage/label must be nonblank strings')
            if record.group is not None and (type(record.group) is not str or not record.group.strip()):
                raise ValueError('Known group must be a nonblank string')
            if record.identity in identities:
                raise ValueError('Duplicate admitted recording identity')
            identities.add(record.identity)
            if record.label not in self._classes:
                raise ValueError('Unknown true label')
            if not isinstance(record.path, Path) or not record.path.is_file():
                raise ValueError('Recording path must be an existing regular file')
            before = _sha256(record.path)
            samples, sr = librosa.load(record.path, sr=None, mono=True)
            if sr <= 0 or not samples.size or not np.isfinite(samples).all():
                raise ValueError('Recording must decode to nonempty finite audio')
            if _sha256(record.path) != before:
                raise ValueError('Audio changed during preflight')
            manifest.append(dict(identity=record.identity, label=record.label,
                                 reference=record.reference, stage=record.stage,
                                 group=record.group, audio_sha256=before))
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode('utf-8')
        self._hashes = tuple(row['audio_sha256'] for row in manifest)
        provenance_type = EvaluationIdentity if id_modelo is not None else EvaluationProvenance
        provenance_fields = ({"id_modelo": id_modelo} if id_modelo is not None else {})
        self.identity = provenance_type(
            **provenance_fields, schema_version=2, evaluator_version=EVALUATOR_VERSION,
            checkpoint_sha256=checkpoint_sha256, dataset=dataset, split=split,
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            classes=self._classes, sample_count=len(self._records),
            predictor_config=predictor_config, preprocessing_config=preprocessing_config,
            aggregation_config=aggregation_config, code_revision=code_revision)
        # Detach dictionaries from caller-owned mutable configuration.
        self.identity = provenance_type.model_validate_json(self.identity.model_dump_json())

    def evaluate(self):
        if list(self._predictor.classes) != self._classes:
            raise ValueError('Predictor classes changed after admission')
        predicted = []
        for record, expected_hash in zip(self._records, self._hashes):
            if _sha256(record.path) != expected_hash:
                raise ValueError('Audio changed after admission')
            output = self._predictor.predict(record.path)
            if _sha256(record.path) != expected_hash:
                raise ValueError('Audio changed during inference')
            status = output.detalles.get('status')
            if status in ('silence', 'noise'):
                predicted.append(REJECTION_LABEL)
            elif status in ('classified', 'bundle_classified', 'classified_super_ensemble') and type(output.clase) is str and output.clase in self._classes:
                predicted.append(output.clase)
            else:
                raise ValueError('Unknown predictor output/status')
        report = calculate_classification_report(
            [r.label for r in self._records], predicted, self._classes,
            rejection_label=REJECTION_LABEL)
        return validate_report(report, self.identity)
