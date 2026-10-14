"""Upload identity and counters through public interfaces, without cloud access."""
import io
import wave

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.ingestion import IngestionService
from app.services import training


def synthetic_wav(frames=8000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * frames)
    return output.getvalue()


@pytest.fixture
def upload_environment(tmp_path, monkeypatch):
    objects = {}

    class Blob:
        def __init__(self, name):
            self.name = name

        def upload_from_string(self, content, **kwargs):
            objects[self.name] = content

    class Bucket:
        def blob(self, name):
            return Blob(name)

    class Client:
        def bucket(self, name):
            return Bucket()

    monkeypatch.setattr("google.cloud.storage.Client", Client)
    service = IngestionService(bucket_name="test-bucket", local_base_dir=tmp_path / "raw",
                               local_processed_dir=tmp_path / "processed")
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: service.local_base_dir / (name or ""))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with sessionmaker(bind=engine)() as db:
            yield service, db, objects
    finally:
        engine.dispose()


def test_same_filename_in_two_classes_remains_two_registered_audios(upload_environment):
    service, db, objects = upload_environment
    content = synthetic_wav()
    for label in ("Chucao", "Rayadito"):
        result = service.upload_files_to_gcs([("audio.wav", content)], "AvesChilenas", label, db=db)
        assert result["db_persisted"] is True

    dataset, = training.training_service.get_available_datasets(db=db)

    assert dataset["audio_count"] == 2
    assert set(dataset["classes"]) == {"Chucao", "Rayadito"}
    assert set(objects) == {"datasets/AvesChilenas/Chucao/audio.wav", "datasets/AvesChilenas/Rayadito/audio.wav"}


def test_replacing_an_object_updates_bytes_without_incrementing_audio_count(upload_environment):
    service, db, objects = upload_environment
    original = synthetic_wav(frames=524288)  # 1 MiB of PCM plus WAV header.
    replacement = synthetic_wav(frames=1048576)  # 2 MiB of PCM plus header.
    for content in (original, replacement):
        result = service.upload_files_to_gcs([("audio.wav", content)], "AvesChilenas", "Chucao", db=db)
        assert result["db_persisted"] is True

    dataset, = training.training_service.get_available_datasets(db=db)

    assert dataset["audio_count"] == 1
    assert dataset["size_mb"] == 2.0
    assert objects["datasets/AvesChilenas/Chucao/audio.wav"] == replacement


def test_duplicate_object_in_one_batch_counts_final_object_once(upload_environment):
    service, db, objects = upload_environment
    original = synthetic_wav(frames=524288)
    replacement = synthetic_wav(frames=1048576)

    result = service.upload_files_to_gcs(
        [("audio.wav", original), ("audio.wav", replacement)], "AvesChilenas", "Chucao", db=db
    )
    dataset, = training.training_service.get_available_datasets(db=db)

    assert result["uploaded"] == 2  # Two transfers, but only one final object.
    assert result["db_persisted"] is True
    assert dataset["audio_count"] == 1
    assert dataset["size_mb"] == 2.0
    assert len(objects) == 1
