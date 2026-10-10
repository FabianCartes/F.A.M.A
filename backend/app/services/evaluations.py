"""Small session-injected persistence interface; no training or activation effects."""
from datetime import datetime, timezone

from sqlalchemy import update

from app.models.training import ModelEvaluation, Modelo
from app.schemas.evaluation import EvaluationIdentity, strict_json, validate_report


class EvaluationService:
    """Each mutation commits, rolling back on error; supply a dedicated session.

    create(identity), start(id), complete(id, report), fail(id, reason), read(id)
    return detached JSON-compatible dictionaries. Missing read returns None;
    invalid identities/transitions raise ValueError. Retry by create, never reset.
    """
    def __init__(self, session):
        self.session = session

    def create(self, identity):
        try:
            identity = EvaluationIdentity.model_validate(identity)
            if self.session.get(Modelo, identity.id_modelo) is None:
                raise ValueError('Evaluation requires an existing model identity')
            row = ModelEvaluation(**strict_json(identity.model_dump()), status='pending',
                                  created_at=datetime.now(timezone.utc))
            self.session.add(row)
            self.session.commit()
            return self.read(row.id_evaluation)
        except Exception:
            self.session.rollback()
            raise

    def read(self, evaluation_id):
        row = self.session.get(ModelEvaluation, evaluation_id, populate_existing=True)
        if row is None:
            return None
        result = {str(c.name): getattr(row, c.name) for c in row.__table__.columns}
        for name in ('created_at', 'started_at', 'finished_at'):
            value = result[name]
            if value is not None:
                result[name] = value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()
        return strict_json(result)

    def start(self, evaluation_id):
        return self._transition(evaluation_id, ('pending',), status='running',
                                started_at=datetime.now(timezone.utc))

    def complete(self, evaluation_id, report):
        try:
            row = self.read(evaluation_id)
            if row is None:
                raise ValueError('Evaluation does not exist')
            identity = EvaluationIdentity.model_validate({k: row[k] for k in EvaluationIdentity.model_fields})
            if self.session.get(Modelo, identity.id_modelo) is None:
                raise ValueError('Model identity no longer exists')
            report = validate_report(report, identity)
            return self._transition(evaluation_id, ('running',), status='completed',
                                    report=report, finished_at=datetime.now(timezone.utc))
        except Exception:
            self.session.rollback()
            raise

    def fail(self, evaluation_id, reason):
        if type(reason) is not str or not reason.strip() or len(reason) > 2000:
            self.session.rollback()
            raise ValueError('Failure requires a nonblank reason of at most 2000 characters')
        return self._transition(evaluation_id, ('pending', 'running'), status='failed',
                                error_reason=reason, finished_at=datetime.now(timezone.utc))

    def _transition(self, evaluation_id, allowed, **changes):
        try:
            # Conditional write also rejects competing/stale transitions.
            result = self.session.execute(update(ModelEvaluation).where(
                ModelEvaluation.id_evaluation == evaluation_id,
                ModelEvaluation.status.in_(allowed)).values(**changes))
            if result.rowcount != 1:
                raise ValueError('Illegal evaluation transition or missing evaluation')
            self.session.commit()
            return self.read(evaluation_id)
        except Exception:
            self.session.rollback()
            raise
