"""Current-revision admission without invalidating immutable historical sources."""
import pytest

from tests.test_api_training import client
from tests.test_training_flow import training_env
from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_imported_dataset_preparation import cohort, create
from tests.test_imported_training_admission import authenticated

STALE_MESSAGE = (
    "La preparación corresponde a una revisión anterior del dataset. Cree un nuevo "
    "snapshot, complete la procedencia de todos los audios y vuelva a preparar las particiones."
)


def setup_source(cohort, tmp_path, training_env, monkeypatch):
    from app.services import training
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    monkeypatch.setattr(training, "SessionLocal", cohort[0].sessions)
    migrate_imported_sources(cohort[0].sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "revision-prepared")
    prepared = create(preparations, cohort)
    source = ImportedTrainingSource(preparations)
    training_env[0].imported_sources = source
    return source, preparations, prepared


def owner_headers():
    from app.services import auth
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": "1"})}


def selection(cohort, prepared):
    return {"imported_dataset_id": cohort[5], "snapshot_id": cohort[1]["id"],
            "imported_prepared_version": prepared["version_id"], "architecture": "AudioCNN"}


def test_stale_start_rejects_without_job_or_history_changes(
    client, training_env, cohort, tmp_path, authenticated, monkeypatch,
):
    from app.models.dataset_import import ImportedDataset
    source, preparations, prepared = setup_source(cohort, tmp_path, training_env, monkeypatch)
    # Fixture-only revision change: independent of the parallel feedback writer.
    with cohort[0].sessions.begin() as db:
        db.get(ImportedDataset, cohort[5]).revision += 1
    headers = owner_headers()
    before = client.get("/api/training/progress", headers=headers).json()
    history = client.get("/api/training/history?include_imported=true", headers=headers).json()
    response = client.post("/api/training/start", headers=headers, json=selection(cohort, prepared))
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": {"code": "preparation_stale", "message": STALE_MESSAGE}}
    assert client.get("/api/training/progress", headers=headers).json() == before
    assert client.get("/api/training/history?include_imported=true", headers=headers).json() == history
    training_env[3].assert_not_called()
    catalog = client.get("/api/training/datasets?include_imported=true", headers=headers)
    assert catalog.status_code == 200, catalog.text
    entry, = [row for row in catalog.json()["datasets"] if row.get("source_type") == "imported"]
    assert entry["id"] == cohort[5]
    assert entry["eligible"] is False
    assert entry["reasons"] == ["preparation_stale"]
    choice, = entry["preparations"]
    assert choice["eligible"] is False
    assert choice["reasons"] == ["preparation_stale"]
    assert preparations.get(1, cohort[1]["id"], prepared["version_id"]) == prepared
    assert cohort[0].get(1, cohort[1]["id"]) == cohort[1]
    historical = source.resolve(1, cohort[5], cohort[1]["id"], prepared["version_id"], architecture="AudioCNN")
    assert historical["identity"]["snapshot_id"] == cohort[1]["id"]
    assert sum(map(len, historical["splits"].values())) == 6


def test_new_cohort_requires_annotations_and_admits_all_current_members(
    client, training_env, cohort, tmp_path, authenticated, monkeypatch,
):
    from training.imported_dataset_preparation import PreparationError
    from tests.test_dataset_zip_validation import wav_bytes
    source, preparations, old = setup_source(cohort, tmp_path, training_env, monkeypatch)
    original_snapshot = cohort[0].get(1, cohort[1]["id"])
    job = prepare(cohort[4], tmp_path, key="revision-growth", target_id=cohort[5],
                  entries=[("ants/new.wav", wav_bytes(20)), ("zebra/new.wav", wav_bytes(21))])
    added = confirm(cohort[4], job)
    assert added.status_code == 200, added.text
    current = cohort[0].create(1, cohort[5])
    assert current["dataset_revision"] > original_snapshot["dataset_revision"]
    assert current["file_count"] == 8
    assert current["id"] != original_snapshot["id"]
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, current["id"], mapping=cohort[2],
                            provenance={"source": "explicit synthetic annotations"},
                            seed=42, profile=cohort[3])
    assert failure.value.code == "invalid_mapping"
    members = [member for member, _ in cohort[0].iter_verified(1, current["id"])]
    mapping = [{"member_id": member["member_id"], "recording_id": member["original_path"],
                "group_id": member["original_path"].split("/")[-1]} for member in members]
    prepared = preparations.create(1, current["id"], mapping=mapping,
                                  provenance={"source": "explicit synthetic annotations"},
                                  seed=42, profile=cohort[3])
    resolved = source.resolve_for_training(1, cohort[5], current["id"],
                                          prepared["version_id"], architecture="AudioCNN")
    all_rows = [row for rows in resolved["splits"].values() for row in rows]
    assert len(all_rows) == 8
    assert {row["member_id"] for row in all_rows} == {member["member_id"] for member in members}
    assert {row["original_path"] for row in all_rows} >= {"ants/new.wav", "zebra/new.wav"}
    for split, rows in resolved["splits"].items():
        assert {row["class_name"] for row in rows} == {"ants", "zebra"}
        others = [row for name, values in resolved["splits"].items() if name != split for row in values]
        for key in ("group_id", "recording_id"):
            assert not ({row[key] for row in rows} & {row[key] for row in others})
    assert cohort[0].get(1, original_snapshot["id"]) == original_snapshot
    assert preparations.get(1, original_snapshot["id"], old["version_id"]) == old
    assert source.resolve(1, cohort[5], original_snapshot["id"], old["version_id"],
                          architecture="AudioCNN")["identity"]["snapshot_id"] == original_snapshot["id"]
    headers = owner_headers()
    response = client.get("/api/training/datasets?include_imported=true", headers=headers)
    assert response.status_code == 200, response.text
    entry, = [row for row in response.json()["datasets"] if row.get("source_type") == "imported"]
    assert entry["eligible"] is True
    choices = {row["snapshot_id"]: row for row in entry["preparations"]}
    assert choices[original_snapshot["id"]]["reasons"] == ["preparation_stale"]
    assert choices[current["id"]]["eligible"] is True
    training_env[3].assert_not_called()  # Preparation never starts a job.
    body = {**selection(cohort, prepared), "snapshot_id": current["id"]}
    response = client.post("/api/training/start", headers=headers, json=body)
    assert response.status_code == 200, response.text
    admitted = training_env[3].call_args.kwargs["args"][0]["source"]
    assert admitted["identity"]["snapshot_id"] == current["id"]
    assert sum(map(len, admitted["splits"].values())) == 8
