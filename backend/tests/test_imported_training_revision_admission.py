"""Historical prepared sources remain readable after dataset revision changes."""
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create


def test_revision_change_preserves_historical_source(cohort, tmp_path):
    from app.models.dataset_import import ImportedDataset
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "revision-prepared")
    prepared = create(preparations, cohort)
    with cohort[0].sessions.begin() as db:
        db.get(ImportedDataset, cohort[5]).revision += 1
    source = ImportedTrainingSource(preparations).resolve(
        1, cohort[5], cohort[1]["id"], prepared["version_id"], architecture="AudioCNN")
    assert source["identity"]["snapshot_id"] == cohort[1]["id"]
    assert sum(map(len, source["splits"].values())) == 6
    assert preparations.get(1, cohort[1]["id"], prepared["version_id"]) == prepared
    assert cohort[0].get(1, cohort[1]["id"]) == cohort[1]
