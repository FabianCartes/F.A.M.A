"""The development check never initializes or repairs an import store."""
import pytest
from sqlalchemy import create_engine, text

from scripts.prepare_zip_manual_database import initialize


@pytest.mark.parametrize("damage", [None, "table", "marker", "summary"])
def test_readiness_preserves_database_and_rejects_missing_preparation(damage):
    from scripts.check_dev_import_database import verify

    engine = create_engine("sqlite://")
    try:
        initialize(engine, writers_stopped=True)
        with engine.begin() as connection:
            if damage == "table":
                connection.execute(text("DROP TABLE dataset_import_chunk"))
            elif damage == "marker":
                connection.execute(text("DELETE FROM dataset_import_chunk_schema"))
            elif damage == "summary":
                connection.execute(text("INSERT INTO imported_dataset "
                    "(id, owner_id, name, description, revision, files) "
                    "VALUES ('missing-summary', -1, 'synthetic', '', 0, '[]')"))
        with engine.connect() as connection:
            before = tuple(connection.connection.driver_connection.iterdump())
        if damage:
            with pytest.raises(ValueError):
                verify(engine)
        else:
            assert verify(engine) == {"ready": True, "verification": "import_schema_and_markers"}
        with engine.connect() as connection:
            assert tuple(connection.connection.driver_connection.iterdump()) == before
    finally:
        engine.dispose()


def test_empty_database_is_not_initialized():
    from scripts.check_dev_import_database import verify

    engine = create_engine("sqlite://")
    try:
        with pytest.raises(ValueError):
            verify(engine)
        from sqlalchemy import inspect
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_development_cli_is_read_only_and_normalizes_worker_driver(monkeypatch, tmp_path, capsys):
    import json
    from scripts.check_dev_import_database import main

    root = tmp_path / "backend/data-dev/dataset-imports"
    root.mkdir(parents=True, mode=0o700)
    monkeypatch.setenv("FAMA_ENV", "development")
    monkeypatch.setenv("FAMA_IMPORT_DEV_MODE", "1")
    monkeypatch.setenv("FAMA_IMPORT_ROOT", str(root))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:synthetic@db:5432/fama_db")
    engine = create_engine("sqlite://")
    initialize(engine, writers_stopped=True)
    # The CLI's DB connection seam is synthetic; no network or live DB is opened.
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    try:
        assert main([]) == 0
        assert json.loads(capsys.readouterr().out)["ready"] is True
        assert main(["--worker-config"]) == 0
        config = json.loads(capsys.readouterr().out)
        assert config["database_url"] == "postgresql+psycopg2://test:synthetic@172.30.253.30:5432/fama_db"
        assert config["import_root"] == str(root)
        monkeypatch.setenv("FAMA_ENV", "production")
        with pytest.raises(SystemExit) as error:
            main([])
        assert error.value.code == 1
        assert "synthetic" not in capsys.readouterr().err
    finally:
        engine.pool.dispose()
