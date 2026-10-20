import os
import json
import base64
import hmac
import hashlib
import secrets
import math
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import Usuario

# ============================================================================
# CONFIGURACIÓN CRIPTOGRÁFICA Y DE TOKENS (RNF_03, Tabla 6.2)
# ============================================================================
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))  # 8 horas por defecto

security_bearer = HTTPBearer(auto_error=False)


class AuthenticationConfigurationError(RuntimeError):
    """Authentication cannot proceed with absent or unsafe operator configuration."""


def ensure_authentication_configured() -> None:
    """Validate before credential verification or session-related DB writes."""
    try:
        key_bytes = SECRET_KEY.encode("utf-8") if isinstance(SECRET_KEY, str) else b""
    except UnicodeError as error:
        raise AuthenticationConfigurationError("Autenticación no configurada: JWT_SECRET_KEY inválida") from error
    if (not isinstance(SECRET_KEY, str) or not SECRET_KEY.strip()
            or len(key_bytes) < 32
            or SECRET_KEY == "fama_bioacoustic_secret_key_mlops_2026"):
        raise AuthenticationConfigurationError("Autenticación no configurada: JWT_SECRET_KEY ausente o insegura")


def _signing_key() -> bytes:
    ensure_authentication_configured()
    return SECRET_KEY.encode("utf-8")


# ============================================================================
# HASH Y VERIFICACIÓN DE CONTRASEÑAS (PBKDF2-HMAC-SHA256 con Salt aleatorio)
# ============================================================================
def hash_password(password: str) -> str:
    """Genera un hash criptográfico seguro con sal usando PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(16)
    iterations = 600000
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si la contraseña plana coincide con el hash almacenado en tiempo constante."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_hash = bytes.fromhex(parts[3])
        computed_hash = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(expected_hash, computed_hash)
    except Exception:
        return False


# ============================================================================
# GENERACIÓN Y VALIDACIÓN DE TOKENS JWT (RFC 7519)
# ============================================================================
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Genera un token JWT firmado criptográficamente con HMAC-SHA256."""
    header = {"alg": ALGORITHM, "typ": "JWT"}
    payload = data.copy()

    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    payload["exp"] = int(expire.timestamp())
    payload["iat"] = int(now.timestamp())

    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    header_b64 = _b64url_encode(header_bytes)
    payload_b64 = _b64url_encode(payload_bytes)

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(_signing_key(), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_access_token(token: str) -> dict:
    """Decodifica y valida la firma y vigencia de un token JWT."""
    parts = token.split(".")
    if len(parts) != 3 or any(re.fullmatch(r"[A-Za-z0-9_-]+", part) is None for part in parts):
        raise ValueError("Token inválido: formato no corresponde a JWT")

    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(_signing_key(), signing_input, hashlib.sha256).digest()
    expected_sig_b64 = _b64url_encode(expected_sig)

    if not hmac.compare_digest(signature_b64, expected_sig_b64):
        raise ValueError("Firma de token inválida")

    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Cabecera JWT inválida") from exc
    if not isinstance(header, dict) or header.get("alg") != ALGORITHM:
        raise ValueError("Algoritmo JWT no permitido")

    try:
        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
    except Exception as exc:
        raise ValueError("Carga útil del token corrupta") from exc

    if not isinstance(payload, dict):
        raise ValueError("Carga útil JWT inválida: se requiere un objeto")
    if "exp" not in payload:
        raise ValueError("Token inválido: expiración requerida")
    expiration = payload["exp"]
    if (type(expiration) not in (int, float)
            or (isinstance(expiration, float) and not math.isfinite(expiration))):
        raise ValueError("Token inválido: expiración numérica finita requerida")
    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts >= expiration:
        raise ValueError("Token expirado")

    return payload


# ============================================================================
# GESTIÓN Y PERSISTENCIA DE USUARIOS (CU_SES_01 / CU_ADM_01)
# ============================================================================
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
    return user


def create_user(
    db: Session,
    email: str,
    password: str,
    nombre_completo: str,
    rol: str = "investigador",
) -> Usuario:
    """Crea y persiste un nuevo usuario asegurando el hash de contraseña y unicidad de email."""
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
    db.commit()
    db.refresh(user)
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


# ============================================================================
# DEPENDENCIAS FASTAPI: AUTENTICACIÓN Y CONTROL DE ACCESO BASADO EN ROLES (RBAC)
# ============================================================================
def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    """Extrae y valida el usuario activo a partir del Bearer token en la cabecera Authorization."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida. Token no provisto.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except AuthenticationConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de autenticación no configurado.",
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token inválido o expirado: {err}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_raw = payload.get("sub")
    user_id = None
    if isinstance(user_id_raw, str) and user_id_raw.isascii() and user_id_raw.isdecimal():
        try:
            user_id = int(user_id_raw)
        except ValueError:
            pass
    # Usuario.id is PostgreSQL INTEGER (signed 32-bit), not an arbitrary integer.
    if user_id is None or not 1 <= user_id <= 2 ** 31 - 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no contiene sujeto de usuario válido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario asociado al token no existe.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La cuenta de usuario se encuentra inactiva.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_roles(allowed_roles: List[str]):
    """Generador de dependencias para proteger endpoints según roles permitidos."""
    def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        if current_user.rol not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado. Se requiere uno de los siguientes roles: {allowed_roles}",
            )
        return current_user
    return role_checker
