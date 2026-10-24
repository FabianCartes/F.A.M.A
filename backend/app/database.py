"""ORM imports are dormant; runtime sessions use explicit installation configuration."""
from threading import RLock
from fastapi import HTTPException
from sqlalchemy.orm import declarative_base, sessionmaker
from app.database_connection import database_engine, normalize_database_url

Base = declarative_base()
_RUNTIME = {}
_RUNTIME_LOCK = RLock()


def _runtime_database_url():
    with _RUNTIME_LOCK:
        if "DATABASE_URL" not in _RUNTIME:
            from app.configuration import get_configuration
            url = get_configuration().database_url
            _RUNTIME["DATABASE_URL"] = normalize_database_url(url) if url else None
        return _RUNTIME["DATABASE_URL"]


def _runtime_engine():
    with _RUNTIME_LOCK:
        if "engine" not in _RUNTIME:
            url = _runtime_database_url()
            _RUNTIME["engine"] = database_engine(url) if url else None
        return _RUNTIME["engine"]


def _runtime_session_factory():
    with _RUNTIME_LOCK:
        if "SessionLocal" not in _RUNTIME:
            _RUNTIME["SessionLocal"] = sessionmaker(autocommit=False, autoflush=False, bind=_runtime_engine())
        return _RUNTIME["SessionLocal"]


def __getattr__(name):
    functions = {"DATABASE_URL": _runtime_database_url, "engine": _runtime_engine,
                 "SessionLocal": _runtime_session_factory}
    if name not in functions:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = functions[name]()
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | {"DATABASE_URL", "engine", "SessionLocal"})


def get_db():
    if _runtime_engine() is None:
        raise HTTPException(503, "Base de datos no configurada.")
    factory = globals().get("SessionLocal") or _runtime_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
