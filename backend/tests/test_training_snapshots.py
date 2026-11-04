"""Snapshot behavior through the owner/ID service seam."""
import pytest

from tests.test_dataset_import_api import imports, prepare, confirm
from tests.test_dataset_zip_validation import wav_bytes


@pytest.fixture
def frozen(imports, tmp_path):
    from app.services.training_snapshots import TrainingSnapshots
    from app.database import Base
    client, source, _, sessions = imports
    Base.metadata.create_all(sessions.kw["bind"])
    job = prepare(client, tmp_path)
    dataset = confirm(client, job).json()["dataset_id"]
    snapshots = TrainingSnapshots(sessions, source, tmp_path / "snapshots")
    return snapshots, dataset, job


@pytest.mark.parametrize("damage", ["hash", "size", "missing", "symlink", "manifest"])
def test_corrupt_snapshot_rejects_before_delivering_bytes(frozen, damage):
    from app.services.training_snapshots import SnapshotIntegrityError
    snapshots, dataset, _ = frozen
    result = snapshots.create(1, dataset)
    payload = next(p for p in (snapshots.root / result["id"]).iterdir() if p.name != "manifest.jsonl")
    payload.chmod(0o600)
    if damage == "missing":
        payload.rename(payload.with_suffix(".missing"))
    elif damage == "symlink":
        saved = payload.with_suffix(".saved")
        payload.rename(saved)
        payload.symlink_to(saved)
    elif damage == "manifest":
        manifest = payload.parent / "manifest.jsonl"
        manifest.chmod(0o600)
        manifest.write_bytes(b"{}\n")
    elif damage == "size":
        payload.write_bytes(b"truncated")
    else:
        payload.write_bytes(b"x" * payload.stat().st_size)
    with pytest.raises((SnapshotIntegrityError, OSError)):
        next(snapshots.iter_verified(1, result["id"]))


@pytest.mark.parametrize("owner", [2, -1])
def test_owner_mismatch_does_not_disclose_or_publish(frozen, imports, owner):
    from fastapi import HTTPException
    snapshots, dataset, _ = frozen
    result = snapshots.create(1, dataset)
    before = snapshots.get(1, result["id"])
    client = imports[0]
    catalog_before = client.get("/api/ingestion/imports/datasets").json()
    files_before = client.get(f"/api/ingestion/imports/datasets/{dataset}/files").json()
    for operation in (lambda: snapshots.create(owner, dataset), lambda: snapshots.get(owner, result["id"]), lambda: list(snapshots.iter_verified(owner, result["id"]))):
        with pytest.raises(HTTPException) as failure:
            operation()
        assert failure.value.status_code == 404
    assert snapshots.get(1, result["id"]) == before
    assert client.get("/api/ingestion/imports/datasets").json() == catalog_before
    assert client.get(f"/api/ingestion/imports/datasets/{dataset}/files").json() == files_before


@pytest.mark.parametrize("damage", ["hash", "size", "missing", "symlink", "space", "manifest_space", "publication"])
def test_failed_creation_has_no_consumable_snapshot(frozen, monkeypatch, damage):
    from fastapi import HTTPException
    from types import SimpleNamespace
    from app.services import training_snapshots as module
    snapshots, dataset, _ = frozen
    fixed = "a" * 32
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex=fixed))
    source_file = next(p for p in (snapshots.source.root / "objects").rglob("*") if p.is_file())
    original = source_file.read_bytes()
    if damage == "hash":
        source_file.write_bytes(b"x" * len(original))
    elif damage == "size":
        source_file.write_bytes(original[:-1])
    elif damage == "missing":
        source_file.rename(source_file.with_suffix(".missing"))
    elif damage == "symlink":
        saved = source_file.with_suffix(".saved")
        source_file.rename(saved)
        source_file.symlink_to(saved)
    elif damage in ("space", "manifest_space"):
        free = 0 if damage == "space" else len(original) + snapshots.reserve_bytes
        monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=free))
    else:
        def fail_rename(*args, **kwargs):
            raise OSError("synthetic publication failure")
        monkeypatch.setattr(module.os, "rename", fail_rename)
    with pytest.raises((module.SnapshotIntegrityError, OSError)):
        snapshots.create(1, dataset)
    with pytest.raises(HTTPException) as failure:
        snapshots.get(1, fixed)
    assert failure.value.status_code == 404
    assert not (snapshots.root / (".staging-" + fixed)).exists()
    if damage in ("space", "publication"):
        assert source_file.read_bytes() == original


