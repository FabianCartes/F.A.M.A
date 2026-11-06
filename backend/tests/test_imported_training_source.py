"""Owner-scoped imported adapter admission; real snapshot/preparation artifacts."""
import pytest
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create


def test_foreign_source_is_not_disclosed(cohort, tmp_path):
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from app.services.imported_training_source import ImportedTrainingSource, ImportedSourceError
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    sources = ImportedTrainingSource(preparations)
    for dataset_id, snapshot_id in ((cohort[5], cohort[1]["id"]), ("0" * 32, "0" * 32)):
        with pytest.raises(ImportedSourceError) as failure:
            sources.resolve(2, dataset_id, snapshot_id, prepared["version_id"], architecture="AudioCNN")
        assert failure.value.code == "source_unavailable"
        assert str(failure.value) == "Fuente importada no disponible."


def test_source_pins_classes_and_consumes_verified_audio(cohort, tmp_path):
    import pickle
    import torch
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from app.services.imported_training_source import ImportedTrainingSource, ImportedAudioDataset
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    source = ImportedTrainingSource(preparations).resolve(
        1, cohort[5], cohort[1]["id"], prepared["version_id"], architecture="AudioCNN")
    source = pickle.loads(pickle.dumps(source))
    assert source["classes"] == ["ants", "zebra"]
    assert source["identity"]["profile"] == prepared["profile"]
    dataset = ImportedAudioDataset(source, "train")
    assert len(dataset) == 2
    labels = []
    for waveform, label in dataset:
        assert waveform.shape == (8000,)
        assert torch.isfinite(waveform).all()
        labels.append(label.item())
    assert sorted(labels) == [0, 1]
    model = torch.nn.Linear(8000, 2)
    waveform, label = dataset[0]
    loss = torch.nn.functional.cross_entropy(model(waveform[None]), label[None])
    loss.backward()
    assert model.weight.grad is not None


@pytest.mark.parametrize("damage", ["architecture", "missing", "corrupt", "profile", "split"])
def test_source_rejects_incompatible_or_damaged_selection(cohort, tmp_path, damage):
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from app.services.imported_training_source import ImportedTrainingSource, ImportedSourceError
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    kwargs = {"architecture": "AudioCNN"}
    if damage == "architecture":
        kwargs["architecture"] = "PANNs-CNN14"
    elif damage == "profile":
        kwargs["audio_config"] = {"target_sr": 16000}
    elif damage == "split":
        (preparations.root / prepared["version_id"] / "train.csv").chmod(0o600)
        (preparations.root / prepared["version_id"] / "train.csv").write_bytes(b"corrupt")
    else:
        member = next(cohort[0].iter_verified(1, cohort[1]["id"]))[0]
        path = cohort[0].root / cohort[1]["id"] / member["member_id"]
        path.chmod(0o600)
        path.write_bytes(b"" if damage == "missing" else b"changed")
    with pytest.raises(ImportedSourceError) as failure:
        ImportedTrainingSource(preparations).resolve(1, cohort[5], cohort[1]["id"], prepared["version_id"], **kwargs)
    assert failure.value.code in {"source_unavailable", "profile_conflict"}


@pytest.mark.parametrize("damage", ["revision", "manifest", "index", "migration"])
def test_catalog_retains_metadata_guards_without_audio(cohort, tmp_path, monkeypatch, damage):
    from app.models.dataset_import import ImportedDataset
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    if damage == "migration":
        from app.models.imported_training_source import ImportedModelSource
        ImportedModelSource.__table__.drop(cohort[0].sessions.kw["bind"], checkfirst=True)
    else:
        migrate_imported_sources(cohort[0].sessions.kw["bind"], writers_stopped=True)
    if damage == "revision":
        with cohort[0].sessions() as db:
            db.get(ImportedDataset, cohort[5]).revision += 1
            db.commit()
    elif damage in {"manifest", "index"}:
        path = preparations.root / prepared["version_id"] / ("manifest.json" if damage == "manifest" else "train.csv")
        path.chmod(0o600)
        path.write_bytes(b"altered metadata")

    def no_audio_reads(*args, **kwargs):
        pytest.fail("Catalog must not iterate snapshot audio")

    monkeypatch.setattr(cohort[0], "iter_verified", no_audio_reads)
    entry, = ImportedTrainingSource(preparations).catalog(1)
    assert entry["eligible"] is False
    if damage in {"manifest", "index"}:
        assert entry["preparations"] == []
    else:
        assert entry["reasons"] == ["preparation_stale" if damage == "revision" else "source_migration_required"]
    assert ImportedTrainingSource(preparations).catalog(2) == []
