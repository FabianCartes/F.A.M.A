"""Imported preparation at the public owner/snapshot/version seam; real T1 source."""
import pytest

from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_dataset_zip_validation import wav_bytes


@pytest.fixture
def cohort(imports, tmp_path, request):
    from app.database import Base
    from app.services.training_snapshots import TrainingSnapshots
    client, source, _, sessions = imports
    Base.metadata.create_all(sessions.kw["bind"])
    pairs = getattr(request, "param", [(label, i) for label in ("zebra", "ants") for i in range(3)])
    job = prepare(client, tmp_path, entries=[
        (f"{label}/{group}.wav", wav_bytes(1 + i)) for i, (label, group) in enumerate(pairs)
    ])
    dataset = confirm(client, job).json()["dataset_id"]
    snapshots = TrainingSnapshots(sessions, source, tmp_path / "snapshots")
    snapshot = snapshots.create(1, dataset)
    members = {m["member_id"]: m for m, _ in snapshots.iter_verified(1, snapshot["id"])}
    mapping = [dict(member_id=m["member_id"], recording_id=m["original_path"],
                    group_id=m["original_path"].split("/")[-1]) for m in members.values()]
    profile = dict(architecture="audio_cnn", channels=1, preprocessing="mono_mel",
                   windowing="energy_peak_pad", window_hop_seconds=0.5,
                   audio=dict(target_sr=8000, duration_seconds=1.0, n_mels=32,
                              n_fft=256, hop_length=64, f_min=0.0, f_max=4000.0,
                              use_gpu_frontend=False))
    return snapshots, snapshot, mapping, profile, client, dataset


def service(cohort, tmp_path):
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    return ImportedDatasetPreparation(cohort[0], tmp_path / "prepared")


def create(preparations, cohort, **changes):
    _, snapshot, mapping, profile, _, _ = cohort
    return preparations.create(1, snapshot["id"], mapping=mapping,
                               provenance={"source": "synthetic annotations v1"},
                               seed=42, profile=profile, **changes)


@pytest.mark.parametrize("damage", ["missing", "extra", "duplicate", "empty_group", "recording_conflict", "provenance"])
def test_mapping_must_cover_exact_membership_without_mutation(cohort, tmp_path, damage):
    from copy import deepcopy
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    mapping = deepcopy(cohort[2])
    provenance = {"source": "synthetic annotations v1"}
    if damage == "missing":
        mapping.pop()
    elif damage == "extra":
        mapping.append(dict(member_id="unknown", recording_id="other", group_id="other"))
    elif damage == "duplicate":
        mapping.append(dict(mapping[0]))
    elif damage == "empty_group":
        mapping[0]["group_id"] = " "
    elif damage == "recording_conflict":
        mapping[0]["recording_id"] = mapping[1]["recording_id"]
        mapping[0]["group_id"] = "conflicting-group"
    else:
        provenance = {}
    catalog = cohort[4].get("/api/ingestion/imports/datasets").json()
    before = set(preparations.root.iterdir())
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, cohort[1]["id"], mapping=mapping, provenance=provenance,
                            seed=42, profile=cohort[3])
    assert failure.value.code == "invalid_mapping"
    assert failure.value.state == "failed"
    assert preparations.get(1, cohort[1]["id"], prior["version_id"]) == prior
    assert set(preparations.root.iterdir()) == before
    assert cohort[4].get("/api/ingestion/imports/datasets").json() == catalog
    assert len({m["member_id"] for m, _ in cohort[0].iter_verified(1, cohort[1]["id"])}) == 6


@pytest.mark.parametrize("field,value", [
    ("audio", None), ("channels", 2), ("architecture", "unrecognized"),
    ("preprocessing", "hpss"), ("windowing", "random"),
    ("window_hop_seconds", float("nan")), ("window_hop_seconds", 0),
    ("audio.target_sr", 0), ("audio.target_sr", True),
    ("audio.duration_seconds", float("inf")), ("audio.duration_seconds", 0.001),
    ("audio.f_min", -1), ("audio.f_min", float("nan")),
    ("audio.f_max", 4001), ("audio.f_max", None),
    ("audio.n_fft", 257), ("audio.hop_length", 512),
    ("audio.n_mels", 16), ("audio.use_gpu_frontend", "false"),
    ("architecture", "panns_cnn14"),
])
def test_profile_is_explicit_finite_and_architecture_compatible(cohort, tmp_path, field, value):
    from copy import deepcopy
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    profile = deepcopy(cohort[3])
    parent = profile
    if "." in field:
        section, field = field.split(".")
        parent = profile[section]
    if value is None:
        parent.pop(field)
    else:
        parent[field] = value
    before = set(preparations.root.iterdir())
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, cohort[1]["id"], mapping=cohort[2], provenance={"source": "test"},
                            seed=42, profile=profile)
    assert failure.value.code == "invalid_profile"
    assert set(preparations.root.iterdir()) == before
    assert preparations.get(1, cohort[1]["id"], prior["version_id"]) == prior


