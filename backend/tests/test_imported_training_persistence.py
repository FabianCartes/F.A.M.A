"""Additive imported model-source persistence, synthetic memory database only."""
import pytest
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create
from tests.test_training_flow import training_env
from tests.test_api_training import client


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


@pytest.mark.parametrize("fault", [None, "association", "audio_after_admission"])
def test_real_cpu_worker_persists_source_pending_evaluation(cohort, training_env, tmp_path, monkeypatch, client, fault, request):
    import torch
    from app.services import training
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    runtime, _, _, process = training_env
    sessions = cohort[0].sessions
    migrate_imported_sources(sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    monkeypatch.setattr(training, "SessionLocal", sessions)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    # Execute the actual worker and loaders. Only the external process boundary is inline.
    class Inline:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            if fault == "audio_after_admission":
                member = self.args[0]["source"]["splits"]["train"][0]
                path = cohort[0].root / cohort[1]["id"] / member["member_id"]
                path.chmod(0o600)
                path.write_bytes(b"changed after admission")
            self.target(*self.args)
    process.side_effect = Inline
    if fault == "association":
        from sqlalchemy import event
        from app.models.imported_training_source import ImportedModelSource
        def fail_association(*args):
            raise RuntimeError("Synthetic source registration failure")
        event.listen(ImportedModelSource, "before_insert", fail_association)
        # Remove the fault hook even if a public assertion fails.
        request.addfinalizer(lambda: event.remove(ImportedModelSource, "before_insert", fail_association))

    result = runtime.start_training("", imported_dataset_id=cohort[5], snapshot_id=cohort[1]["id"],
        imported_prepared_version=prepared["version_id"], owner_id=1,
        architecture="AudioCNN", epochs=1, batch_size=2, early_stopping=False)
    assert result["status"] == "started"
    if fault:
        progress = runtime.get_progress(owner_id=1)
        assert progress["status"] == "failed", progress
        expected = ("Synthetic source registration failure" if fault == "association"
                    else "Fuente importada no disponible.")
        assert progress["error_message"] == expected
        with sessions() as db:
            assert runtime.get_history(db, owner_id=1) == []
            assert runtime.get_history(db) == []
        assert list(runtime.checkpoints_dir.iterdir()) == []
        return
    assert runtime.get_progress()["status"] == "checkpoint_persisted", runtime.get_progress()
    with sessions() as db:
        entry, = runtime.get_history(db, owner_id=1)
    assert entry["status"] == "standard_eval_pending"
    assert entry["active"] is False
    association = runtime.imported_sources.model_source(1, entry["id"])
    assert association["dataset_id"] == cohort[5]
    assert association["snapshot_id"] == cohort[1]["id"]
    assert association["preparation_version"] == prepared["version_id"]
    checkpoint = torch.load(runtime.checkpoints_dir / entry["filename"], weights_only=True)
    assert checkpoint["imported_source"] == association
    assert checkpoint["classes"] == ["ants", "zebra"]
    assert checkpoint["audio_config"]["target_sr"] == 8000
    assert len(entry["metrics"]) == 1
    with sessions() as db:
        assert runtime.get_history(db) == []
        assert runtime.get_history(db, owner_id=2) == []
        activation = runtime.set_active_model(entry["id"], db)
        assert activation["success"] is False
        from app.services.registry import ModelRegistry
        registry = ModelRegistry()
        assert registry.register_from_db(db, runtime.checkpoints_dir) is None
        assert registry.list_models() == []
    from app.services.imported_training_source import ImportedSourceError
    with pytest.raises(ImportedSourceError):
        runtime.imported_sources.model_source(2, entry["id"])
    from tests.test_api_training import main
    from app.database import get_db
    from app.models.user import Usuario
    from app.services import auth
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-t3-signing-key-not-a-production-secret-2026")
    with sessions() as db:
        for user_id in (1, 2):
            db.add(Usuario(id=user_id, email=f"user{user_id}@example.test", password_hash="unused",
                nombre_completo="Synthetic", rol="investigador", activo=True))
        db.commit()
    previous = main.app.dependency_overrides[get_db]
    def source_db():
        with sessions() as db:
            yield db
    main.app.dependency_overrides[get_db] = source_db
    try:
        owner = {"Authorization": "Bearer " + auth.create_access_token({"sub": "1"})}
        foreign = {"Authorization": "Bearer " + auth.create_access_token({"sub": "2"})}
        assert client.get("/api/training/history").json() == {"history": []}
        assert client.get("/api/training/history?include_imported=true", headers=foreign).json() == {"history": []}
        public_entry, = client.get("/api/training/history?include_imported=true", headers=owner).json()["history"]
        assert public_entry["imported_source"] == association
        activation_url = f"/api/training/models/{entry['id']}/activate"
        assert client.post(activation_url).status_code == 401
        assert client.post(activation_url, headers=foreign).status_code == 404
        response = client.post(activation_url, headers=owner)
        assert response.status_code == 200, response.text
        assert response.json()["success"] is False
        assert client.get("/api/training/progress", headers=owner).json()["status"] == "checkpoint_persisted"
    finally:
        main.app.dependency_overrides[get_db] = previous


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
