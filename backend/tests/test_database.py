"""Database configuration stays dormant for ORM imports, with runtime API compatibility."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap


def run_probe(source):
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", DATABASE_URL="sqlite://")
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30,
    )


def test_orm_imports_do_not_load_dotenv_or_create_runtime_engine():
    probe = run_probe("""
        import dotenv
        import sqlalchemy
        calls = []
        def forbidden(*args, **kwargs):
            calls.append("dotenv")
        def forbidden_engine(*args, **kwargs):
            calls.append("engine")
            raise AssertionError("runtime engine created during ORM import")
        dotenv.load_dotenv = forbidden
        sqlalchemy.create_engine = forbidden_engine

        import app.models
        import app.database as database
        from app.models.training import Modelo
        assert Modelo.metadata is database.Base.metadata
        assert "engine" not in vars(database)
        assert "SessionLocal" not in vars(database)
        assert calls == []
    """)
    assert probe.returncode == 0, probe.stderr


def test_database_runtime_api_keeps_shared_base_session_and_url_normalization():
    probe = run_probe("""
        import dotenv
        import sqlalchemy
        calls = []
        engines = []
        original_create_engine = sqlalchemy.create_engine
        def track_dotenv(*args, **kwargs):
            calls.append("dotenv")
        def track_engine(url, *args, **kwargs):
            engines.append(url)
            return original_create_engine(url, *args, **kwargs)
        dotenv.load_dotenv = track_dotenv
        sqlalchemy.create_engine = track_engine

        import app.database as database
        assert calls == [] and engines == []
        from app.models.training import Modelo
        Base = database.Base
        assert Modelo.metadata is Base.metadata
        assert database.DATABASE_URL == "sqlite://"
        assert calls == ["dotenv"] and engines == []
        engine = database.engine
        assert engine is database.engine
        assert engines == ["sqlite://"]
        factory = database.SessionLocal
        assert factory is database.SessionLocal
        assert factory.kw["bind"] is engine
        assert database.normalize_database_url("postgresql://db.example/fama") == \
            "postgresql+psycopg2://db.example/fama"
        assert database.normalize_database_url("postgresql+asyncpg://db.example/fama") == \
            "postgresql+asyncpg://db.example/fama"

        from app.models.dataset import ConjuntoDatos
        Base.metadata.create_all(bind=engine)
        generator = database.get_db()
        session = next(generator)
        assert session.get_bind() is engine
        session.add(ConjuntoDatos(nombre="synthetic", ruta_gcp="synthetic/"))
        session.commit()
        closed = []
        close = session.close
        session.close = lambda: (closed.append(True), close())[1]
        try:
            next(generator)
        except StopIteration:
            pass
        else:
            raise AssertionError("get_db must yield once")
        assert closed == [True]
        assert engines == ["sqlite://"]
        engine.dispose()
    """)
    assert probe.returncode == 0, probe.stderr