@pytest.mark.parametrize("damage", ["not_wav", "truncated", "stereo_header"])
def test_unreadable_wav_aborts_without_publication(cohort, tmp_path, damage):
    import hashlib
    from app.models.dataset_import_metadata import DatasetMember
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    snapshots = cohort[0]
    # Synthetic import storage/catalog only: build a real, hash-valid T1 snapshot
    # whose bytes cannot be consumed as the supported PCM WAV format.
    with snapshots.sessions.begin() as db:
        member = db.query(DatasetMember).order_by(DatasetMember.id).first()
        path = snapshots.source.root / "objects" / member.source_import_id / member.stored_name
        raw = path.read_bytes()
        if damage == "not_wav":
            raw = b"not wave data"
        elif damage == "truncated":
            raw = raw[:-1]
        else:
            raw = raw[:22] + b"\xff\x7f" + raw[24:]
        path.write_bytes(raw)
        member.sha256, member.size_bytes = hashlib.sha256(raw).hexdigest(), len(raw)
    invalid = snapshots.create(1, cohort[5])
    before = set(preparations.root.iterdir())
    catalog = cohort[4].get("/api/ingestion/imports/datasets").json()
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, invalid["id"], mapping=cohort[2], provenance={"source": "test"},
                            seed=42, profile=cohort[3])
    assert failure.value.code == "invalid_audio"
    assert set(preparations.root.iterdir()) == before
    assert preparations.get(1, cohort[1]["id"], prior["version_id"]) == prior
    assert cohort[4].get("/api/ingestion/imports/datasets").json() == catalog
    assert path.read_bytes() == raw


@pytest.mark.parametrize("cohort", [[(f"class{c}", g) for c in range(4) for g in range(4) if c != g]], indirect=True)
def test_mixed_class_constraints_can_be_impossible_despite_three_groups_per_class(cohort, tmp_path):
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    source_before = list(cohort[0].iter_verified(1, cohort[1]["id"]))
    with pytest.raises(PreparationError) as failure:
        create(preparations, cohort)
    assert failure.value.code == "split_impossible"
    assert failure.value.state == "failed"
    assert not preparations.root.exists()
    assert list(cohort[0].iter_verified(1, cohort[1]["id"])) == source_before
    with pytest.raises(PreparationError) as missing:
        preparations.get(1, cohort[1]["id"], "0" * 64)
    assert missing.value.code == "artifact_unavailable"


def test_fewer_than_three_groups_rejects_but_preserves_previous_version(cohort, tmp_path):
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    mapping = [dict(row, group_id="one") for row in cohort[2]]
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, cohort[1]["id"], mapping=mapping, provenance={"source": "new annotations"},
                            seed=42, profile=cohort[3])
    assert failure.value.code == "split_impossible"
    assert preparations.get(1, cohort[1]["id"], prior["version_id"]) == prior
    assert [p.name for p in preparations.root.iterdir()] == [prior["version_id"]]


@pytest.mark.parametrize("seed", [True, -1, 2**32, 1.2, "42"])
def test_invalid_seed_does_not_publish(cohort, tmp_path, seed):
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, cohort[1]["id"], mapping=cohort[2], provenance={"source": "test"},
                            seed=seed, profile=cohort[3])
    assert failure.value.code == "invalid_seed"
    assert not preparations.root.exists()


