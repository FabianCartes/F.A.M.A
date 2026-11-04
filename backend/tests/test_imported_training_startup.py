"""Fresh-process startup schema contract; invoke each case in a separate runner.

No reload of a populated application module or create_all mock: observe actual
DDL on a new SQLite memory engine. Operational migrations are not executed.
"""
import importlib
import json
import sys

import pytest


@pytest.mark.parametrize("order", ["normal", "eager"])
def test_startup_requires_explicit_imported_source_migration(monkeypatch, order):
    from sqlalchemy import create_engine, event, inspect
    from sqlalchemy.orm import sessionmaker
    from app import database

    assert "app.main" not in sys.modules, "Startup case needs its own fresh runner invocation"
    engine = create_engine("sqlite://")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    if order == "eager":
        # A maintenance module can register the complete ORM dependency closure
        # before another entrypoint imports the application. Do not run migration.
        importlib.import_module("scripts.migrate_imported_training_source")
        importlib.import_module("scripts.migrate_web_sessions")
    statements = []
    event.listen(engine, "before_cursor_execute",
                 lambda connection, cursor, statement, parameters, context, executemany:
                 statements.append(statement) if statement.lstrip().upper().startswith("CREATE TABLE") else None)
    try:
        assert not inspect(engine).has_table("imported_model_source")
        importlib.import_module("app.main")
        created = sorted(inspect(engine).get_table_names())
        print("STARTUP_DDL " + json.dumps({"order": order, "tables": created,
                                          "create_table_statements": statements}, sort_keys=True))
        assert "modelo" in created
        assert "usuario" in created
        assert "conjunto_datos" in created
        assert not {"sesion_web", "cuota_acceso", "evento_seguridad"}.intersection(created)
        assert "imported_model_source" not in created
        assert not any("CREATE TABLE imported_model_source" in statement for statement in statements)
    finally:
        engine.dispose()
