import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
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

# Cadena de conexión obtenida de variables de entorno
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/fama_db",
)

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
