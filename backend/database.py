"""
Módulo de conexión a Base de Datos PostgreSQL.
Re-exporta la configuración de app.database para compatibilidad con la raíz de backend.
"""
from app.database import engine, SessionLocal, Base, get_db, DATABASE_URL

__all__ = ["engine", "SessionLocal", "Base", "get_db", "DATABASE_URL"]
