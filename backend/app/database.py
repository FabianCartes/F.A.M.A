import os
from pathlib import Path
from threading import RLock
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

# Public ORM metadata is independent of runtime connection configuration.
Base = declarative_base()

# ============================================================================
# CONFIGURACIÓN DE CONEXIÓN A POSTGRESQL (RNF_03)
# ============================================================================
_BACKEND_DIR = Path(__file__).resolve().parent
if _BACKEND_DIR.name == "app":
    _BACKEND_DIR = _BACKEND_DIR.parent

_ENV_FILE = _BACKEND_DIR / ".env"
_RUNTIME = {}
_RUNTIME_LOCK = RLock()


def _load_runtime_environment():
    if not _RUNTIME.get("dotenv_loaded"):
        if _ENV_FILE.exists():
            load_dotenv(dotenv_path=_ENV_FILE)
        else:
            load_dotenv()
        _RUNTIME["dotenv_loaded"] = True

# Driver exigido por requirements.txt (psycopg2-binary) y por el Dockerfile
# (libpq-dev). El dialecto por defecto de `postgresql://` cambió de psycopg2 a
# psycopg3 en SQLAlchemy 2.1, de modo que una URL sin driver explícito funciona
# con 2.0.x y revienta con ModuleNotFoundError en 2.1.x. Declarar el driver
# aquí desacopla el arranque de esa decisión de la librería.
REQUIRED_DBAPI = "psycopg2"
BARE_POSTGRES_SCHEMES = {"postgresql", "postgres"}


def normalize_database_url(url: str) -> str:
    """Fija el driver PostgreSQL de forma explícita en la URL de conexión.

    No altera esquemas que ya declaran un driver propio (por ejemplo
    `postgresql+asyncpg`) ni URLs de otros motores. Solo sustituye el dialecto
    por defecto implícito de PostgreSQL, que es el único que depende de la
    versión de SQLAlchemy instalada.
    """
    parsed = make_url(url)

    if parsed.drivername not in BARE_POSTGRES_SCHEMES:
        return url

    return parsed.set(
        drivername=f"postgresql+{REQUIRED_DBAPI}"
    ).render_as_string(hide_password=False)


def _runtime_database_url():
    with _RUNTIME_LOCK:
        if "DATABASE_URL" not in _RUNTIME:
            _load_runtime_environment()
            value = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fama_db")
            _RUNTIME["DATABASE_URL"] = normalize_database_url(value)
        return _RUNTIME["DATABASE_URL"]


def _runtime_engine():
    with _RUNTIME_LOCK:
        if "engine" not in _RUNTIME:
            _RUNTIME["engine"] = create_engine(_runtime_database_url(), pool_pre_ping=True)
        return _RUNTIME["engine"]


def _runtime_session_factory():
    with _RUNTIME_LOCK:
        if "SessionLocal" not in _RUNTIME:
            _RUNTIME["SessionLocal"] = sessionmaker(
                autocommit=False, autoflush=False, bind=_runtime_engine())
        return _RUNTIME["SessionLocal"]


def __getattr__(name):
    if name == "DATABASE_URL":
        value = _runtime_database_url()
    elif name == "engine":
        value = _runtime_engine()
    elif name == "SessionLocal":
        value = _runtime_session_factory()
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | {"DATABASE_URL", "engine", "SessionLocal"})


__all__ = ["Base", "DATABASE_URL", "engine", "SessionLocal", "get_db", "normalize_database_url"]


def get_db():
    """
    Generador de sesiones de base de datos para inyección de dependencias en FastAPI.
    Garantiza el cierre seguro de la conexión al finalizar cada petición HTTP.
    """
    factory = globals().get("SessionLocal")
    if factory is None:
        factory = _runtime_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
