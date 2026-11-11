"""Historical imported model-source persistence, synthetic memory database only."""
import pytest
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort
from tests.test_training_flow import training_env


def test_explicit_migration_from_absent_table(cohort):
    from sqlalchemy import inspect
    from app.models.imported_training_source import ImportedModelSource
    from scripts.migrate_imported_training_source import migrate_imported_sources
    engine = cohort[0].sessions.kw["bind"]
    ImportedModelSource.__table__.drop(engine, checkfirst=True)
    assert not inspect(engine).has_table("imported_model_source")
    with pytest.raises(RuntimeError, match="writers"):
        migrate_imported_sources(engine)
    assert not inspect(engine).has_table("imported_model_source")
    migrate_imported_sources(engine, writers_stopped=True)
    migrate_imported_sources(engine, writers_stopped=True)
    from app.services.imported_training_source import ImportedTrainingSource, ImportedSourceError
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    sources = ImportedTrainingSource(ImportedDatasetPreparation(cohort[0], cohort[0].root.parent / "prepared"))
    with pytest.raises(ImportedSourceError, match="Fuente importada no disponible"):
        sources.model_source(1, 999)


def test_existing_source_history_and_activation_remain_private(cohort, training_env, tmp_path, monkeypatch):
    from tests.test_imported_training_evaluation import _complete_imported_cpu_worker
    from app.services.imported_training_source import ImportedSourceError
    runtime, sessions, model_id, association = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch)
    with sessions() as db:
        entry = next(row for row in runtime.get_history(db, owner_id=1) if row["id"] == model_id)
        assert entry["imported_source"] == association
        assert entry["status"] == "standard_eval_completed"
        assert not entry["active"]
        assert all(row["id"] != model_id for row in runtime.get_history(db))
        assert all(row["id"] != model_id for row in runtime.get_history(db, owner_id=2))
        before = {row["id"]: row["active"] for row in runtime.get_history(db, owner_id=1)}
        assert runtime.set_active_model(model_id, db) == {
            "success": False, "error": "Los modelos importados no pueden activarse globalmente."}
        assert {row["id"]: row["active"] for row in runtime.get_history(db, owner_id=1)} == before
    with pytest.raises(ImportedSourceError):
        runtime.imported_sources.model_source(2, model_id)


def test_incompatible_source_schema_is_not_repaired_or_backfilled(cohort):
    from sqlalchemy import inspect, MetaData, Table, Column, Integer
    from app.models.imported_training_source import ImportedModelSource
    from scripts.migrate_imported_training_source import migrate_imported_sources
    engine = cohort[0].sessions.kw["bind"]
    ImportedModelSource.__table__.drop(engine, checkfirst=True)
    malformed = Table("imported_model_source", MetaData(), Column("model_id", Integer, primary_key=True))
    malformed.create(engine)
    catalog = cohort[4].get("/api/ingestion/imports/datasets").json()
    before = inspect(engine).get_columns("imported_model_source")
    with pytest.raises(RuntimeError, match="Incompatible schema"):
        migrate_imported_sources(engine, writers_stopped=True)
    after = inspect(engine).get_columns("imported_model_source")
    assert [(c["name"], str(c["type"]), c["nullable"]) for c in after] == [
        (c["name"], str(c["type"]), c["nullable"]) for c in before]
    assert cohort[4].get("/api/ingestion/imports/datasets").json() == catalog
