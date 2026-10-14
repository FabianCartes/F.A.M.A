"""Sync integrity through public ingestion interfaces with fake GCS bytes."""
import base64
import hashlib
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
