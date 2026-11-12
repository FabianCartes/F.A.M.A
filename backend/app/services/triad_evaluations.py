"""Joint evaluation attempts of standard triad compositions; no training or activation effects.

An attempt belongs to one exact composition version: its ordered components, their
checkpoint hashes and its weights. Revising weights creates another composition, so a
report is never inherited. Reads never run inference.
"""
from datetime import datetime, timezone

from sqlalchemy import update

from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo
from app.models.triad_composition import TriadComposition, TriadCompositionEvaluation
from app.schemas.evaluation import TriadEvaluationIdentity, strict_json, triad_ensemble_sha256, validate_report
from app.services.triad_compositions import component_ids, component_weights

__all__ = ["TriadEvaluationService", "triad_ensemble_sha256"]


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
