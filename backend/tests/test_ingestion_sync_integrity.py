"""Sync integrity through public ingestion interfaces with fake GCS bytes."""
import base64
import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.ingestion import IngestionService
from app.database import Base
from app.services import training


class BlobFixture:
    def __init__(self, content=b"remote", name="datasets/AvesChilenas/Chucao/audio.wav"):
        self.name = name
        self.content = content
        self.size = len(content)
        self.md5_hash = base64.b64encode(hashlib.md5(content).digest()).decode()
        self.crc32c = None
        self.updated = None
        self.downloads = 0
        self.fail = False

    def download_to_filename(self, path, **kwargs):
        self.downloads += 1
        Path(path).write_bytes(self.content if not self.fail else b"partial")
        if self.fail:
            raise OSError("Synthetic interrupted download")


@pytest.fixture
def sync_environment(tmp_path, monkeypatch):
    blobs = []

    class ClientFixture:
        def list_blobs(self, *args, **kwargs):
            return list(blobs)

    monkeypatch.setattr("google.cloud.storage.Client", ClientFixture)
    service = IngestionService(bucket_name="fixture-bucket", local_base_dir=tmp_path / "raw",
                               local_processed_dir=tmp_path / "processed")
    local = tmp_path / "raw" / "AvesChilenas" / "Chucao" / "audio.wav"
    local.parent.mkdir(parents=True)
    return service, blobs, local


def test_same_size_with_different_content_is_downloaded(sync_environment):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"BBBB")
    blobs.append(blob)
    local.write_bytes(b"AAAA")

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["downloaded"] == 1
    assert result["skipped"] == 0
    assert blob.downloads == 1
    assert local.read_bytes() == b"BBBB"


def test_interrupted_download_preserves_the_previous_file(sync_environment):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"replacement")
    blob.fail = True
    blobs.append(blob)
    local.write_bytes(b"previous verified content")

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert result["downloaded"] == 0
    assert local.read_bytes() == b"previous verified content"
    assert {path.name for path in local.parent.iterdir()} == {"audio.wav"}


def test_download_with_wrong_provider_checksum_does_not_replace_local_audio(sync_environment):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"GOOD")
    blob.content = b"FAIL"  # Same size, but not the bytes described by the provider.
    blobs.append(blob)
    local.write_bytes(b"previous content")

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert result["downloaded"] == 0
    assert local.read_bytes() == b"previous content"
    assert {path.name for path in local.parent.iterdir()} == {"audio.wav"}


def test_crc32c_can_confirm_an_object_without_md5(sync_environment):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"123456789")
    blob.md5_hash = None
    # Standard CRC32C check vector: 0xe3069283, encoded as GCS base64 bytes.
    blob.crc32c = "4waSgw=="
    blobs.append(blob)
    local.write_bytes(b"123456789")

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["skipped"] == 1
    assert result["downloaded"] == 0
    assert blob.downloads == 0


def test_nested_object_paths_keep_their_full_relative_hierarchy(sync_environment):
    service, blobs, local = sync_environment
    blobs.extend([
        BlobFixture(b"first", "datasets/AvesChilenas/Chucao/session1/audio.wav"),
        BlobFixture(b"second", "datasets/AvesChilenas/Chucao/session2/audio.wav"),
    ])

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["downloaded"] == 2
    assert (local.parent / "session1" / "audio.wav").read_bytes() == b"first"
    assert (local.parent / "session2" / "audio.wav").read_bytes() == b"second"
    assert [item["filename"] for item in result["files"]] == ["audio.wav", "audio.wav"]


def test_incomplete_download_without_checksum_is_not_published(sync_environment):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"short")
    blob.size = 20
    blob.md5_hash = None
    blobs.append(blob)
    local.write_bytes(b"previous content")

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert result["downloaded"] == 0
    assert local.read_bytes() == b"previous content"


def test_failed_transfer_is_not_registered_as_a_synced_audio(sync_environment, monkeypatch):
    service, blobs, local = sync_environment
    blob = BlobFixture()
    blob.fail = True
    blobs.append(blob)
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: service.local_base_dir / (name or ""))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            result = service.sync_dataset_to_local("AvesChilenas", db=db)
            dataset, = training.training_service.get_available_datasets(db=db)

        assert result["failed"] == 1
        assert result["db_persisted"] is True
        assert dataset["audio_count"] == 0
        assert dataset["size_mb"] == 0
        assert dataset["estado"] == "sincronizacion_parcial"
        assert not local.exists()
    finally:
        engine.dispose()


