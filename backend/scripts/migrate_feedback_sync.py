"""Crear solo feedback_sync en una base existente, sin backfill ni dotenv.

Acción explícita del operador, después de respaldo y pausa de escritores:
  python backend/scripts/migrate_feedback_sync.py --apply
DATABASE_URL debe suministrarse explícitamente. No importa ni inicia la app.
"""
import argparse
import os

from sqlalchemy import create_engine, inspect, text


def migrate(engine) -> bool:
    """Migración aditiva SQLite/PostgreSQL; False si la tabla ya existe."""
    if engine.dialect.name not in ("postgresql", "sqlite"):
        raise ValueError("Only PostgreSQL and SQLite are supported")
    with engine.begin() as connection:
        schema = inspect(connection)
        if schema.has_table("feedback_sync"):
            return False
        if not schema.has_table("retroalimentacion"):
            raise ValueError("Existing retroalimentacion table required")
        connection.execute(text("""CREATE TABLE feedback_sync (
            id_retroalimentacion INTEGER NOT NULL PRIMARY KEY,
            dataset_name VARCHAR(100) NOT NULL,
            storage_class VARCHAR(100) NOT NULL,
            class_label VARCHAR(100) NOT NULL,
            object_key VARCHAR(255) NOT NULL,
            local_relative_path VARCHAR(255) NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            status VARCHAR(10) NOT NULL,
            attempts INTEGER NOT NULL,
            error_code VARCHAR(32),
            UNIQUE (object_key),
            UNIQUE (local_relative_path),
            FOREIGN KEY (id_retroalimentacion)
                REFERENCES retroalimentacion(id_retroalimentacion) ON DELETE RESTRICT,
            CONSTRAINT feedback_sync_status CHECK (status IN ('pending', 'synced')),
            CONSTRAINT feedback_sync_attempts CHECK (attempts >= 0)
        )"""))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True,
                        help="Explicit authorization to modify the supplied database")
    parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL must be supplied explicitly; no default or dotenv is used")
    engine = create_engine(url)
    try:
        print("feedback_sync added" if migrate(engine) else "feedback_sync already present")
    finally:
        engine.dispose()
