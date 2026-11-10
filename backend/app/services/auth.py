"""Account/password helpers and the retained boot configuration contract."""
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.user import Usuario
from app.passwords import hash_password, verify_password

# The launcher still validates this operator setting; it no longer signs JWTs.
SECRET_KEY = os.getenv("JWT_SECRET_KEY")


class AuthenticationConfigurationError(RuntimeError):
    """Authentication cannot proceed with absent or unsafe operator configuration."""


def ensure_authentication_configured() -> None:
    """Validate boot configuration without issuing a browser credential."""
    try:
        key_bytes = SECRET_KEY.encode("utf-8") if isinstance(SECRET_KEY, str) else b""
    except UnicodeError as error:
        raise AuthenticationConfigurationError("Autenticación no configurada: JWT_SECRET_KEY inválida") from error
    if (not isinstance(SECRET_KEY, str) or not SECRET_KEY.strip()
            or len(key_bytes) < 32
            or SECRET_KEY == "fama_bioacoustic_secret_key_mlops_2026"):
        raise AuthenticationConfigurationError("Autenticación no configurada: JWT_SECRET_KEY ausente o insegura")


def get_user_by_email(db: Session, email: str) -> Optional[Usuario]:
    """Obtiene un usuario por su correo electrónico."""
    return db.query(Usuario).filter(Usuario.email == email.strip().lower()).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[Usuario]:
    """Obtiene un usuario por su identificador primario."""
    return db.query(Usuario).filter(Usuario.id == user_id).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[Usuario]:
    """Valida credenciales contra PostgreSQL y actualiza la marca de último acceso."""
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not user.activo:
        return None
    if not verify_password(password, user.password_hash):
        return None

    user.ultimo_acceso = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return user


def create_user(
    db: Session,
    email: str,
    password: str,
    nombre_completo: str,
    rol: str = "investigador",
    *, commit: bool = True,
) -> Usuario:
    """Create a user; trusted transactional callers can flush without committing."""
    email_clean = email.strip().lower()
    if get_user_by_email(db, email_clean):
        raise ValueError(f"El correo electrónico '{email_clean}' ya se encuentra registrado.")

    if rol not in ("administrador", "investigador"):
        raise ValueError(f"Rol inválido: '{rol}'. Solo se permite 'administrador' o 'investigador'.")

    user = Usuario(
        email=email_clean,
        password_hash=hash_password(password),
        nombre_completo=nombre_completo.strip(),
        rol=rol,
        activo=True,
    )
    db.add(user)
    if commit:
        db.commit()
        db.refresh(user)
    else:
        db.flush()
    return user


def seed_initial_admin(db: Session) -> Optional[Usuario]:
    """
    Crea el primer administrador solo con credenciales explícitas del operador.
    No modifica ni repara cuentas existentes cuando la tabla ya contiene usuarios.
    """
    total = db.query(Usuario).count()
    if total > 0:
        return db.query(Usuario).filter(Usuario.rol == "administrador").first()

    admin_email = os.getenv("ADMIN_INITIAL_EMAIL")
    admin_password = os.getenv("ADMIN_INITIAL_PASSWORD")
    if not admin_email or not admin_password:
        raise AuthenticationConfigurationError("Bootstrap no configurado: credenciales iniciales requeridas")
    admin_email = admin_email.strip().lower()
    if (admin_email.count("@") != 1 or not all(admin_email.split("@"))
            or len(admin_email) > 150 or any(char.isspace() for char in admin_email)
            or not admin_password.strip() or len(admin_password) < 12
            or admin_password == "AdminFama2026!"):
        raise AuthenticationConfigurationError("Bootstrap no configurado: credenciales iniciales inválidas o inseguras")
    admin_name = os.getenv("ADMIN_INITIAL_NAME", "Administrador F.A.M.A.")

    admin = Usuario(
        email=admin_email,
        password_hash=hash_password(admin_password),
        nombre_completo=admin_name,
        rol="administrador",
        activo=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"[Auth] Usuario administrador inicial creado exitosamente: {admin_email}")
    return admin
