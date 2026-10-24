"""Independent S9 regressions for target isolation and application schema checks."""
import contextlib
import hashlib
import io
import unittest
from unittest.mock import patch


class S9DatabaseRegressions(unittest.TestCase):
    def engine(self):
        from sqlalchemy import create_engine
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        return engine

    def digest(self, engine):
        with engine.connect() as connection:
            dump = "\n".join(connection.connection.driver_connection.iterdump())
        return hashlib.sha256(dump.encode()).hexdigest()

    def test_initializer_cannot_override_dedicated_target_with_query(self):
        from scripts.prepare_zip_manual_database import main
        from sqlalchemy import create_engine
        url = ("postgresql+psycopg2://zip_manual:public@127.0.0.1:55432/"
               "fama_zip_manual?dbname=fama_db&host=remote.invalid")
        calls = []
        def intercept(value):
            engine = create_engine(value)
            calls.append(engine.dialect.create_connect_args(engine.url)[1])
            engine.dispose()
            raise ValueError("Network deliberately not opened")
        with patch("sqlalchemy.create_engine", side_effect=intercept), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                main(["--database-url", url, "--initialize", "--writers-stopped"])
        self.assertEqual(calls, [])
        self.assertEqual(result.exception.code, 2)

    def test_check_requires_application_schema(self):
        from scripts.prepare_zip_manual_database import initialize, verify
        from app.models.user import Usuario
        engine = self.engine()
        initialize(engine, writers_stopped=True)
        Usuario.__table__.drop(engine)
        before = self.digest(engine)
        with self.assertRaises(Exception):
            verify(engine)
        self.assertEqual(before, self.digest(engine))
