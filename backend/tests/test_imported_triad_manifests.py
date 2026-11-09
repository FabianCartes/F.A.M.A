"""Public immutable composition seam; synthetic admitted sources only."""
from copy import deepcopy
import hashlib
import json

import pytest
from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort
from tests.test_imported_triad_source import setup_sources


@pytest.fixture
def references(cohort, tmp_path):
    source, choices = setup_sources(cohort, tmp_path)
    admitted = source.resolve_triad_for_training(1, cohort[5], cohort[1]["id"], choices)
    return [{"model_id": i + 1, "checkpoint_sha256": str(i + 1) * 64,
             "imported_source": item["identity"]} for i, item in enumerate(admitted)]


def test_roundtrip_exact_weights_and_immutable_revisions(references, tmp_path):
    from app.services.imported_triad_manifests import ImportedTriadManifests
    store = ImportedTriadManifests(tmp_path / "compositions")
    original = deepcopy(references)
    weights = [0.2000000001, 0.3, 0.5]
    first = store.create(1, references, weights)
    assert first["manifest"]["weights"] == weights
    assert first["manifest"]["components"] == original
    assert store.get(1, first["id"]) == first
    assert store.create(1, references, weights) == first
    second = store.create(1, references, [0.1, 0.4, 0.5])
    assert second["id"] != first["id"]
    assert store.get(1, first["id"]) == first
    reverse = store.create(1, list(reversed(references)), weights)
    assert reverse["id"] != first["id"]
    assert references == original
    first["manifest"]["components"][0]["imported_source"]["classes"].append("changed")
    assert store.get(1, second["id"]) == second


@pytest.mark.parametrize("damage", ["foreign", "dataset", "snapshot", "manifest", "classes",
    "classmap", "profile", "hash", "model", "duplicate", "path", "owner_override", "count",
    "negative", "zero", "sum", "nan", "inf", "bool", "tuple"])
def test_invalid_creation_preserves_published_descriptor(references, tmp_path, damage):
    from app.services.imported_triad_manifests import ImportedTriadManifests, ImportedTriadManifestError
    store = ImportedTriadManifests(tmp_path / "compositions")
    before = store.create(1, references, [0.2, 0.3, 0.5])
    refs, weights = deepcopy(references), [0.2, 0.3, 0.5]
    identity = refs[1]["imported_source"]
    if damage == "foreign": identity["owner_id"] = 2
    elif damage == "dataset": identity["dataset_id"] = "e" * 32
    elif damage == "snapshot": identity["snapshot_id"] = "e" * 32
    elif damage == "manifest": identity["snapshot_manifest_sha256"] = "e" * 64
    elif damage == "classes":
        identity["classes"] = ["other"]
        identity["class_to_index"] = {"other": 0}
    elif damage == "classmap": identity["class_to_index"] = {}
    elif damage == "profile": identity["profile"]["architecture"] = "unknown"
    elif damage == "hash": refs[1]["checkpoint_sha256"] = "bad"
    elif damage == "model": refs[1]["model_id"] = True
    elif damage == "duplicate": refs[1]["model_id"] = refs[0]["model_id"]
    elif damage == "path": refs[1]["model_id"] = "gs://bucket/weights"
    elif damage == "owner_override": refs[1]["owner_id"] = 1
    elif damage == "count": refs.pop()
    elif damage == "negative": weights = [-0.1, 0.6, 0.5]
    elif damage == "zero": weights = [0, 0, 0]
    elif damage == "sum": weights = [0.2, 0.3, 0.6]
    elif damage == "nan": weights = [float("nan"), 0, 1]
    elif damage == "inf": weights = [float("inf"), 0, 1]
    elif damage == "bool": weights = [True, 0, 0]
    elif damage == "tuple": weights = (0.2, 0.3, 0.5)
    with pytest.raises(ImportedTriadManifestError) as failure:
        store.create(1, refs, weights)
    assert failure.value.code == "composition_unavailable"
    assert store.get(1, before["id"]) == before


