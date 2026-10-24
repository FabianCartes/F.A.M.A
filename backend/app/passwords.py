"""Contraseñas de cuentas, sin depender de conexiones o configuración del nodo."""
import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 600000
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        computed = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), bytes.fromhex(parts[2]), int(parts[1]))
        return hmac.compare_digest(bytes.fromhex(parts[3]), computed)
    except Exception:
        return False
