"""Account invariants and session revocation in a single database transaction."""
import hashlib
import time
import secrets

from fastapi import HTTPException
from sqlalchemy import text

from app.models.user import Usuario
from app.models.web_session import SesionWeb
from app.models.password_reset import RecuperacionCuenta
from app.services.web_sessions import settings
from app.services.auth import hash_password, verify_password, create_user
from app.services.security_audit import record_event


def lock_accounts(db):
    # No process-local mutex: all writers share this transaction gate. Both
    # PostgreSQL and SQLite serialize this write, including first-use insertion.
    db.execute(text("INSERT INTO control_cuentas (id) VALUES (1) ON CONFLICT (id) DO NOTHING"))
    db.execute(text("UPDATE control_cuentas SET id = id WHERE id = 1"))


def account_mutation(db, request, actor_id, *, administrator=False):
    lock_accounts(db)
    actor = db.query(Usuario).populate_existing().filter_by(id=actor_id).first()
    token = request.cookies.get(settings().cookie, "")
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    session = db.query(SesionWeb).populate_existing().filter(
        SesionWeb.token_hash == digest, SesionWeb.id_usuario == actor_id,
        SesionWeb.expira_en > now, SesionWeb.inactiva_en > now,
    ).first()
    if actor is None or not actor.activo or session is None:
        raise HTTPException(401, "Sesión requerida o expirada.")
    if administrator and actor.rol != "administrador":
        raise HTTPException(403, "Se requiere un administrador.")
    return actor


def target_user(db, user_id):
    user = db.query(Usuario).populate_existing().filter_by(id=user_id).first()
    if user is None:
        raise HTTPException(404, "Usuario no encontrado.")
    return user


def revoke_sessions(db, user_id):
    db.query(SesionWeb).filter_by(id_usuario=user_id).delete(synchronize_session=False)


def revoke_credentials(db, user_id):
    revoke_sessions(db, user_id)
    db.query(RecuperacionCuenta).filter_by(id_usuario=user_id).delete(synchronize_session=False)


def update_account(db, request, actor_id, user_id, changes):
    account_mutation(db, request, actor_id, administrator=True)
    user = target_user(db, user_id)
    stays_administrator = changes.get("activo", user.activo) and changes.get("rol", user.rol) == "administrador"
    if user.activo and user.rol == "administrador" and not stays_administrator:
        count = db.query(Usuario).filter_by(activo=True, rol="administrador").count()
        if count <= 1:
            for key in ("rol", "activo"):
                if key in changes and changes[key] != getattr(user, key):
                    action = "account.role_changed" if key == "rol" else "account.suspended"
                    record_event(db, action, "denied", actor_id=actor_id, subject_user_id=user_id)
            db.commit()
            raise HTTPException(409, "Debe conservarse al menos un administrador activo.")
    sensitive = any(key in changes and changes[key] != getattr(user, key) for key in ("activo", "rol"))
    for key, value in changes.items():
        if value != getattr(user, key):
            action = {"nombre_completo": "account.name_updated", "rol": "account.role_changed",
                      "activo": "account.reactivated" if value else "account.suspended"}[key]
            record_event(db, action, "success", actor_id=actor_id, subject_user_id=user_id)
        setattr(user, key, value)
    if sensitive:
        revoke_credentials(db, user_id)
    db.commit()
    db.refresh(user)
    return user


def create_account(db, request, actor_id, **fields):
    account_mutation(db, request, actor_id, administrator=True)
    user = create_user(db=db, commit=False, **fields)
    record_event(db, "account.created", "success", actor_id=actor_id, subject_user_id=user.id)
    db.commit()
    db.refresh(user)
    return user


def change_password(db, request, actor_id, current_password, new_password):
    user = account_mutation(db, request, actor_id)
    if not verify_password(current_password, user.password_hash):
        record_event(db, "account.password_changed", "denied", actor_id=user.id, subject_user_id=user.id)
        db.commit()
        raise HTTPException(400, "Contraseña actual incorrecta.")
    user.password_hash = hash_password(new_password)
    revoke_credentials(db, user.id)
    record_event(db, "account.password_changed", "success", actor_id=user.id, subject_user_id=user.id)
    db.commit()


def issue_password_reset(db, request, actor_id, user_id):
    account_mutation(db, request, actor_id, administrator=True)
    user = target_user(db, user_id)
    if not user.activo:
        record_event(db, "account.recovery_issued", "denied", actor_id=actor_id, subject_user_id=user_id)
        db.commit()
        raise HTTPException(409, "La cuenta debe estar activa para iniciar recuperación.")
    token = secrets.token_urlsafe(32)
    db.query(RecuperacionCuenta).filter_by(id_usuario=user_id).delete(synchronize_session=False)
    db.add(RecuperacionCuenta(id_usuario=user_id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                             expira_en=int(time.time()) + 900))
    revoke_sessions(db, user_id)
    record_event(db, "account.recovery_issued", "success", actor_id=actor_id, subject_user_id=user_id)
    db.commit()
    return {"reset_url": f"{settings().origin}/reset-password#token={token}", "expires_in": 900}


def reset_password(db, token, new_password):
    lock_accounts(db)
    row = db.query(RecuperacionCuenta).filter(
        RecuperacionCuenta.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        RecuperacionCuenta.expira_en > int(time.time()),
    ).first()
    user = db.query(Usuario).populate_existing().filter_by(id=row.id_usuario).first() if row else None
    if user is None or not user.activo:
        record_event(db, "account.password_reset", "denied")
        db.commit()
        raise HTTPException(400, "Recuperación inválida o expirada.")
    user.password_hash = hash_password(new_password)
    revoke_sessions(db, user.id)
    db.delete(row)
    record_event(db, "account.password_reset", "success", subject_user_id=user.id)
    db.commit()
