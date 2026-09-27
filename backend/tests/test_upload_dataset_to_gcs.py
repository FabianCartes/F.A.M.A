import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from training.upload_dataset_to_gcs import scan_dataset_files, upload_dataset_to_gcs


@pytest.fixture
def temp_dataset_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        # Crear estructura con dos clases
        c1 = base / "clase_a"
        c2 = base / "nested_group" / "clase_b"
        c1.mkdir(parents=True)
        c2.mkdir(parents=True)

        (c1 / "audio1.wav").write_bytes(b"RIFFdummydata1")
        (c1 / "audio2.wav").write_bytes(b"RIFFdummydata2")
        (c2 / "audio3.wav").write_bytes(b"RIFFdummydata3")
        (base / "ignored.txt").write_bytes(b"not audio")

        yield base


def test_scan_dataset_files(temp_dataset_dir):
    items = scan_dataset_files(temp_dataset_dir, dataset_name="TestDataset")
    assert len(items) == 3

    classes = {item["class_name"] for item in items}
    assert classes == {"clase_a", "clase_b"}

    destinations = [item["destination_blob"] for item in items]
    assert "datasets/TestDataset/clase_a/audio1.wav" in destinations
    assert "datasets/TestDataset/clase_a/audio2.wav" in destinations
    assert "datasets/TestDataset/clase_b/audio3.wav" in destinations


def test_upload_dataset_dry_run(temp_dataset_dir):
    stats = upload_dataset_to_gcs(
        dataset_name="TestDataset",
        source_dir=temp_dataset_dir,
        bucket_name="test-bucket",
        dry_run=True,
    )
    assert stats["total_scanned"] == 3
    assert stats["uploaded"] == 0
    assert stats["dry_run"] is True


def test_upload_dataset_with_mock_client(temp_dataset_dir):
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()

    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    with patch("training.upload_dataset_to_gcs.get_storage_client", return_value=mock_client):
        stats = upload_dataset_to_gcs(
            dataset_name="TestDataset",
            source_dir=temp_dataset_dir,
            bucket_name="test-bucket",
            dry_run=False,
            max_workers=2,
        )

        assert stats["total_scanned"] == 3
        assert stats["uploaded"] == 3
        assert stats["failed"] == 0
        assert mock_bucket.blob.call_count == 3
        assert mock_blob.upload_from_filename.call_count == 3
