"""DB-backed fixed-window admission, committed before credential work."""
import hashlib
import hmac
import os
import time
import json

from fastapi import HTTPException
from sqlalchemy import text


DEFAULT_RULES = {
    "login_account": (5, 120),
    "login_peer": (60, 60),
    "recovery_target": (3, 900),
    "recovery_issuer": (10, 900),
    "recovery_peer": (20, 900),
}


def observed_peer(request):
    # Forwarded headers are not a verified end-user identity. Behind Next.js or
    # another proxy this can deliberately be a shared, supplementary bucket.
    return request.client.host if request.client is not None else "unavailable"

RESERVE = text("""
INSERT INTO cuota_acceso (clave_hash, intentos, expira_en) VALUES (:key, 1, :expires)
ON CONFLICT (clave_hash) DO UPDATE SET
    intentos = CASE WHEN cuota_acceso.expira_en <= :now THEN 1 ELSE cuota_acceso.intentos + 1 END,
    expira_en = CASE WHEN cuota_acceso.expira_en <= :now THEN :expires ELSE cuota_acceso.expira_en END
WHERE cuota_acceso.expira_en <= :now OR cuota_acceso.intentos < :maximum
RETURNING expira_en
""")


def configuration(values=None):
    values = os.environ if values is None else values
    try:
        raw = values["FAMA_RATE_LIMIT_KEY"]
        key = raw.encode("utf-8")
        if not raw.strip() or len(key) < 32:
            raise ValueError
        overrides = json.loads(values.get("FAMA_ACCESS_LIMITS_JSON", "{}"))
        if not isinstance(overrides, dict) or set(overrides) - set(DEFAULT_RULES):
            raise ValueError
        rules = dict(DEFAULT_RULES)
        for policy, rule in overrides.items():
            if not isinstance(rule, dict) or set(rule) != {"limit", "window_seconds"}:
                raise ValueError
            maximum, seconds = rule["limit"], rule["window_seconds"]
            if type(maximum) is not int or type(seconds) is not int:
                raise ValueError
            if not 1 <= maximum <= 10000 or not 1 <= seconds <= 86400:
                raise ValueError
            rules[policy] = (maximum, seconds)
        return key, rules
    except (KeyError, ValueError, UnicodeError):
        raise HTTPException(503, "Límites de acceso no configurados.") from None


def admit(db, buckets):
    key, rules = configuration()
    now = int(time.time())
    # Stable ordering avoids inverted row-lock acquisition across requests.
    reservations = []
    for policy, identity in buckets:
        digest = hmac.new(key, f"{policy}\0{identity}".encode("utf-8"), hashlib.sha256).hexdigest()
        reservations.append((digest, *rules[policy]))
    retry_after = 0
    try:
        for digest, maximum, seconds in sorted(reservations):
            reserved = db.execute(RESERVE, {"key": digest, "expires": now + seconds,
                                           "now": now, "maximum": maximum}).scalar_one_or_none()
            if reserved is None:
                expires = db.execute(text("SELECT expira_en FROM cuota_acceso WHERE clave_hash = :key"),
                                     {"key": digest}).scalar_one()
                retry_after = max(retry_after, max(1, expires - now))
        if retry_after:
            raise HTTPException(429, "Demasiados intentos. Inténtelo más tarde.",
                                headers={"Retry-After": str(retry_after)})
        db.commit()
    except Exception:
        db.rollback()
        raise
