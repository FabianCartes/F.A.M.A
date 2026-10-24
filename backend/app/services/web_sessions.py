"""Web identity behind a cookie interface; no JWT or browser-stored bearer tokens."""
import hashlib
import secrets
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import Usuario
from app.models.web_session import SesionWeb
from app.services.auth import get_user_by_email, verify_password
from app.services.security_audit import record_event


from app.web_settings import WebSessionSettings, settings


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


def trusted_web_request(request: Request) -> WebSessionSettings:
    config = settings()
    origin = request.headers.get("origin")
    # Reads carrying a browser Origin must not inherit permissive CORS access
    # merely because the browser also holds an administrator's cookie.
    if origin is not None or request.method not in ("GET", "HEAD", "OPTIONS"):
        if origin != config.origin:
            raise HTTPException(403, "Origen de solicitud no permitido.")
    return config


def start_session(db: Session, user: Usuario, request: Request, response: Response, config: WebSessionSettings):
    revoke_browser_session(db, request, config)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.add(SesionWeb(token_hash=hashlib.sha256(token.encode()).hexdigest(), id_usuario=user.id,
                     expira_en=now + config.lifetime, inactiva_en=now + config.idle))
    record_event(db, "session.login", "success", actor_id=user.id, subject_user_id=user.id)
    db.commit()
    response.set_cookie(config.cookie, token, max_age=config.lifetime, httponly=True,
                        secure=config.secure, samesite="strict", path="/")
    no_store(response)


def authenticate_web_user(db, email, password):
    user = get_user_by_email(db, email)
    if user is None or not user.activo:
        return None
    accepted_hash = user.password_hash
    if not verify_password(password, accepted_hash):
        return None
    # Credential verification and session creation share one transaction. The
    # conditional write locks the user row and rejects a password/suspension
    # change that committed while password verification was running.
    matched = db.query(Usuario).filter(Usuario.id == user.id, Usuario.activo.is_(True),
                                      Usuario.password_hash == accepted_hash).update(
        {Usuario.ultimo_acceso: datetime.now(timezone.utc)}, synchronize_session=False)
    if matched != 1:
        db.rollback()
        return None
    db.refresh(user)
    return user


def revoke_browser_session(db: Session, request: Request, config: WebSessionSettings):
    token = request.cookies.get(config.cookie, "")
    if len(token) == 43:
        db.query(SesionWeb).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).delete()


def end_session(request: Request, response: Response, db: Session):
    config = trusted_web_request(request)
    revoke_browser_session(db, request, config)
    db.commit()
    response.delete_cookie(config.cookie, path="/", secure=config.secure, httponly=True, samesite="strict")
    no_store(response)


def current_web_user(request: Request, response: Response, db: Session = Depends(get_db)) -> Usuario:
    config = trusted_web_request(request)
    no_store(response)
    token = request.cookies.get(config.cookie, "")
    if len(token) != 43:
        raise HTTPException(401, "Sesión requerida o expirada.")
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    session = db.get(SesionWeb, digest)
    if session is None or now >= session.expira_en or now >= session.inactiva_en:
        raise HTTPException(401, "Sesión requerida o expirada.")
    user = db.get(Usuario, session.id_usuario)
    if user is None or not user.activo:
        raise HTTPException(401, "Sesión requerida o expirada.")
    db.query(SesionWeb).filter(SesionWeb.token_hash == digest).update({
        SesionWeb.inactiva_en: min(session.expira_en, now + config.idle),
    })
    db.commit()
    return user


def web_administrator(user: Usuario = Depends(current_web_user)) -> Usuario:
    if user.rol != "administrador":
        raise HTTPException(403, "Se requiere un administrador.")
    return user
