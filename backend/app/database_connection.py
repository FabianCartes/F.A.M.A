"""Política SQL compartida por el operador de migraciones y la aplicación."""
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def normalize_database_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        return parsed.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)
    return url


def database_engine(url: str):
    normalized = normalize_database_url(url)
    options = {}
    if make_url(normalized).get_backend_name() == "postgresql":
        options["connect_args"] = {
            "connect_timeout": 5,
            "options": "-c statement_timeout=5000 -c lock_timeout=3000",
        }
    return create_engine(normalized, pool_pre_ping=True, hide_parameters=True, **options)
