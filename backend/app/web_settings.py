"""Configuración de sesiones, utilizable antes de abrir la base o cargar modelos."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit
from fastapi import HTTPException


@dataclass(frozen=True)
class WebSessionSettings:
    origin: str
    secure: bool
    lifetime: int
    idle: int

    @property
    def cookie(self):
        return "__Host-fama_session" if self.secure else "fama_session_dev"


def settings(values=None) -> WebSessionSettings:
    """Explicit origin; HTTP is opt-in and restricted to loopback development."""
    values = os.environ if values is None else values
    try:
        origin = values["FAMA_WEB_ORIGIN"]
        parsed = urlsplit(origin)
        secure = parsed.scheme == "https"
        loopback = (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
                    and values.get("FAMA_ALLOW_INSECURE_LOOPBACK") == "1")
        if (not (secure or loopback) or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or origin != origin.strip()):
            raise ValueError
        # Accessing port also rejects malformed or out-of-range ports.
        parsed.port
        lifetime = int(values.get("FAMA_SESSION_MAX_AGE_SECONDS", "28800"))
        idle = int(values.get("FAMA_SESSION_IDLE_SECONDS", "1800"))
        if not 1 <= idle <= lifetime <= 2678400:
            raise ValueError
        return WebSessionSettings(origin, secure, lifetime, idle)
    except (KeyError, ValueError):
        raise HTTPException(503, "Sesión web no configurada.") from None

