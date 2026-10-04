"""Add the nullable inference destination to an EXISTING database, explicitly.

Deployment: back up the database, stop inference/curation writers, supply the
operator-approved DATABASE_URL through the environment, then run:
  python backend/scripts/migrate_prediction_dataset.py --apply
Run BEFORE refreshing backend code. No dotenv, application import, startup hook
or guessed legacy backfill: old predictions retain NULL and remain pending.
"""
import argparse
import os
from sqlalchemy import create_engine, inspect, text


def migrate(engine) -> bool:
    """Return whether the additive PostgreSQL/SQLite migration changed schema."""
    if engine.dialect.name not in ("postgresql", "sqlite"):
        raise ValueError("Only PostgreSQL and SQLite are supported")
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("prediccion")}
        if "dataset_name" in columns:
            return False
        connection.execute(text("ALTER TABLE prediccion ADD COLUMN dataset_name VARCHAR(100) NULL"))
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
        print("dataset_name added" if migrate(engine) else "dataset_name already present")
    finally:
        engine.dispose()