@pytest.mark.parametrize("damage", ["bytes", "version", "owner", "source", "symlink", "oversize"])
def test_read_fails_closed_and_does_not_repair(references, tmp_path, damage):
    from app.services.imported_triad_manifests import ImportedTriadManifests, ImportedTriadManifestError
    root = tmp_path / "compositions"
    store = ImportedTriadManifests(root)
    first = store.create(1, references, [0.2, 0.3, 0.5])
    artifact_id = first["id"]
    path = root / (artifact_id + ".json")
    if damage in ("version", "owner", "source"):
        manifest = deepcopy(first["manifest"])
        if damage == "version": manifest["schema_version"] = 2
        elif damage == "owner": manifest["cohort"]["owner_id"] = 2
        else: manifest["components"][2]["imported_source"]["snapshot_id"] = "f" * 32
        data = json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")).encode()
        artifact_id = hashlib.sha256(data).hexdigest()
        path = root / (artifact_id + ".json")
        path.write_bytes(data)
    elif damage == "symlink":
        artifact_id = "f" * 64
        path = root / (artifact_id + ".json")
        path.symlink_to(root / (first["id"] + ".json"))
    else:
        path.chmod(0o600)
        path.write_bytes(b"x" * (1024 * 1024 + 1) if damage == "oversize" else b"{}")
    before = path.read_bytes()
    with pytest.raises(ImportedTriadManifestError):
        store.get(1, artifact_id)
    assert path.read_bytes() == before
    if damage in ("bytes", "oversize"):
        with pytest.raises(ImportedTriadManifestError):
            store.create(1, references, [0.2, 0.3, 0.5])
        assert path.read_bytes() == before


def test_missing_foreign_and_invalid_ids_share_private_error(references, tmp_path):
    from app.services.imported_triad_manifests import ImportedTriadManifests, ImportedTriadManifestError
    store = ImportedTriadManifests(tmp_path / "compositions")
    first = store.create(1, references, [1, 0, 0])
    errors = []
    for owner, artifact_id in [(2, first["id"]), (1, "f" * 64), (1, "../escape"),
                               (True, first["id"]), (1, "gs://bucket/file")]:
        with pytest.raises(ImportedTriadManifestError) as failure:
            store.get(owner, artifact_id)
        errors.append((failure.value.code, str(failure.value)))
    assert len(set(errors)) == 1
    assert store.get(1, first["id"]) == first


@pytest.mark.parametrize("kind", ["root_link", "ancestor_link", "traversal", "relative", "public"])
def test_unsafe_configured_root_rejected_without_outside_writes(tmp_path, kind):
    from app.services.imported_triad_manifests import ImportedTriadManifests, ImportedTriadManifestError
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    if kind in ("root_link", "ancestor_link"):
        link = tmp_path / "link"
        link.symlink_to(outside, target_is_directory=True)
        root = link if kind == "root_link" else link / "child"
    elif kind == "traversal": root = str(tmp_path) + "/../escape"
    elif kind == "relative": root = "relative-compositions"
    else:
        outside.chmod(0o755)
        root = outside
    with pytest.raises(ImportedTriadManifestError):
        ImportedTriadManifests(root)
    assert list(outside.iterdir()) == []


def test_root_privacy_is_rechecked_on_read(references, tmp_path):
    from app.services.imported_triad_manifests import ImportedTriadManifests, ImportedTriadManifestError
    root = tmp_path / "compositions"
    store = ImportedTriadManifests(root)
    first = store.create(1, references, [1, 0, 0])
    root.chmod(0o755)
    with pytest.raises(ImportedTriadManifestError):
        store.get(1, first["id"])


def test_repeated_architecture_does_not_replace_component_identity(references, tmp_path):
    from app.services.imported_triad_manifests import ImportedTriadManifests
    refs = deepcopy(references)
    refs[2]["imported_source"] = deepcopy(refs[0]["imported_source"])
    store = ImportedTriadManifests(tmp_path / "compositions")
    result = store.create(1, refs, [1, 0, 0])
    assert result["manifest"]["components"] == refs
    assert result["manifest"]["cohort"]["owner_id"] == 1
    assert store.get(1, result["id"]) == result


def test_replaced_root_and_published_symlink_fail_closed(references, tmp_path):
    from app.services.imported_triad_manifests import ImportedTriadManifests, ImportedTriadManifestError
    root = tmp_path / "compositions"
    store = ImportedTriadManifests(root)
    first = store.create(1, references, [1, 0, 0])
    # An attacker can anticipate the ID; a symlink must not count as idempotence.
    other = ImportedTriadManifests(tmp_path / "other")
    (other.root / (first["id"] + ".json")).symlink_to(root / (first["id"] + ".json"))
    with pytest.raises(ImportedTriadManifestError):
        other.create(1, references, [1, 0, 0])
    # Simulate an ancestor swap only within this fixture's private tree.
    saved = tmp_path / "saved"
    root.rename(saved)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ImportedTriadManifestError):
        store.create(1, references, [1, 0, 0])
    with pytest.raises(ImportedTriadManifestError):
        store.get(1, first["id"])
    assert list(outside.iterdir()) == []
