"""Joint evaluation attempts of standard triad compositions; no training or activation effects.

An attempt belongs to one exact composition version: its ordered components, their
checkpoint hashes and its weights. Revising weights creates another composition, so a
report is never inherited. Reads never run inference.
"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update

from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo
from app.models.triad_composition import TriadComposition, TriadCompositionEvaluation
from app.schemas.evaluation import TriadEvaluationIdentity, strict_json, triad_ensemble_sha256, validate_report
from app.services.recording_evaluator import RecordingEvaluator
from app.services.triad_compositions import component_ids, component_weights

__all__ = ["TriadEvaluationService", "evaluate_composition", "triad_ensemble_sha256"]


class TriadEvaluationService:
    """Each mutation commits, rolling back on error; supply a dedicated session.

    create(identity), start(id), complete(id, report), fail(id, reason), read(id) return
    detached JSON-compatible dictionaries; latest_by_split(composition_ids) returns the
    newest attempt per split. Invalid identities or transitions raise ValueError.
    """

    def __init__(self, session):
        self.session = session

    def create(self, identity):
        try:
            identity = TriadEvaluationIdentity.model_validate(identity)
            self._require_current_identity(identity)
            row = TriadCompositionEvaluation(**strict_json(identity.model_dump()), status="pending",
                                             created_at=datetime.now(timezone.utc))
            self.session.add(row)
            self.session.commit()
            return self.read(row.id)
        except Exception:
            self.session.rollback()
            raise

    def read(self, attempt_id):
        row = self.session.get(TriadCompositionEvaluation, attempt_id, populate_existing=True)
        return None if row is None else _serialize(row)

    def latest_by_split(self, composition_ids):
        """``{composition_id: {split: attempt}}`` with the newest attempt of each split."""
        ids = list(composition_ids)
        if not ids:
            return {}
        result = {}
        rows = (self.session.query(TriadCompositionEvaluation)
                .filter(TriadCompositionEvaluation.composition_id.in_(ids))
                .order_by(TriadCompositionEvaluation.id).all())
        for row in rows:
            result.setdefault(row.composition_id, {})[row.split] = _serialize(row)
        return result

    def start(self, attempt_id):
        return self._transition(attempt_id, ("pending",), status="running", started_at=datetime.now(timezone.utc))

    def complete(self, attempt_id, report):
        try:
            row = self.read(attempt_id)
            if row is None:
                raise ValueError("Evaluation does not exist")
            identity = TriadEvaluationIdentity.model_validate(
                {key: row[key] for key in TriadEvaluationIdentity.model_fields})
            self._require_current_identity(identity)
            report = validate_report(report, identity)
            return self._transition(attempt_id, ("running",), status="completed", report=report,
                                    finished_at=datetime.now(timezone.utc))
        except Exception:
            self.session.rollback()
            raise

    def fail(self, attempt_id, reason):
        if type(reason) is not str or not reason.strip() or len(reason) > 2000:
            self.session.rollback()
            raise ValueError("Failure requires a nonblank reason of at most 2000 characters")
        return self._transition(attempt_id, ("pending", "running"), status="failed", error_reason=reason,
                                finished_at=datetime.now(timezone.utc))

    def _require_current_identity(self, identity):
        composition = self.session.get(TriadComposition, identity.composition_id)
        if composition is None:
            raise ValueError("Evaluation requires an existing composition")
        if (composition.version != identity.composition_version
                or list(component_ids(composition)) != identity.component_model_ids
                or list(component_weights(composition)) != identity.weights):
            raise ValueError("Evaluation identity does not match the stored composition")
        dataset = self.session.get(ConjuntoDatos, composition.dataset_id)
        if dataset is None or dataset.nombre != identity.dataset:
            raise ValueError("Evaluation dataset does not match the composition")
        for model_id, digest in zip(identity.component_model_ids, identity.checkpoint_sha256s):
            model = self.session.get(Modelo, model_id)
            stored = getattr(model, "hash_binario", None)
            if not isinstance(stored, str) or stored.lower() != digest:
                raise ValueError("Component checkpoint hash does not match the registered model")

    def _transition(self, attempt_id, allowed, **changes):
        try:
            # Conditional write also rejects competing/stale transitions.
            result = self.session.execute(update(TriadCompositionEvaluation).where(
                TriadCompositionEvaluation.id == attempt_id,
                TriadCompositionEvaluation.status.in_(allowed)).values(**changes))
            if result.rowcount != 1:
                raise ValueError("Illegal evaluation transition or missing evaluation")
            self.session.commit()
            return self.read(attempt_id)
        except Exception:
            self.session.rollback()
            raise


def _serialize(row):
    result = {str(column.name): getattr(row, column.name) for column in row.__table__.columns}
    for name in ("created_at", "started_at", "finished_at"):
        value = result[name]
        if value is not None:
            result[name] = (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
    return strict_json(result)


def evaluate_composition(session_factory, composition_id, *, predictor, checkpoint_paths, recordings,
                         component_configs, code_revision=None):
    """Evaluate the fused output of one stored composition on its admitted val/test recordings.

    ``predictor`` is the composition's ``TriadPredictor``; ``component_configs`` holds the
    effective ``(predictor, preprocessing, aggregation)`` configs of each ordered component.
    Identity is checked before any attempt exists; afterwards every failure marks the open
    attempts ``failed`` and is re-raised. Completed attempts, checkpoints, composition rows
    and activation are never changed. Returns ``{split: attempt}``.
    """
    paths = [Path(path) for path in checkpoint_paths]
    configs = [tuple(config) for config in component_configs]
    if len(paths) != 3 or len(configs) != 3 or any(len(config) != 3 for config in configs):
        raise ValueError("Joint evaluation requires three checkpoints and three component configs")
    with session_factory() as db:
        composition = db.get(TriadComposition, composition_id)
        if composition is None:
            raise ValueError("Evaluation requires an existing composition")
        ids, weights = list(component_ids(composition)), list(component_weights(composition))
        version = composition.version
        dataset = db.get(ConjuntoDatos, composition.dataset_id).nombre
        stored = [getattr(db.get(Modelo, model_id), "hash_binario", None) for model_id in ids]
    if [component.model_id for component in predictor.components] != [str(model_id) for model_id in ids]:
        raise ValueError("Predictor components do not match the composition order")
    if list(predictor.weights) != weights:
        raise ValueError("Predictor weights do not match the composition")
    hashes = [_file_sha256(path) for path in paths]
    if [value.lower() if isinstance(value, str) else value for value in stored] != hashes:
        raise ValueError("Checkpoint changed since component registration")
    verified = _IdentityCheckedTriad(predictor, hashes)
    composition_fields = dict(composition_id=composition_id, composition_version=version,
                              component_model_ids=ids, checkpoint_sha256s=hashes, weights=weights)
    evaluators = {split: RecordingEvaluator(
        recordings[split], verified, dataset=dataset, split=split,
        checkpoint_sha256=triad_ensemble_sha256(hashes, weights, list(predictor.classes)),
        predictor_config={"components": [config[0] for config in configs]},
        preprocessing_config={"components": [config[1] for config in configs]},
        aggregation_config={"components": [config[2] for config in configs]},
        code_revision=code_revision) for split in ("val", "test")}
    attempts = {}
    with session_factory() as db:
        service = TriadEvaluationService(db)
        try:
            for split, evaluator in evaluators.items():
                attempts[split] = service.create({**evaluator.identity.model_dump(), **composition_fields})
            for split, evaluator in evaluators.items():
                service.start(attempts[split]["id"])
                report = evaluator.evaluate()
                if [_file_sha256(path) for path in paths] != hashes:
                    raise ValueError("Checkpoint changed during joint inference")
                attempts[split] = service.complete(attempts[split]["id"], report)
        except Exception as error:
            reason = (str(error).strip() or type(error).__name__)[:2000]
            for split, attempt in attempts.items():
                if service.read(attempt["id"])["status"] in ("pending", "running"):
                    attempts[split] = service.fail(attempt["id"], reason)
            raise
    return attempts


class _IdentityCheckedTriad:
    """Refuse a fused output whose loaded checkpoints differ from the admitted hashes."""

    def __init__(self, predictor, hashes):
        self._predictor = predictor
        self._hashes = list(hashes)
        self.classes = predictor.classes

    def predict(self, path):
        output = self._predictor.predict(path)
        loaded = output.detalles.get("loaded_checkpoint_sha256s")
        if output.detalles.get("status") == "classified" and list(loaded or ()) != self._hashes:
            raise ValueError("Loaded checkpoints differ from the admitted composition")
        return output


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