def test_existing_version_directory_is_never_overwritten(cohort, tmp_path):
    from training.imported_dataset_preparation import ImportedDatasetPreparation, PreparationError
    first = create(service(cohort, tmp_path), cohort)
    root = tmp_path / "other-prepared"
    root.mkdir(mode=0o700)
    collision = root / first["version_id"]
    collision.mkdir(mode=0o700)
    preparations = ImportedDatasetPreparation(cohort[0], root)
    with pytest.raises(PreparationError) as failure:
        create(preparations, cohort)
    assert failure.value.code == "artifact_unavailable"
    assert collision.is_dir() and list(collision.iterdir()) == []
    assert list(root.iterdir()) == [collision]


@pytest.mark.parametrize("damage", ["modified", "missing", "symlink", "late_iterator"])
def test_source_failures_never_publish_partial_preparation(cohort, tmp_path, monkeypatch, damage):
    from app.services.training_snapshots import SnapshotIntegrityError
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    before = set(preparations.root.iterdir())
    snapshots, snapshot = cohort[:2]
    catalog = cohort[4].get("/api/ingestion/imports/datasets").json()
    if damage == "late_iterator":
        original = snapshots.iter_verified
        def fail_after_last_member(owner, snapshot_id):
            yield from original(owner, snapshot_id)
            raise SnapshotIntegrityError("synthetic late failure")
        monkeypatch.setattr(snapshots, "iter_verified", fail_after_last_member)
    else:
        member_id = cohort[2][0]["member_id"]
        path = snapshots.root / snapshot["id"] / member_id
        path.chmod(0o600)
        if damage == "modified":
            path.write_bytes(b"x" * path.stat().st_size)
        else:
            saved = path.with_suffix(".saved")
            path.rename(saved)
            if damage == "symlink":
                path.symlink_to(saved)
    with pytest.raises(PreparationError) as failure:
        create(preparations, cohort)
    assert failure.value.code == "source_unavailable"
    assert set(preparations.root.iterdir()) == before
    # Descriptor validates T1 manifest, not a second full read of original audio.
    assert preparations.get(1, snapshot["id"], prior["version_id"]) == prior
    assert cohort[4].get("/api/ingestion/imports/datasets").json() == catalog


@pytest.mark.parametrize("owner", [2, -1])
def test_foreign_owner_cannot_create_select_or_read(cohort, tmp_path, owner):
    from fastapi import HTTPException
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    before = set(preparations.root.iterdir())
    for operation in (
        lambda: preparations.create(owner, cohort[1]["id"], mapping=cohort[2],
                                    provenance={"source": "test"}, seed=42, profile=cohort[3]),
        lambda: preparations.get(owner, cohort[1]["id"], prior["version_id"]),
        lambda: preparations.read_split(owner, cohort[1]["id"], prior["version_id"], "train"),
    ):
        with pytest.raises(HTTPException) as failure:
            operation()
        assert failure.value.status_code == 404
    assert set(preparations.root.iterdir()) == before
    assert preparations.get(1, cohort[1]["id"], prior["version_id"]) == prior


@pytest.mark.parametrize("damage", ["manifest", "csv", "csv_symlink", "version_symlink", "traversal", "foreign_snapshot"])
def test_corrupt_or_mismatched_preparation_is_not_consumable(cohort, tmp_path, damage):
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    version, snapshot_id = prior["version_id"], cohort[1]["id"]
    path = preparations.root / version
    if damage in ("manifest", "csv", "csv_symlink"):
        target = path / ("manifest.json" if damage == "manifest" else "train.csv")
        target.chmod(0o600)
        if damage == "csv_symlink":
            saved = path / "saved.csv"
            target.rename(saved)
            target.symlink_to(saved)
        else:
            target.write_bytes(b"corrupt")
    elif damage == "version_symlink":
        saved = preparations.root / "saved"
        path.rename(saved)
        path.symlink_to(saved, target_is_directory=True)
    elif damage == "traversal":
        version = "../" + version
    else:
        snapshot_id = cohort[0].create(1, cohort[5])["id"]
    for operation in (
        lambda: preparations.get(1, snapshot_id, version),
        lambda: preparations.read_split(1, snapshot_id, version, "train"),
    ):
        with pytest.raises(PreparationError) as failure:
            operation()
        assert failure.value.code == ("invalid_identity" if damage == "traversal" else "artifact_unavailable")


