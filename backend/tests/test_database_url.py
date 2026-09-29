"""The database engine must not depend on SQLAlchemy's version-dependent default driver.

A bare ``postgresql://`` URL resolves to the psycopg2 dialect in SQLAlchemy 2.0
and to the psycopg3 dialect in 2.1. ``requirements.txt`` declares
``sqlalchemy>=2.0.0`` with no upper bound, so a workstation holding 2.0.x imports
this module happily while a freshly built image holding 2.1.x raises
``ModuleNotFoundError: No module named 'psycopg'`` during import and the API
never starts.

The invariant under test is therefore behavioural, not a version pin: whatever
SQLAlchemy is installed, the engine this module builds must resolve to a driver
whose DBAPI is importable.
"""

import importlib

import pytest
from sqlalchemy.engine import make_url


def _dbapi_is_importable(url: str) -> bool:
    """`URL.get_dialect()` is the portable way to resolve a dialect.

    `sqlalchemy.dialects.registry.load()` is not: on SQLAlchemy 2.0.53 it raises
    NoSuchModuleError for `postgresql+psycopg2` even though the dialect loads fine
    through the URL, so using the registry here would test the lookup rather than
    the contract.
    """

    try:
        dialect = make_url(url).get_dialect()
        dialect.import_dbapi()
    except ImportError:
        return False
    return True


def test_engine_driver_is_importable_with_the_installed_sqlalchemy():
    from app.database import DATABASE_URL, engine

    assert _dbapi_is_importable(str(engine.url)), (
        f"DATABASE_URL {DATABASE_URL!r} resolves to {engine.url.drivername!r}, "
        "whose DBAPI is not installed"
    )


def test_bare_postgresql_scheme_is_pinned_to_an_explicit_driver():
    from app.database import normalize_database_url

    pinned = make_url(normalize_database_url("postgresql://u:p@h:5432/db"))

    assert pinned.get_backend_name() == "postgresql"
    assert pinned.drivername == "postgresql+psycopg2"


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@h:5432/db",
        "postgresql+psycopg2://u:p@h:5432/db",
    ],
)
def test_legacy_and_already_pinned_schemes_both_reach_psycopg2(url: str):
    from app.database import normalize_database_url

    assert make_url(normalize_database_url(url)).drivername == "postgresql+psycopg2"


def test_explicit_third_party_driver_is_preserved():
    from app.database import normalize_database_url

    async_pg = "postgresql+asyncpg://u:p@h:5432/db"

    assert normalize_database_url(async_pg) == async_pg


def test_credentials_survive_normalisation():
    from app.database import normalize_database_url

    pinned = make_url(
        normalize_database_url("postgresql://user:s3cr3t@db:5432/fama_db")
    )

    assert pinned.username == "user"
    assert pinned.password == "s3cr3t"
    assert pinned.host == "db"
    assert pinned.database == "fama_db"


def test_normalised_url_actually_loads_its_dbapi():
    from app.database import normalize_database_url

    assert _dbapi_is_importable(normalize_database_url("postgres://u:p@h:5432/db"))


def test_engine_creation_from_normalized_env_url(monkeypatch):
    """Creating an engine from an env var must resolve to an importable explicit driver."""
    import os
    from sqlalchemy import create_engine
    from app.database import normalize_database_url

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
    url = normalize_database_url(os.environ["DATABASE_URL"])
    eng = create_engine(url)

    assert eng.url.drivername == "postgresql+psycopg2"
    assert _dbapi_is_importable(str(eng.url))
