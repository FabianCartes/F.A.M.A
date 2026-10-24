"""Sesiones SQL explícitas. Importar modelos no conecta ni crea tablas."""
from fastapi import HTTPException
from sqlalchemy.orm import declarative_base, sessionmaker

from app.configuration import get_configuration
from app.database_connection import database_engine, normalize_database_url

_configuration = get_configuration()
DATABASE_URL = normalize_database_url(_configuration.database_url) if _configuration.database_url else None
engine = database_engine(DATABASE_URL) if DATABASE_URL else None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    if engine is None:
        raise HTTPException(503, "Base de datos no configurada.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