def test_failed_refresh_keeps_previous_accepted_counts_and_bytes(sync_environment, monkeypatch):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"x" * (1024 * 1024))
    blobs.append(blob)
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: service.local_base_dir / (name or ""))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            initial = service.sync_dataset_to_local("AvesChilenas", db=db)
            assert initial["downloaded"] == 1
            blobs[:] = [BlobFixture(b"y" * (1024 * 1024))]
            blobs[0].fail = True
            result = service.sync_dataset_to_local("AvesChilenas", db=db)
            dataset, = training.training_service.get_available_datasets(db=db)

        assert result["failed"] == 1
        assert dataset["audio_count"] == 1
        assert dataset["size_mb"] == 1.0
        assert dataset["estado"] == "sincronizacion_parcial"
        assert local.read_bytes() == blob.content
    finally:
        engine.dispose()


def test_equal_basenames_in_different_classes_keep_two_audio_records(sync_environment, monkeypatch):
    service, blobs, local = sync_environment
    blobs.extend([
        BlobFixture(b"AAAA"),
        BlobFixture(b"BBBB", "datasets/AvesChilenas/Rayadito/audio.wav"),
    ])
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: service.local_base_dir / (name or ""))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            result = service.sync_dataset_to_local("AvesChilenas", db=db)
            dataset, = training.training_service.get_available_datasets(db=db)

        assert result["downloaded"] == 2
        assert dataset["audio_count"] == 2
        assert set(dataset["classes"]) == {"Chucao", "Rayadito"}
        assert local.read_bytes() == b"AAAA"
        assert (local.parent.parent / "Rayadito" / "audio.wav").read_bytes() == b"BBBB"
    finally:
        engine.dispose()


def test_matching_md5_is_skipped_without_a_download(sync_environment):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"verified")
    blobs.append(blob)
    local.write_bytes(blob.content)

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["skipped"] == 1
    assert blob.downloads == 0


def test_missing_checksums_never_prove_same_size_is_up_to_date(sync_environment):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"BBBB")
    blob.md5_hash = None
    blobs.append(blob)
    local.write_bytes(b"AAAA")

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["downloaded"] == 1
    assert result["skipped"] == 0
    assert local.read_bytes() == b"BBBB"


def test_wrong_crc32c_preserves_existing_content(sync_environment):
    service, blobs, local = sync_environment
    blob = BlobFixture(b"wrong-data")
    blob.md5_hash = None
    blob.crc32c = "4waSgw=="
    blobs.append(blob)
    local.write_bytes(b"previous content")

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert local.read_bytes() == b"previous content"


def test_missing_provider_size_uses_observed_local_bytes(sync_environment):
    service, blobs, _ = sync_environment
    blob = BlobFixture(b"DATA")
    blob.size = None
    blobs.append(blob)

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["downloaded"] == 1
    assert result["files"][0]["size"] == 4


def test_remote_parent_component_cannot_escape_dataset(sync_environment):
    service, blobs, _ = sync_environment
    blob = BlobFixture(b"unsafe", "datasets/AvesChilenas/../escaped.wav")
    blobs.append(blob)

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert result["downloaded"] == 0
    assert blob.downloads == 0
    assert not (service.local_base_dir / "escaped.wav").exists()


def test_dataset_parent_path_is_rejected_before_contacting_cloud(sync_environment):
    service, blobs, _ = sync_environment
    blobs.append(BlobFixture(name="datasets/../outside/Chucao/audio.wav"))

    with pytest.raises(ValueError, match="dataset"):
        service.sync_dataset_to_local("../outside")

    assert blobs[0].downloads == 0
    assert not (service.local_base_dir.parent / "outside").exists()


@pytest.mark.parametrize("name", ["C:escape", "CON", "NUL.wav", "AvesChilenas.", "AvesChilenas ", "bad\x00name"])
def test_windows_ambiguous_dataset_names_are_rejected(sync_environment, name):
    service, _, _ = sync_environment

    with pytest.raises(ValueError, match="dataset"):
        service.sync_dataset_to_local(name)


