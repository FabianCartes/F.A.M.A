"""Historical imported composition readmission; automatic worker creation retired."""
import pytest
from tests.test_imported_training_triad import triad
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort
from tests.test_training_flow import training_env
from tests.test_training_persistence import persistence_env, start as start_legacy


def test_existing_three_profile_composition_is_readable_without_training(triad, training_env, monkeypatch):
    from app.models.training import Modelo
    from app.services.registry import ModelRegistry, ModelNotFoundError
    from tests.test_imported_training_evaluation import publish_preexisting_imported_checkpoint
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    runtime, references, preparations = triad
    components = []
    for index, member in enumerate(references["models"]):
        model_id, identity = publish_preexisting_imported_checkpoint(
            runtime, preparations.snapshots.sessions, runtime.imported_sources,
            owner_id=1, dataset_id=references["imported_dataset_id"],
            snapshot_id=references["snapshot_id"],
            prepared_version=member["imported_prepared_version"], filename=f"historical-component-{index}.pt")
        with preparations.snapshots.sessions() as db:
            digest = db.get(Modelo, model_id).hash_binario
        components.append(dict(model_id=model_id, checkpoint_sha256=digest, imported_source=identity))
    records = runtime.triad_records
    descriptor = records.manifests.create(1, components, [0.2, 0.3, 0.5])
    saved = records.create(1, descriptor["id"])
    reread = records.read_admitted(1, saved["model"].id_modelo)
    assert reread["manifest"]["components"] == components
    assert reread["manifest"]["weights"] == [0.2, 0.3, 0.5]
    assert reread["pair_ids"] == saved["pair_ids"]
    registry = ModelRegistry(triad_records=records)
    with preparations.snapshots.sessions() as db:
        registry.publish_from_db(db, runtime.checkpoints_dir, owner_id=1)
    assert registry.get(saved["predictor"].model_id, owner_id=1).classes == ("ants", "zebra")
    with pytest.raises(ModelNotFoundError):
        registry.get(saved["predictor"].model_id, owner_id=2)
    assert registry.get_default_model_id() is None
    assert runtime.get_progress()["status"] == "idle"
    training_env[3].assert_not_called()


def test_legacy_ensemble_keeps_eval4_without_triad_factory(persistence_env, monkeypatch):
    from app.services.imported_triad_records import ImportedTriadRecords
    runtime, sessions, _, _ = persistence_env
    def forbidden(*args, **kwargs):
        pytest.fail("legacy ensemble must not configure a triad")
    monkeypatch.setattr(ImportedTriadRecords, "for_training", forbidden)
    start_legacy(runtime, models=[dict(architecture="fixture", weight=0.5),
                                dict(architecture="fixture", weight=0.5)])
    progress = runtime.get_progress()
    assert progress["status"] == "completed", progress
    assert not progress["ensemble_available"]
    assert progress["composition_model_id"] is None
    with sessions() as db:
        history = runtime.get_history(db)
        assert len(history) == 2
        assert all(h["status"] == "standard_component_evaluated" and not h["active"] for h in history)
