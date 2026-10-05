"""Explicit additive migration tested only against temporary SQLite."""
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session


def test_migration_preserves_legacy_rows_and_reexecution_preserves_queue(tmp_path):
    from scripts.migrate_feedback_sync import migrate
    from app.services.feedback_sync import FeedbackSyncQueue

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("""CREATE TABLE prediccion (
            id_prediccion INTEGER PRIMARY KEY, ruta_audio_prueba VARCHAR(255),
            etiqueta_predicha VARCHAR(100), confianza FLOAT, modelo_id VARCHAR(100),
            dataset_name VARCHAR(100), fecha_prediccion DATETIME)"""))
        connection.execute(text("""CREATE TABLE retroalimentacion (
            id_retroalimentacion INTEGER PRIMARY KEY, id_prediccion INTEGER,
            id_usuario INTEGER, etiqueta_corregida VARCHAR(100), fue_correcta BOOLEAN,
            procesado BOOLEAN, fecha_retroalimentacion DATETIME)"""))
        connection.execute(text("""INSERT INTO prediccion VALUES
            (1, 'raw_audios/source.wav', 'Rayadito', 0.9, 'model', 'AvesChilenas', NULL)"""))
        connection.execute(text("""INSERT INTO retroalimentacion VALUES
            (7, 1, 1, NULL, 1, 0, NULL), (8, 1, 1, NULL, 1, 1, NULL)"""))
        before = connection.execute(text("SELECT * FROM retroalimentacion ORDER BY 1")).all()
        schema_before = connection.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")).all()
    assert migrate(engine) is True
    assert set(inspect(engine).get_table_names()) == {"prediccion", "retroalimentacion", "feedback_sync"}
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name != 'feedback_sync' ORDER BY name"
        )).all() == schema_before
        assert connection.execute(text("SELECT * FROM retroalimentacion ORDER BY 1")).all() == before
    queue = FeedbackSyncQueue()
    with Session(engine) as db:
        assert queue.pending(db) == []
        assert queue.get(db, 8) is None  # Old processed is not local-ready.
        item = queue.enqueue(db, 7, dataset_name="AvesChilenas",
                             storage_class="rayadito", sha256="a" * 64)
        db.commit()
    assert migrate(engine) is False
    schema = inspect(engine)
    assert schema.get_pk_constraint("feedback_sync")["constrained_columns"] == ["id_retroalimentacion"]
    foreign_key = schema.get_foreign_keys("feedback_sync")[0]
    assert foreign_key["referred_table"] == "retroalimentacion"
    assert foreign_key["options"]["ondelete"] == "RESTRICT"
    assert {tuple(c["column_names"]) for c in schema.get_unique_constraints("feedback_sync")} == {
        ("object_key",), ("local_relative_path",)}
    with Session(engine) as db:
        assert queue.pending(db) == [item]
    # Fresh metadata and the explicit migration expose the same column contract.
    from app.database import Base
    fresh = create_engine(f"sqlite:///{tmp_path / 'fresh.sqlite'}")
    Base.metadata.create_all(fresh)
    for key in ("nullable", "default", "primary_key"):
        assert [(c["name"], str(c["type"]), c[key]) for c in schema.get_columns("feedback_sync")] == [
            (c["name"], str(c["type"]), c[key]) for c in inspect(fresh).get_columns("feedback_sync")]
    fresh.dispose()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM retroalimentacion ORDER BY 1")).all() == before
    engine.dispose()


def test_operator_script_requires_apply_and_explicit_url(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "migrate_feedback_sync.py"
    url = f"sqlite:///{tmp_path / 'operator.sqlite'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE retroalimentacion (id_retroalimentacion INTEGER PRIMARY KEY)"))
    environment = {"DATABASE_URL": url, "PYTHONDONTWRITEBYTECODE": "1"}
    refused = subprocess.run([sys.executable, str(script)], env=environment,
                             capture_output=True, text=True, timeout=20)
    assert refused.returncode != 0
    assert inspect(engine).get_table_names() == ["retroalimentacion"]
    missing_url = subprocess.run([sys.executable, str(script), "--apply"],
                                env={"PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=20)
    assert missing_url.returncode != 0
    assert "DATABASE_URL must be supplied explicitly" in missing_url.stderr
    for output in ("feedback_sync added", "feedback_sync already present"):
        result = subprocess.run([sys.executable, str(script), "--apply"], env=environment,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == output
    engine.dispose()


def test_migration_refuses_missing_legacy_table_without_creating_other_tables(tmp_path):
    from scripts.migrate_feedback_sync import migrate

    engine = create_engine(f"sqlite:///{tmp_path / 'empty.sqlite'}")
    with pytest.raises(ValueError, match="retroalimentacion"):
        migrate(engine)
    assert inspect(engine).get_table_names() == []
    engine.dispose()