@pytest.mark.parametrize("relative", ["..\\escaped.wav", "Chucao/..\\..\\escaped.wav", "Chucao/audio.wav:stream", "NUL/audio.wav"])
def test_remote_windows_paths_are_rejected_without_downloading(sync_environment, relative):
    service, blobs, _ = sync_environment
    blob = BlobFixture(name=f"datasets/AvesChilenas/{relative}")
    blobs.append(blob)

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert blob.downloads == 0


@pytest.mark.parametrize("relative", ["Chucao/" + "f" * 252 + ".wav", "Chucao/" + "s" * 200 + "/" + "t" * 200 + "/" + "f" * 96 + ".wav"], ids=["filename", "object-uri"])
def test_remote_names_exceeding_database_limits_are_rejected(sync_environment, relative):
    service, blobs, _ = sync_environment
    blob = BlobFixture(name=f"datasets/AvesChilenas/{relative}")
    blobs.append(blob)

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert blob.downloads == 0
    assert result["files"][0]["error"] == "Invalid object metadata length"


@pytest.mark.parametrize("name", ["datasets/Other/Chucao/audio.wav", "datasets/AvesChilenas/Chucao//audio.wav"])
def test_wrong_prefix_and_empty_components_are_not_downloaded(sync_environment, name):
    service, blobs, _ = sync_environment
    blob = BlobFixture(name=name)
    blobs.append(blob)

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert blob.downloads == 0


def test_local_directory_link_cannot_redirect_download_outside_dataset(sync_environment):
    service, blobs, local = sync_environment
    outside = service.local_base_dir.parent / "outside"
    outside.mkdir()
    local.parent.rmdir()  # Empty synthetic class directory, not user data.
    if os.name == "nt":
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(local.parent), str(outside)],
                       check=True, capture_output=True)
    else:
        local.parent.symlink_to(outside, target_is_directory=True)
    blobs.append(BlobFixture())
    try:
        result = service.sync_dataset_to_local("AvesChilenas")

        assert result["failed"] == 1
        assert blobs[0].downloads == 0
        assert not (outside / "audio.wav").exists()
    finally:
        if os.name == "nt":
            os.rmdir(local.parent)  # Remove only our junction, never its target.
        else:
            local.parent.unlink()


def test_dataset_link_outside_raw_root_is_rejected(sync_environment):
    service, blobs, local = sync_environment
    outside = service.local_base_dir.parent / "outside"
    outside.mkdir()
    dataset_dir = local.parent.parent
    local.parent.rmdir()
    dataset_dir.rmdir()
    if os.name == "nt":
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(dataset_dir), str(outside)],
                       check=True, capture_output=True)
    else:
        dataset_dir.symlink_to(outside, target_is_directory=True)
    blobs.append(BlobFixture())
    try:
        with pytest.raises(ValueError, match="dataset"):
            service.sync_dataset_to_local("AvesChilenas")
        assert blobs[0].downloads == 0
        assert not (outside / "Chucao").exists()
    finally:
        if os.name == "nt":
            os.rmdir(dataset_dir)
        else:
            dataset_dir.unlink()


def test_directory_markers_are_ignored_and_unicode_audio_names_are_preserved(sync_environment):
    service, blobs, _ = sync_environment
    blobs.extend([
        BlobFixture(b"", "datasets/AvesChilenas/"),
        BlobFixture(b"", "datasets/AvesChilenas/Churrín del sur/"),
        BlobFixture(b"audio", "datasets/AvesChilenas/Churrín del sur/grabación.wav"),
    ])

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["downloaded"] == 1
    assert result["failed"] == 0
    assert (service.local_base_dir / "AvesChilenas" / "Churrín del sur" / "grabación.wav").read_bytes() == b"audio"


def test_remote_class_exceeding_database_column_is_rejected_before_download(sync_environment):
    service, blobs, _ = sync_environment
    blob = BlobFixture(name=f"datasets/AvesChilenas/{'c' * 101}/audio.wav")
    blobs.append(blob)

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert blob.downloads == 0


