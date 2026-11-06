"""Automatic preparation at the public create/get/read_split boundary."""
import pytest

from tests.test_imported_dataset_preparation import cohort, service, create
from tests.test_dataset_import_api import imports


ASSUMPTION = {"source": "per-wav-independent-assumption-v1"}


def independent_mapping(cohort):
    return [dict(member_id=r["member_id"], recording_id=r["member_id"],
                 group_id=r["member_id"]) for r in cohort[2]]


@pytest.mark.parametrize("cohort", [[(label, i) for label in ("ants", "zebra")
                                     for i in range(597)]], indirect=True)
def test_automatic_large_cohort_is_stratified_reproducible_and_versioned(cohort, tmp_path):
    preparations = service(cohort, tmp_path)
    kwargs = dict(mapping=independent_mapping(cohort), provenance=ASSUMPTION,
                  seed=42, profile=cohort[3])
    result = preparations.create(1, cohort[1]["id"], **kwargs)
    assert result["policy"]["name"] == "per-wav-stratified-70-15-15-v1"
    assert result["policy"]["target"] == [0.7, 0.15, 0.15]
    assert result["provenance"] == ASSUMPTION
    assert preparations.get(1, cohort[1]["id"], result["version_id"]) == result
    assert preparations.create(1, cohort[1]["id"], **kwargs) == result
    splits = [preparations.read_split(1, cohort[1]["id"], result["version_id"], s)
              for s in ("train", "val", "test")]
    assert sum(map(len, splits)) == 1194
    for rows, target in zip(splits, (0.7, 0.15, 0.15)):
        assert abs(len(rows) / 1194 - target) < 0.005
        assert {r["class_name"] for r in rows} == {"ants", "zebra"}
    groups = [{r["group_id"] for r in rows} for rows in splits]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    changed = preparations.create(1, cohort[1]["id"], **dict(kwargs, seed=43))
    assert changed["version_id"] != result["version_id"]
    assert preparations.read_split(1, cohort[1]["id"], changed["version_id"], "train") != splits[0]


def test_minimum_coverage_and_exact_sentinel_dispatch(cohort, tmp_path):
    preparations = service(cohort, tmp_path)
    kwargs = dict(mapping=independent_mapping(cohort), provenance=ASSUMPTION,
                  seed=42, profile=cohort[3])
    result = preparations.create(1, cohort[1]["id"], **kwargs)
    for split in ("train", "val", "test"):
        rows = preparations.read_split(1, cohort[1]["id"], result["version_id"], split)
        assert len(rows) == 2
        assert {r["class_name"] for r in rows} == {"ants", "zebra"}
    explicit = preparations.create(1, cohort[1]["id"], **dict(
        kwargs, provenance=dict(ASSUMPTION, additional="explicit annotation")))
    assert explicit["policy"]["name"] == "group-cover-v1"
    assert preparations.get(1, cohort[1]["id"], result["version_id"]) == result


@pytest.mark.parametrize("cohort", [[(label, i) for label in ("ants", "zebra")
                                     for i in range(2)]], indirect=True)
def test_insufficient_wavs_do_not_publish(cohort, tmp_path):
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, cohort[1]["id"], mapping=independent_mapping(cohort),
                            provenance=ASSUMPTION, seed=42, profile=cohort[3])
    assert failure.value.code == "split_impossible"
    assert not preparations.root.exists()


@pytest.mark.parametrize("field", ["recording_id", "group_id"])
def test_forged_assumption_is_rejected_atomically_and_legacy_still_reads(cohort, tmp_path, field):
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    legacy = create(preparations, cohort)
    before = set(preparations.root.iterdir())
    mapping = independent_mapping(cohort)
    mapping[0][field] = "forged-identity"
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, cohort[1]["id"], mapping=mapping,
                            provenance=ASSUMPTION, seed=42, profile=cohort[3])
    assert failure.value.code == "invalid_mapping"
    assert set(preparations.root.iterdir()) == before
    assert preparations.get(1, cohort[1]["id"], legacy["version_id"]) == legacy
    assert legacy["policy"]["name"] == "group-cover-v1"
