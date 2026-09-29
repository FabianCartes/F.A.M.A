import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

# ============================================================================
# CONFIGURACIÓN DE CONEXIÓN A POSTGRESQL (RNF_03)
# ============================================================================
_BACKEND_DIR = Path(__file__).resolve().parent
if _BACKEND_DIR.name == "app":
    _BACKEND_DIR = _BACKEND_DIR.parent

_ENV_FILE = _BACKEND_DIR / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()

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


# Cadena de conexión obtenida de variables de entorno
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/fama_db",
)
DATABASE_URL = normalize_database_url(DATABASE_URL)

# Motor de base de datos SQLAlchemy con verificación de conexión activa (pool_pre_ping)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

# Creador de sesiones para transacciones
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base declarativa para modelos relacionales
Base = declarative_base()


def get_db():
    """
    Generador de sesiones de base de datos para inyección de dependencias en FastAPI.
    Garantiza el cierre seguro de la conexión al finalizar cada petición HTTP.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