def test_maximum_filename_downloads_without_inflating_temporary_name(sync_environment):
    service, blobs, local = sync_environment
    filename = "f" * 251 + ".wav"  # 255 characters, valid NTFS/SQL component.
    blob = BlobFixture(b"verified bytes", f"datasets/AvesChilenas/Chucao/{filename}")
    blobs.append(blob)

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 0
    assert result["downloaded"] == 1
    destination = local.parent / filename
    if os.name == "nt":
        destination = Path("\\\\?\\" + str(destination))
    assert destination.read_bytes() == b"verified bytes"
    assert {path.name for path in local.parent.iterdir()} == {filename}


def test_long_nested_destination_can_be_downloaded_and_skipped_on_retry(sync_environment):
    service, blobs, local = sync_environment
    folder = "session-" + "s" * 92
    blob = BlobFixture(b"nested verified bytes", f"datasets/AvesChilenas/Chucao/{folder}/audio.wav")
    blobs.append(blob)

    first = service.sync_dataset_to_local("AvesChilenas")
    second = service.sync_dataset_to_local("AvesChilenas")

    assert first["downloaded"] == 1
    assert second["skipped"] == 1
    assert blob.downloads == 1
    assert first["local_dir"] == str(local.parent.parent)
    destination = local.parent / folder / "audio.wav"
    if os.name == "nt":
        destination = Path("\\\\?\\" + str(destination))
    assert destination.read_bytes() == b"nested verified bytes"


def test_long_configured_root_still_reuses_existing_slug_dataset(sync_environment):
    original, blobs, _ = sync_environment
    raw_root = original.local_base_dir / ("r" * 100) / ("s" * 100)
    existing = raw_root / "aves_chilenas"
    filesystem_existing = Path("\\\\?\\" + str(existing)) if os.name == "nt" else existing
    filesystem_existing.mkdir(parents=True)
    service = IngestionService(bucket_name="fixture-bucket", local_base_dir=raw_root,
                               local_processed_dir=original.local_processed_dir)
    blobs.append(BlobFixture(b"long root bytes", "datasets/Aves Chilenas/Chucao/audio.wav"))

    result = service.sync_dataset_to_local("Aves Chilenas")

    assert result["local_dir"] == str(existing)
    assert result["downloaded"] == 1
    assert (filesystem_existing / "Chucao" / "audio.wav").read_bytes() == b"long root bytes"


def test_local_parent_conflict_fails_one_transfer_without_aborting_batch(sync_environment):
    service, blobs, local = sync_environment
    blocked = local.parent / "blocked"
    blocked.write_bytes(b"previous local file")
    blobs.extend([
        BlobFixture(b"rejected", "datasets/AvesChilenas/Chucao/blocked/audio.wav"),
        BlobFixture(b"accepted"),
    ])

    result = service.sync_dataset_to_local("AvesChilenas")

    assert result["failed"] == 1
    assert result["downloaded"] == 1
    assert result["files"][0]["error"] == "No se pudo sincronizar el archivo."
    assert blobs[0].downloads == 0
    assert blocked.read_bytes() == b"previous local file"
    assert local.read_bytes() == b"accepted"


@pytest.mark.skipif(os.name != "nt", reason="Windows file handles block temporary deletion")
def test_locked_temporary_reports_cleanup_pending_without_aborting_batch(sync_environment):
    service, blobs, local = sync_environment

    class LockedInterruptedBlob(BlobFixture):
        handle = None
        temporary = None

        def download_to_filename(self, path, **kwargs):
            self.temporary = Path(path)
            self.temporary.write_bytes(b"partial")
            self.handle = self.temporary.open("rb")
            raise OSError("Synthetic failure /private/provider")

    interrupted = LockedInterruptedBlob(b"replacement")
    local.write_bytes(b"previous")
    blobs.extend([interrupted, BlobFixture(b"accepted", "datasets/AvesChilenas/Chucao/other.wav")])
    try:
        result = service.sync_dataset_to_local("AvesChilenas")

        assert result["failed"] == 1
        assert result["downloaded"] == 1
        assert result["files"][0]["cleanup_pending"] is True
        assert result["files"][0]["error"] == "No se pudo sincronizar el archivo."
        assert local.read_bytes() == b"previous"
        assert (local.parent / "other.wav").read_bytes() == b"accepted"
    finally:
        if interrupted.handle is not None:
            interrupted.handle.close()
        if interrupted.temporary is not None:
            interrupted.temporary.unlink(missing_ok=True)
