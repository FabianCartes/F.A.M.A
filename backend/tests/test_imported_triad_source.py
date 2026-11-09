"""Triad source resolution through real immutable synthetic preparations."""
from copy import deepcopy

import pytest
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create


def test_single_admission_normalizes_missing_and_unexpected_options(cohort, tmp_path):
    from app.services.imported_training_source import ImportedSourceError
    source, choices = setup_sources(cohort, tmp_path)
    before = source.catalog(1)
    failures = {}
    for case, options in (("missingarchitecture", {}),
                          ("unexpectedoption", {"architecture": "AudioCNN", "unexpected": True})):
        try:
            source.resolve_for_training(1, cohort[5], cohort[1]["id"],
                                        choices[0]["version"], **options)
        except Exception as error:
            failures[case] = error
        assert source.catalog(1) == before
    assert {case: type(error).__name__ for case, error in failures.items()} == {
        "missingarchitecture": "ImportedSourceError", "unexpectedoption": "ImportedSourceError"}
    for error in failures.values():
        assert isinstance(error, ImportedSourceError)
        assert error.code == "source_unavailable"
        assert str(error) == "Fuente importada no disponible."


def setup_sources(cohort, tmp_path):
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "triad-prepared")
    choices = []
    for architecture, name in (("audio_cnn", "AudioCNN"),
                              ("efficientnet_b0", "EfficientNet-B0"),
                              ("resnet34d", "ResNet-34d")):
        profile = deepcopy(cohort[3])
        profile["architecture"] = architecture
        prepared = preparations.create(1, cohort[1]["id"], mapping=cohort[2],
            provenance={"source": "synthetic annotations v1"}, seed=42, profile=profile)
        choices.append({"version": prepared["version_id"], "architecture": name})
    return ImportedTrainingSource(preparations), choices


@pytest.mark.parametrize("components", [[], [{"version": "0" * 64, "architecture": "AudioCNN"}] * 2,
    [{"version": "0" * 64, "architecture": "AudioCNN"}] * 4,
    [{"version": "0" * 64, "architecture": "AudioCNN", "owner": 2}] * 3])
def test_invalid_component_schema_is_private_and_nonmutating(cohort, tmp_path, components):
    from app.services.imported_training_source import ImportedSourceError
    source, _ = setup_sources(cohort, tmp_path)
    before = source.catalog(1)
    with pytest.raises(ImportedSourceError) as failure:
        source.resolve_triad_for_training(1, cohort[5], cohort[1]["id"], components)
    assert failure.value.code == "source_unavailable"
    assert source.catalog(1) == before


@pytest.mark.parametrize("change", ["groups", "recordings", "seed", "provenance"])
def test_different_cohort_annotations_rejected_without_mutation(cohort, tmp_path, change):
    from app.services.imported_training_source import ImportedSourceError
    source, choices = setup_sources(cohort, tmp_path)
    mapping = deepcopy(cohort[2])
    provenance = {"source": "synthetic annotations v1"}
    seed = 42
    if change == "groups":
        for row in mapping:
            row["group_id"] = "renamed-" + row["group_id"]
    elif change == "recordings":
        for row in mapping:
            row["recording_id"] = "renamed-" + row["recording_id"]
    elif change == "seed":
        seed = 43
    else:
        provenance = {"source": "different annotation provenance"}
    prepared = source.preparations.create(1, cohort[1]["id"], mapping=mapping,
        provenance=provenance, seed=seed, profile=cohort[3])
    choices[2] = {"version": prepared["version_id"], "architecture": "AudioCNN"}
    # Each alternative is independently valid, but not a common triad cohort.
    source.resolve_for_training(1, cohort[5], cohort[1]["id"], **choices[2])
    before = source.catalog(1)
    with pytest.raises(ImportedSourceError) as failure:
        source.resolve_triad_for_training(1, cohort[5], cohort[1]["id"], choices)
    assert failure.value.code == "source_unavailable"
    assert source.catalog(1) == before


@pytest.mark.parametrize("damage", ["owner", "dataset", "snapshot", "revision", "archive", "profile", "missing"])
def test_triad_reuses_admission_and_component_guards(cohort, tmp_path, damage):
    from app.models.dataset_import import ImportedDataset
    from app.services.imported_training_source import ImportedSourceError
    source, choices = setup_sources(cohort, tmp_path)
    owner, dataset_id, snapshot_id = 1, cohort[5], cohort[1]["id"]
    if damage == "owner":
        owner = 2
    elif damage == "dataset":
        dataset_id = "0" * 32
    elif damage == "snapshot":
        snapshot_id = "0" * 32
    elif damage == "revision":
        with cohort[0].sessions.begin() as db:
            db.get(ImportedDataset, dataset_id).revision += 1
    elif damage == "archive":
        dataset = cohort[4].get('/api/ingestion/imports/datasets').json()['datasets'][0]
        assert cohort[4].request('DELETE', f'/api/ingestion/imports/datasets/{dataset_id}',
            json={'revision': dataset['revision']}).status_code == 204
    elif damage == "profile":
        choices[2]["audio_config"] = {"target_sr": 16000}
    else:
        choices[2]["version"] = "0" * 64
    before = source.catalog(1)
    available = cohort[4].get('/api/ingestion/imports/datasets').json()
    with pytest.raises(ImportedSourceError) as failure:
        source.resolve_triad_for_training(owner, dataset_id, snapshot_id, choices)
    assert failure.value.code == ("preparation_stale" if damage == "revision" else
                                  "profile_conflict" if damage == "profile" else "source_unavailable")
    assert source.catalog(1) == before
    assert cohort[4].get('/api/ingestion/imports/datasets').json() == available