def test_root_symlink_is_rejected_and_external_directory_unchanged(cohort, tmp_path):
    from app.services.training_snapshots import SnapshotIntegrityError
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    preparations = ImportedDatasetPreparation(cohort[0], alias / "prepared")
    with pytest.raises(SnapshotIntegrityError):
        create(preparations, cohort)
    assert list(target.iterdir()) == []


def test_changed_inputs_create_new_versions_and_prior_bytes_remain_exact(cohort, tmp_path):
    from copy import deepcopy
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    first = create(preparations, cohort)
    prior_bytes = {p.name: p.read_bytes() for p in (preparations.root / first["version_id"]).iterdir()}
    versions = {first["version_id"]}
    for change in ("seed", "provenance", "mapping", "profile"):
        mapping, profile = deepcopy(cohort[2]), deepcopy(cohort[3])
        provenance, seed = {"source": "synthetic annotations v1"}, 42
        if change == "seed":
            seed = 123
        elif change == "provenance":
            provenance = {"source": "annotations v2"}
        elif change == "mapping":
            mapping = [dict(row, group_id="renamed-" + row["group_id"]) for row in mapping]
        else:
            profile["audio"]["f_min"] = 10.0
        descriptor = preparations.create(1, cohort[1]["id"], mapping=mapping,
                                         provenance=provenance, seed=seed, profile=profile)
        assert descriptor["version_id"] not in versions
        versions.add(descriptor["version_id"])
    assert {p.name: p.read_bytes() for p in (preparations.root / first["version_id"]).iterdir()} == prior_bytes
    assert preparations.get(1, cohort[1]["id"], first["version_id"], expected_profile=cohort[3]) == first
    with pytest.raises(PreparationError) as failure:
        preparations.get(1, cohort[1]["id"], first["version_id"], expected_profile=profile)
    assert failure.value.code == "profile_mismatch"
    assert len(list(preparations.root.iterdir())) == 5


