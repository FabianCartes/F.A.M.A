"""A closed event vocabulary; transaction ownership stays with the caller."""
import time

from app.models.security_audit import EventoSeguridad


ACTIONS = {"session.login", "account.created", "account.name_updated", "account.role_changed",
           "account.suspended", "account.reactivated", "account.recovery_issued",
           "account.password_reset", "account.password_changed", "assignment.granted", "assignment.revoked",
           "security.cleanup", "dataset.requested", "dataset.request_approved", "dataset.request_rejected",
           "dataset.audio_uploaded", "account.operator_recovered", "account.operator_adopted"}


def record_event(db, action, outcome, *, actor_id=None, subject_user_id=None, dataset_id=None):
    if action not in ACTIONS or outcome not in {"success", "denied"}:
        raise ValueError("Evento de seguridad no permitido")
    if any(value is not None and (type(value) is not int or not 1 <= value <= 2 ** 31 - 1)
           for value in (actor_id, subject_user_id, dataset_id)):
        raise ValueError("Identificadores de auditoría inválidos")
    db.add(EventoSeguridad(occurred_at=int(time.time()), action=action, outcome=outcome,
                          actor_id=actor_id, subject_user_id=subject_user_id, dataset_id=dataset_id))


def recent_events(db, limit, before_id):
    query = db.query(EventoSeguridad)
    if before_id is not None:
        query = query.filter(EventoSeguridad.id < before_id)
    rows = query.order_by(EventoSeguridad.id.desc()).limit(limit + 1).all()
    visible = rows[:limit]
    return {"events": visible, "next_before_id": visible[-1].id if len(rows) > limit else None}
