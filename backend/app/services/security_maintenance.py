"""Explicit bounded maintenance; no filesystem, cloud or background scheduler."""
import os
import time

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models.web_session import SesionWeb
from app.models.password_reset import RecuperacionCuenta
from app.models.access_quota import CuotaAcceso
from app.models.security_audit import EventoSeguridad
from app.services.accounts import account_mutation
from app.services.security_audit import record_event


def retention_days():
    try:
        days = int(os.getenv("FAMA_AUDIT_RETENTION_DAYS", "90"))
        if not 1 <= days <= 3650:
            raise ValueError
        return days
    except ValueError:
        raise HTTPException(503, "Retención de auditoría no configurada correctamente.") from None


def cleanup(db, request, actor_id, batch_size):
    days = retention_days()
    account_mutation(db, request, actor_id, administrator=True)
    now = int(time.time())
    groups = (
        ("sessions", SesionWeb, SesionWeb.token_hash,
         or_(SesionWeb.expira_en <= now, SesionWeb.inactiva_en <= now)),
        ("recoveries", RecuperacionCuenta, RecuperacionCuenta.id_usuario, RecuperacionCuenta.expira_en <= now),
        ("quotas", CuotaAcceso, CuotaAcceso.clave_hash, CuotaAcceso.expira_en <= now),
        ("audit", EventoSeguridad, EventoSeguridad.id, EventoSeguridad.occurred_at <= now - days * 86400),
    )
    counts = {}
    has_more = False
    for name, model, identifier, expired in groups:
        candidates = db.query(identifier).filter(expired).order_by(identifier).limit(batch_size).subquery()
        # Recheck expiry in the DELETE as well as candidate selection: a quota
        # or recovery renewed by another request must not lose its new window.
        counts[name] = db.query(model).filter(
            expired, identifier.in_(select(candidates.c[identifier.key])),
        ).delete(synchronize_session=False)
        has_more = has_more or db.query(identifier).filter(expired).first() is not None
    record_event(db, "security.cleanup", "success", actor_id=actor_id)
    db.commit()
    return {"batch_size": batch_size, "deleted": counts, "has_more": has_more}