def test_failure_after_rename_is_not_visible_or_cleaned_as_staging(frozen, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.services import training_snapshots as module
    snapshots, dataset, _ = frozen
    snapshots.root.mkdir(mode=0o700)
    unrelated = snapshots.root / "unrelated"
    unrelated.write_bytes(b"preserve")
    fixed = "c" * 32
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex=fixed))
    original_fsync = module.os.fsync
    root_inode = snapshots.root.stat().st_ino
    def fail_root_sync(fd):
        if module.os.fstat(fd).st_ino == root_inode:
            raise OSError("synthetic durability failure after rename")
        return original_fsync(fd)
    monkeypatch.setattr(module.os, "fsync", fail_root_sync)
    with pytest.raises(OSError):
        snapshots.create(1, dataset)
    with pytest.raises(HTTPException) as failure:
        snapshots.get(1, fixed)
    assert failure.value.status_code == 404
    assert (snapshots.root / fixed).is_dir()
    assert unrelated.read_bytes() == b"preserve"


def test_symlinked_snapshot_ancestor_is_rejected_before_writes(frozen, tmp_path):
    from app.services.training_snapshots import TrainingSnapshots, SnapshotIntegrityError
    snapshots, dataset, _ = frozen
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    unsafe = TrainingSnapshots(snapshots.sessions, snapshots.source, alias / "snapshots")
    with pytest.raises(SnapshotIntegrityError):
        unsafe.create(1, dataset)
    assert list(actual.iterdir()) == []


def test_append_after_capture_preserves_exact_cohort(frozen, imports, tmp_path, monkeypatch):
    from app.services import training_snapshots as module
    snapshots, dataset, _ = frozen
    client, _, _, _ = imports
    original_usage = module.shutil.disk_usage
    appended = []
    def append_during_copy(path):
        monkeypatch.setattr(module.shutil, "disk_usage", original_usage)
        job = prepare(client, tmp_path, key="concurrent", target_id=dataset, sample=2)
        result = confirm(client, job).json()
        assert result["status"] == "imported"
        appended.append(job["id"])
        return original_usage(path)
    monkeypatch.setattr(module.shutil, "disk_usage", append_during_copy)
    snapshot = snapshots.create(1, dataset)
    assert appended
    assert snapshot["file_count"] == 1
    assert snapshot["dataset_revision"] == 1
    assert [data for _, data in snapshots.iter_verified(1, snapshot["id"])] == [wav_bytes(1)]
    monkeypatch.setattr(module.shutil, "disk_usage", original_usage)
    later = snapshots.create(1, dataset)
    assert later["file_count"] == 2
    assert later["dataset_revision"] == 2


def test_private_copy_is_independent_of_catalog_and_original_bytes(frozen):
    from app.models.dataset_import_metadata import DatasetMember
    snapshots, dataset, _ = frozen
    result = snapshots.create(1, dataset)
    source_file = next(p for p in (snapshots.source.root / "objects").rglob("*") if p.is_file())
    source_file.write_bytes(b"changed original")
    with snapshots.sessions.begin() as db:
        # Synthetic loss/change of mutable catalog is not loss of history.
        member = db.query(DatasetMember).filter_by(dataset_id=dataset).one()
        member.class_name = "changed"
    assert [(entry["class_name"], data) for entry, data in snapshots.iter_verified(1, result["id"])] == [("birds", wav_bytes(1))]


