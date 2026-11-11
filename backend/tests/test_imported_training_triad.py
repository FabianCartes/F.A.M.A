"""Historical three-profile source fixture; imported worker admission is retired."""
from copy import deepcopy
import pytest
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create
from tests.test_training_flow import training_env


@pytest.fixture
def triad(cohort, training_env, tmp_path, monkeypatch):
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    runtime = training_env[0]
    migrate_imported_sources(cohort[0].sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "prepared-triad")
    models = []
    for duration, weight in ((0.5, 0.2), (0.75, 0.3), (1.0, 0.5)):
        profile = deepcopy(cohort[3])
        profile["audio"]["duration_seconds"] = duration
        changed = list(cohort)
        changed[3] = profile
        prepared = create(preparations, changed)
        models.append(dict(architecture="AudioCNN", weight=weight, epochs=1,
                           learning_rate=0.001, batch_size=2,
                           imported_prepared_version=prepared["version_id"]))
    runtime.imported_sources = ImportedTrainingSource(preparations)
    from app.services.imported_triad_records import ImportedTriadRecords
    from app.services.imported_triad_manifests import ImportedTriadManifests
    from app.services.imported_triad_evaluation import ImportedTriadEvaluation
    manifests = ImportedTriadManifests(tmp_path / "triad-manifests")
    runtime.triad_records = ImportedTriadRecords(cohort[0].sessions, manifests,
        ImportedTriadEvaluation(cohort[0].sessions, manifests, runtime.imported_sources,
                                runtime.checkpoints_dir))
    # Retain the fixture's reference shape for historical consumer tests only.
    return runtime, dict(dataset_name="", imported_dataset_id=cohort[5],
        snapshot_id=cohort[1]["id"], owner_id=1, models=models, seed=42), preparations


def test_historical_triad_profiles_remain_readable(triad):
    runtime, references, _ = triad
    sources = runtime.imported_sources.resolve_triad(
        1, references["imported_dataset_id"], references["snapshot_id"],
        [dict(version=m["imported_prepared_version"], architecture=m["architecture"])
         for m in references["models"]])
    assert [s["identity"]["profile"]["audio"]["duration_seconds"] for s in sources] == [0.5, 0.75, 1.0]
    assert all(s["classes"] == ["ants", "zebra"] for s in sources)
    assert runtime.get_progress()["status"] == "idle"