@pytest.mark.parametrize("fault", ["space", "rename", "busy", "open"])
def test_publication_failure_cleans_only_owned_staging(cohort, tmp_path, monkeypatch, fault):
    import fcntl
    import os
    from types import SimpleNamespace
    from training import imported_dataset_preparation as module
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    unrelated = preparations.root / ".staging-unrelated"
    unrelated.mkdir(mode=0o700)
    (unrelated / "preserve").write_bytes(b"unrelated")
    before = set(preparations.root.iterdir())
    profile = dict(cohort[3], window_hop_seconds=0.25)
    root_fd = None
    if fault == "space":
        monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    elif fault == "rename":
        original = module.os.rename
        def fail_publication(src, dst, **kwargs):
            if str(src).startswith(".staging-"):
                raise OSError("synthetic rename failure")
            return original(src, dst, **kwargs)
        monkeypatch.setattr(module.os, "rename", fail_publication)
    elif fault == "open":
        original_open = module.os.open
        def fail_staging_open(path, flags, *args, **kwargs):
            if str(path).startswith(".staging-"):
                raise OSError("synthetic staging open failure")
            return original_open(path, flags, *args, **kwargs)
        monkeypatch.setattr(module.os, "open", fail_staging_open)
    else:
        root_fd = os.open(preparations.root, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises((module.PreparationError, OSError)) as failure:
            preparations.create(1, cohort[1]["id"], mapping=cohort[2], provenance={"source": "test"},
                                seed=42, profile=profile)
        if fault not in ("rename", "open"):
            assert failure.value.code == ("budget_exceeded" if fault == "space" else "publication_busy")
    finally:
        if root_fd is not None:
            os.close(root_fd)
    assert set(preparations.root.iterdir()) == before
    assert (unrelated / "preserve").read_bytes() == b"unrelated"
    assert preparations.get(1, cohort[1]["id"], prior["version_id"]) == prior
    assert len(list(cohort[0].iter_verified(1, cohort[1]["id"]))) == 6


def test_concurrent_absent_root_creators_reopen_safe_winner(cohort, tmp_path, monkeypatch):
    import os
    preparations = service(cohort, tmp_path)
    original_mkdir = os.mkdir
    def concurrent_winner_before_mkdir(path, mode=0o777, *, dir_fd=None):
        if path == "prepared" and dir_fd is not None:
            # Model the filesystem interleaving: another creator wins after
            # our missing-directory open and before our mkdir. The second
            # real syscall raises FileExistsError, with no scheduling barrier.
            original_mkdir(path, mode, dir_fd=dir_fd)
        return original_mkdir(path, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "mkdir", concurrent_winner_before_mkdir)
    ready = create(preparations, cohort)
    assert [p.name for p in preparations.root.iterdir()] == [ready["version_id"]]
    artifact = preparations.root / ready["version_id"]
    before = {p.name: p.read_bytes() for p in artifact.iterdir()}
    assert create(preparations, cohort) == ready
    assert {p.name: p.read_bytes() for p in artifact.iterdir()} == before
    assert preparations.get(1, cohort[1]["id"], ready["version_id"]) == ready


@pytest.mark.parametrize("winner", ["symlink", "nonprivate"])
def test_concurrent_unsafe_root_winner_is_rejected(cohort, tmp_path, monkeypatch, winner):
    import os
    from app.services.training_snapshots import SnapshotIntegrityError
    preparations = service(cohort, tmp_path)
    target = tmp_path / "foreign-root"
    target.mkdir(mode=0o700)
    original_mkdir = os.mkdir
    def adversarial_root_mkdir(path, mode=0o777, *, dir_fd=None):
        if path == "prepared" and dir_fd is not None:
            if winner == "symlink":
                os.symlink(target, path, dir_fd=dir_fd)
            else:
                original_mkdir(path, 0o700, dir_fd=dir_fd)
                preparations.root.chmod(0o755)
            raise FileExistsError("synthetic concurrent unsafe root")
        return original_mkdir(path, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "mkdir", adversarial_root_mkdir)
    source_before = list(cohort[0].iter_verified(1, cohort[1]["id"]))
    with pytest.raises(SnapshotIntegrityError):
        create(preparations, cohort)
    assert list(target.iterdir()) == []
    if winner == "symlink":
        assert preparations.root.is_symlink()
    else:
        assert list(preparations.root.iterdir()) == []
        assert preparations.root.stat().st_mode & 0o777 == 0o755
    assert list(cohort[0].iter_verified(1, cohort[1]["id"])) == source_before


def test_concurrent_identical_creators_reselect_without_overwrite(cohort, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    barrier = Barrier(2)
    def work(_):
        barrier.wait(timeout=5)
        try:
            return create(service(cohort, tmp_path), cohort)
        except PreparationError as error:
            assert error.code == "publication_busy"
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, range(2)))
    ready = [r for r in results if r is not None]
    assert ready and all(r == ready[0] for r in ready)
    assert [p.name for p in preparations.root.iterdir()] == [ready[0]["version_id"]]
    assert create(preparations, cohort) == ready[0]


@pytest.mark.parametrize("cohort", [[(c, g) for c in ("ants", "zebra") for g in range(10)]], indirect=True)
def test_ten_groups_target_eight_one_one_without_quantity_warning(cohort, tmp_path):
    preparations = service(cohort, tmp_path)
    result = create(preparations, cohort)
    assert result["warnings"] == []
    assert [len(preparations.read_split(1, cohort[1]["id"], result["version_id"], s))
            for s in ("train", "val", "test")] == [16, 2, 2]


def test_mapping_order_and_explicit_nyquist_are_canonical(cohort, tmp_path):
    from copy import deepcopy
    preparations = service(cohort, tmp_path)
    first = create(preparations, cohort)
    profile = deepcopy(cohort[3])
    profile["audio"]["f_max"] = None
    reordered = preparations.create(1, cohort[1]["id"], mapping=list(reversed(cohort[2])),
                                    provenance={"source": "synthetic annotations v1"}, seed=42, profile=profile)
    assert reordered == first
    assert preparations.get(1, cohort[1]["id"], first["version_id"], expected_profile=profile) == first


@pytest.mark.parametrize("architecture", ["panns_cnn14", "efficientnet_b0", "convnext_nano", "resnet34d"])
def test_other_existing_mono_architectures_have_explicit_supported_profiles(cohort, tmp_path, architecture):
    from copy import deepcopy
    profile = deepcopy(cohort[3])
    profile["architecture"] = architecture
    profile["audio"]["n_mels"] = 64
    preparations = service(cohort, tmp_path)
    result = preparations.create(1, cohort[1]["id"], mapping=cohort[2], provenance={"source": "test"},
                                 seed=42, profile=profile)
    assert result["profile"] == profile
    assert result["profile"]["windowing"] == "energy_peak_pad"