@pytest.mark.parametrize("field,value", [("stored_name", "../outside.wav"), ("source_import_id", "../outside"), ("original_path", "../outside.wav"), ("relative_path", "/outside.wav"), ("id", "../outside")])
def test_unconfined_catalog_references_are_not_published(frozen, field, value, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.models.dataset_import_metadata import DatasetMember
    from app.services import training_snapshots as module
    snapshots, dataset, _ = frozen
    with snapshots.sessions.begin() as db:
        member = db.query(DatasetMember).filter_by(dataset_id=dataset).one()
        setattr(member, field, value)
    fixed = "b" * 32
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex=fixed))
    with pytest.raises(module.SnapshotIntegrityError):
        snapshots.create(1, dataset)
    with pytest.raises(HTTPException) as failure:
        snapshots.get(1, fixed)
    assert failure.value.status_code == 404


def test_verified_iteration_spills_and_bounds_chunks(imports, tmp_path):
    import io
    import wave
    from app.database import Base
    from app.services.training_snapshots import TrainingSnapshots
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\x01\x00" * (1024 * 1024))
    expected = buffer.getvalue()
    client, source, _, sessions = imports
    Base.metadata.create_all(sessions.kw["bind"])
    job = prepare(client, tmp_path, entries=[("birds/large.wav", expected)])
    dataset = confirm(client, job).json()["dataset_id"]
    snapshots = TrainingSnapshots(sessions, source, tmp_path / "snapshots")
    result = snapshots.create(1, dataset)
    chunks = [chunk for _, chunk in snapshots.iter_verified(1, result["id"])]
    assert len(chunks) == 3
    assert max(map(len, chunks)) <= 1024 * 1024
    assert b"".join(chunks) == expected


def test_membership_crosses_batch_boundary(frozen):
    import hashlib
    import uuid
    from app.models.dataset_import_metadata import DatasetMember
    snapshots, dataset, _ = frozen
    with snapshots.sessions.begin() as db:
        source = db.query(DatasetMember).filter_by(dataset_id=dataset).one()
        template = {c.name: getattr(source, c.name) for c in DatasetMember.__table__.columns}
        for number in range(2, 67):
            data = wav_bytes(number)
            values = dict(template, id=uuid.uuid4().hex, sha256=hashlib.sha256(data).hexdigest(),
                          stored_name=f"{number}.wav", relative_path=f"birds/{number}.wav")
            (snapshots.source.root / "objects" / source.source_import_id / values["stored_name"]).write_bytes(data)
            db.add(DatasetMember(**values))
    snapshot = snapshots.create(1, dataset)
    assert snapshot["file_count"] == 66
    assert {data for _, data in snapshots.iter_verified(1, snapshot["id"])} == {wav_bytes(n) for n in range(1, 67)}


def test_verified_labels_come_from_canonical_manifest(frozen):
    from sqlalchemy import update
    from app.models.training_snapshot import SnapshotMember
    snapshots, dataset, _ = frozen
    result = snapshots.create(1, dataset)
    # Simulate drift of the auxiliary capture rows. They are not the artifact.
    with snapshots.sessions.begin() as db:
        db.execute(update(SnapshotMember).values(class_name="wrong"))
    assert {entry["class_name"] for entry, _ in snapshots.iter_verified(1, result["id"])} == {"birds"}


def test_complete_cohort_survives_reopen(imports, tmp_path):
    from app.services.training_snapshots import TrainingSnapshots
    client, source, _, sessions = imports
    from app.database import Base
    Base.metadata.create_all(sessions.kw["bind"])
    first = prepare(client, tmp_path)
    dataset = confirm(client, first).json()["dataset_id"]
    second = prepare(client, tmp_path, key="second", target_id=dataset,
                     entries=[("ants/b.wav", wav_bytes(2))])
    confirm(client, second)
    snapshots = TrainingSnapshots(sessions, source, tmp_path / "snapshots")
    result = snapshots.create(1, dataset)
    assert result["file_count"] == 2
    assert result["classes"] == ["ants", "birds"]
    assert result["dataset_revision"] == 2
    assert {entry["source_import_id"] for entry, data in snapshots.iter_verified(1, result["id"])} == {first["id"], second["id"]}
    assert {data for entry, data in snapshots.iter_verified(1, result["id"])} == {wav_bytes(1), wav_bytes(2)}
    reopened = TrainingSnapshots(sessions, source, tmp_path / "snapshots")
    assert reopened.get(1, result["id"]) == result
