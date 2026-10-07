"""Explicitly add nullable upload display metadata to an EXISTING database.

Back up the database and stop writers before an operator supplies DATABASE_URL
and runs: python backend/scripts/migrate_prediction_audio_metadata.py --apply
Run before deploying the new backend. No dotenv, app imports or historical
backfill: original names and reception times cannot be inferred from UUIDs.
"""
import argparse
import os
from sqlalchemy import create_engine, inspect, text


def migrate(engine) -> bool:
    """Add missing columns transactionally on PostgreSQL or SQLite; safe to repeat."""
    if engine.dialect.name not in ("postgresql", "sqlite"):
        raise ValueError("Only PostgreSQL and SQLite are supported")
    changed = False
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("prediccion")}
        definitions = {
            "nombre_original": "VARCHAR(255)",
            "fecha_carga": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "TIMESTAMP",
        }
        for name, sql_type in definitions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE prediccion ADD COLUMN {name} {sql_type} NULL"))
                changed = True
    return changed


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
        print("audio metadata added" if migrate(engine) else "audio metadata already present")
    finally:
        engine.dispose()