@pytest.mark.parametrize("field,value", [("class_name", "__unknown__"), ("class_name", " "),
                                         ("class_name", "bad/class"), ("original_path", "ants/file.mp3")])
def test_invalid_snapshot_metadata_is_rejected_without_new_version(cohort, tmp_path, field, value):
    from app.models.dataset_import_metadata import DatasetMember
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    prior = create(preparations, cohort)
    with cohort[0].sessions.begin() as db:
        member = db.query(DatasetMember).first()
        setattr(member, field, value)
    invalid = cohort[0].create(1, cohort[5])
    with pytest.raises(PreparationError) as failure:
        preparations.create(1, invalid["id"], mapping=cohort[2], provenance={"source": "test"},
                            seed=42, profile=cohort[3])
    assert failure.value.code == "invalid_metadata"
    assert [p.name for p in preparations.root.iterdir()] == [prior["version_id"]]
    assert preparations.get(1, cohort[1]["id"], prior["version_id"]) == prior


def test_large_multi_chunk_wav_is_verified_without_transforming_original(cohort, tmp_path):
    import hashlib
    import io
    import wave
    from app.models.dataset_import_metadata import DatasetMember
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\x01\x00\x02\x00" * 300000)
    raw = buffer.getvalue()
    with cohort[0].sessions.begin() as db:
        member = db.query(DatasetMember).first()
        member_id = member.id
        path = cohort[0].source.root / "objects" / member.source_import_id / member.stored_name
        path.write_bytes(raw)
        member.sha256, member.size_bytes = hashlib.sha256(raw).hexdigest(), len(raw)
    snapshot = cohort[0].create(1, cohort[5])
    preparations = service(cohort, tmp_path)
    result = preparations.create(1, snapshot["id"], mapping=cohort[2], provenance={"source": "test"},
                                 seed=42, profile=cohort[3])
    chunks = [chunk for member, chunk in cohort[0].iter_verified(1, snapshot["id"]) if member["member_id"] == member_id]
    assert len(chunks) == 2 and b"".join(chunks) == raw
    assert path.read_bytes() == raw
    assert result["profile"]["audio"]["target_sr"] == 8000
    assert result["profile"]["channels"] == 1
    assert {p.name for p in (preparations.root / result["version_id"]).iterdir()} == {"manifest.json", "train.csv", "val.csv", "test.csv"}


@pytest.mark.parametrize("cohort", [[(c, g) for c in ("ants", "zebra") for g in range(201)]], indirect=True)
def test_search_limit_reports_unknown_feasibility_not_impossibility(cohort, tmp_path):
    from training.imported_dataset_preparation import PreparationError
    preparations = service(cohort, tmp_path)
    with pytest.raises(PreparationError) as failure:
        create(preparations, cohort)
    assert failure.value.code == "split_search_unavailable"
    assert not preparations.root.exists()
    assert cohort[0].get(1, cohort[1]["id"])["file_count"] == 402


def test_exact_reselect_and_mixed_class_groups_are_reproducible(cohort, tmp_path):
    preparations = service(cohort, tmp_path)
    first = create(preparations, cohort)
    assert first["state"] == "ready"
    assert first["class_to_index"] == {"ants": 0, "zebra": 1}
    assert first["warnings"] == [{"code": "low_independent_groups", "class_name": c,
                                   "groups": 3, "recommended": 10} for c in ("ants", "zebra")]
    assert create(preparations, cohort) == first
    reopened = service(cohort, tmp_path)
    assert reopened.get(1, cohort[1]["id"], first["version_id"]) == first
    groups = []
    for split in ("train", "val", "test"):
        rows = reopened.read_split(1, cohort[1]["id"], first["version_id"], split)
        assert {r["class_name"] for r in rows} == {"ants", "zebra"}
        assert len(rows) == 2
        assert all(r["snapshot_id"] == cohort[1]["id"] and r["sha256"] and r["source_import_id"] for r in rows)
        groups.append({r["group_id"] for r in rows})
    assert all(not a & b for i, a in enumerate(groups) for b in groups[i + 1:])
    assert cohort[4].get(f"/api/ingestion/imports/datasets/{cohort[5]}/files").json()["files"]
