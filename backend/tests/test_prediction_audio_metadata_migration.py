"""Additive migration on historical SQLite schemas; no application startup."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


def test_migration_is_additive_idempotent_and_does_not_invent_history():
    path = Path(__file__).resolve().parents[1] / "scripts/migrate_prediction_audio_metadata.py"
    spec = importlib.util.spec_from_file_location("audio_metadata_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE prediccion (id_prediccion INTEGER PRIMARY KEY, ruta_audio_prueba VARCHAR(255))"))
            connection.execute(text("INSERT INTO prediccion VALUES (7, 'raw_audios/historical.wav')"))
        assert module.migrate(engine) is True
        assert module.migrate(engine) is False
        columns = {column['name']: column for column in inspect(engine).get_columns('prediccion')}
        assert columns['nombre_original']['nullable'] is True
        assert columns['fecha_carga']['nullable'] is True
        with engine.connect() as connection:
            assert connection.execute(text("SELECT * FROM prediccion")).one() == (
                7, 'raw_audios/historical.wav', None, None)
    finally:
        engine.dispose()


@pytest.mark.parametrize('existing', ['nombre_original VARCHAR(255)', 'fecha_carga TIMESTAMP'])
def test_migration_completes_a_partially_migrated_schema(existing):
    path = Path(__file__).resolve().parents[1] / "scripts/migrate_prediction_audio_metadata.py"
    spec = importlib.util.spec_from_file_location("audio_metadata_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE TABLE prediccion (id_prediccion INTEGER, {existing})'))
        assert module.migrate(engine) is True
        assert module.migrate(engine) is False
        assert {c['name'] for c in inspect(engine).get_columns('prediccion')} == {
            'id_prediccion', 'nombre_original', 'fecha_carga'}
    finally:
        engine.dispose()
