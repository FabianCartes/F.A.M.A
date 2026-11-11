"""Build test databases through the Alembic migrations, never through create_all."""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

BACKEND = Path(__file__).resolve().parents[1]


def _config(connection):
    from alembic.config import Config
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.attributes["connection"] = connection
    return config


def upgrade(connection, revision="head"):
    from alembic import command
    command.upgrade(_config(connection), revision)


def downgrade(connection, revision):
    from alembic import command
    command.downgrade(_config(connection), revision)


def migrated_engine(revision="head"):
    """In-memory SQLite engine shared across threads, migrated to ``revision``."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as connection:
        upgrade(connection, revision)
    return engine