def test_triad_missing_archive_schema_preserves_503(cohort, tmp_path):
    from fastapi import HTTPException
    from sqlalchemy import text
    source, choices = setup_sources(cohort, tmp_path)
    # Synthetic SQLite fixture schema only; no admission collaborator is mocked.
    with cohort[0].sessions.begin() as db:
        db.execute(text('ALTER TABLE imported_dataset RENAME COLUMN archived TO unavailable_archived'))
    with pytest.raises(HTTPException) as failure:
        source.resolve_triad_for_training(1, cohort[5], cohort[1]["id"], choices)
    assert failure.value.status_code == 503


def test_triad_admission_is_common_before_capture(cohort, tmp_path, monkeypatch):
    source, choices = setup_sources(cohort, tmp_path)
    original = source.resolve
    captures = []
    def capture(*args, **kwargs):
        if not captures:
            dataset = cohort[4].get('/api/ingestion/imports/datasets').json()['datasets'][0]
            assert cohort[4].request('DELETE', f'/api/ingestion/imports/datasets/{cohort[5]}',
                json={'revision': dataset['revision']}).status_code == 204
        captures.append(kwargs["version"])
        return original(*args, **kwargs)
    # Instrument capture, not admission: archive through its actual public route.
    monkeypatch.setattr(source, "resolve", capture)
    resolved = source.resolve_triad_for_training(1, cohort[5], cohort[1]["id"], choices)
    assert len(resolved) == 3
    assert captures == [c["version"] for c in choices]
    assert source.catalog(1) == []


@pytest.mark.parametrize("change", ["classes", "splits", "policy"])
def test_hash_valid_alternate_cohort_is_not_compatible(cohort, tmp_path, change):
    import csv
    import hashlib
    import io
    import json
    from app.services.imported_training_source import ImportedSourceError
    from training.imported_dataset_preparation import INDEPENDENT_PROVENANCE
    source, choices = setup_sources(cohort, tmp_path)
    if change == "policy":
        mapping = [dict(member_id=r["member_id"], recording_id=r["member_id"],
                        group_id=r["member_id"]) for r in cohort[2]]
        alternate = source.preparations.create(1, cohort[1]["id"], mapping=mapping,
            provenance=INDEPENDENT_PROVENANCE, seed=42, profile=cohort[3])
        version = alternate["version_id"]
    else:
        # Construct a hash-valid immutable synthetic version: swapped partitions
        # or reversed output indices, not a corrupted file or a mocked resolver.
        root = source.preparations.root / choices[0]["version"]
        manifest = json.loads((root / "manifest.json").read_bytes())
        payloads = {name: (root / name).read_bytes() for name in manifest["files"]}
        if change == "splits":
            payloads["train.csv"], payloads["val.csv"] = payloads["val.csv"], payloads["train.csv"]
        else:
            manifest["class_to_index"] = {"ants": 1, "zebra": 0}
            for name, raw in payloads.items():
                reader = csv.DictReader(io.StringIO(raw.decode()))
                rows, fields = list(reader), reader.fieldnames
                stream = io.StringIO(newline="")
                writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    row["class_index"] = manifest["class_to_index"][row["class_name"]]
                    writer.writerow(row)
                payloads[name] = stream.getvalue().encode()
        manifest["files"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()}
        manifest.pop("version_id")
        def encode(value):
            return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
        version = hashlib.sha256(encode(manifest)).hexdigest()
        manifest["version_id"] = version
        target = source.preparations.root / version
        target.mkdir()
        for name, raw in payloads.items():
            (target / name).write_bytes(raw)
        (target / "manifest.json").write_bytes(encode(manifest))
    choices[2] = {"version": version, "architecture": "AudioCNN"}
    alternate = source.resolve_for_training(1, cohort[5], cohort[1]["id"], **choices[2])
    assert alternate["preparation"]["manifest"]["seed"] == 42
    before = source.catalog(1)
    with pytest.raises(ImportedSourceError):
        source.resolve_triad_for_training(1, cohort[5], cohort[1]["id"], choices)
    assert source.catalog(1) == before


def test_compatible_triad_preserves_order_profiles_and_single_resolution(cohort, tmp_path):
    source, choices = setup_sources(cohort, tmp_path)
    resolved = source.resolve_triad_for_training(1, cohort[5], cohort[1]["id"], choices)
    assert [s["identity"]["preparation_version"] for s in resolved] == [c["version"] for c in choices]
    assert [s["identity"]["profile"]["architecture"] for s in resolved] == [
        "audio_cnn", "efficientnet_b0", "resnet34d"]
    assert all(s["classes"] == ["ants", "zebra"] for s in resolved)
    assert source.resolve_for_training(1, cohort[5], cohort[1]["id"], **choices[0]) == resolved[0]
    assert source.resolve_triad_for_training(1, cohort[5], cohort[1]["id"], [choices[0]] * 3) == [resolved[0]] * 3
