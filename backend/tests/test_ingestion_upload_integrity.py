"""Upload identity and counters through public interfaces, without cloud access."""
import io
import wave
import base64
import hashlib
from google.api_core.exceptions import NotFound, PreconditionFailed
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.services.ingestion import IngestionService
from app.services import training


def synthetic_wav(frames=8000, sample_rate=8000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\0\0" * frames)
    return output.getvalue()


@pytest.fixture
def upload_environment(tmp_path, monkeypatch):
    objects = {}
    generations = {}

    class Blob:
        def __init__(self, name):
            self.name = name

        @property
        def generation(self):
            return generations.get(self.name, 1 if self.name in objects else None)

        @property
        def md5_hash(self):
            return base64.b64encode(hashlib.md5(objects[self.name], usedforsecurity=False).digest()).decode()

        def reload(self):
            if self.name not in objects:
                raise NotFound("Synthetic missing object")

        def upload_from_string(self, content, **kwargs):
            if self.name in Client.failures:
                raise OSError("Synthetic provider failure /private/credentials.json")
            expected = kwargs.get("if_generation_match")
            if expected is not None and expected != (self.generation or 0):
                raise PreconditionFailed("Synthetic generation conflict")
            generations[self.name] = (self.generation or 0) + 1
            objects[self.name] = content

    class Bucket:
        def blob(self, name):
            return Blob(name)

    class Client:
        failures = set()

        def bucket(self, name):
            return Bucket()

        def list_blobs(self, bucket, prefix):
            return [SimpleNamespace(name=name, size=len(content), updated=None)
                    for name, content in objects.items() if name.startswith(prefix)]

    monkeypatch.setattr("google.cloud.storage.Client", Client)
    service = IngestionService(bucket_name="test-bucket", local_base_dir=tmp_path / "raw",
                               local_processed_dir=tmp_path / "processed")
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: service.local_base_dir / (name or ""))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def test_conflicting_object_preserves_bytes_and_audio_count(upload_environment):
    service, db, objects = upload_environment
    original = synthetic_wav(frames=524288)  # 1 MiB of PCM plus WAV header.
    replacement = synthetic_wav(frames=1048576)  # 2 MiB of PCM plus header.
    for content in (original, replacement):
        result = service.upload_files_to_gcs([("audio.wav", content)], "AvesChilenas", "Chucao", db=db)
        assert result["db_persisted"] is (content == original)

    dataset, = training.training_service.get_available_datasets(db=db)

    assert dataset["audio_count"] == 1
    assert dataset["size_mb"] == 1.0
    assert objects["datasets/AvesChilenas/Chucao/audio.wav"] == original


def test_duplicate_object_in_one_batch_counts_final_object_once(upload_environment):
    service, db, objects = upload_environment
    original = synthetic_wav(frames=524288)
    replacement = synthetic_wav(frames=1048576)

    result = service.upload_files_to_gcs(
        [("audio.wav", original), ("audio.wav", replacement)], "AvesChilenas", "Chucao", db=db
    )
    dataset, = training.training_service.get_available_datasets(db=db)

    assert result["uploaded"] == 1
    assert result["failed"] == 1
    assert result["db_persisted"] is True
    assert dataset["audio_count"] == 1
    assert dataset["size_mb"] == 1.0
    assert len(objects) == 1


@pytest.mark.parametrize("name", ["../outside", "Aves/Chilenas", "Aves\\Chilenas", "NUL", "C:escape", "", "AvesChilenas "])
def test_invalid_upload_dataset_is_rejected_without_transferring(upload_environment, name):
    service, db, objects = upload_environment

    with pytest.raises(ValueError, match="dataset"):
        service.upload_files_to_gcs([("audio.wav", synthetic_wav())], name, db=db)

    assert objects == {}
    assert training.training_service.get_available_datasets(db=db) == []


def test_combined_object_uri_cannot_exceed_database_route_limit(upload_environment):
    original, db, objects = upload_environment
    service = IngestionService(bucket_name="b" * 63, local_base_dir=original.local_base_dir,
                               local_processed_dir=original.local_processed_dir)

    with pytest.raises(ValueError, match="object"):
        service.upload_files_to_gcs([("f" * 251 + ".wav", synthetic_wav())],
                                    "d" * 100, "c" * 100, db=db)

    assert objects == {}
    assert training.training_service.get_available_datasets(db=db) == []


@pytest.mark.parametrize("label", ["../Chucao", "Chucao/Rayadito", "Chucao\\Rayadito", "NUL", "", "Chucao."])
def test_invalid_class_is_rejected_without_transferring(upload_environment, label):
    service, db, objects = upload_environment

    with pytest.raises(ValueError, match="class"):
        service.upload_files_to_gcs([("audio.wav", synthetic_wav())], "AvesChilenas", label, db=db)

    assert objects == {}
    assert training.training_service.get_available_datasets(db=db) == []


@pytest.mark.parametrize("filename", ["../audio.wav", "folder/audio.wav", "folder\\audio.wav", "C:audio.wav", "audio.wav:stream", "NUL.wav", "", "audio.wav."])
def test_invalid_filename_rejects_entire_batch_before_first_transfer(upload_environment, filename):
    service, db, objects = upload_environment
    content = synthetic_wav()

    with pytest.raises(ValueError, match="filename"):
        service.upload_files_to_gcs(
            [("valid.wav", content), (filename, content)], "AvesChilenas", "Chucao", db=db
        )

    assert objects == {}
    assert training.training_service.get_available_datasets(db=db) == []


@pytest.mark.parametrize("field", ["dataset", "class", "filename"])
def test_names_exceeding_database_columns_are_rejected_before_upload(upload_environment, field):
    service, db, objects = upload_environment
    dataset = "d" * 101 if field == "dataset" else "AvesChilenas"
    label = "c" * 101 if field == "class" else "Chucao"
    filename = "f" * 252 + ".wav" if field == "filename" else "audio.wav"

    with pytest.raises(ValueError, match=field):
        service.upload_files_to_gcs([("valid.wav", synthetic_wav()), (filename, synthetic_wav())],
                                    dataset, label, db=db)

    assert objects == {}


def test_names_at_database_column_limits_can_be_uploaded(upload_environment):
    service, db, objects = upload_environment

    result = service.upload_files_to_gcs([("f" * 251 + ".wav", synthetic_wav())],
                                         "d" * 100, "c" * 100, db=db)

    assert result["uploaded"] == 1
    assert result["db_persisted"] is True
    assert len(objects) == 1


def test_object_uri_at_500_characters_can_be_uploaded(upload_environment):
    original, db, objects = upload_environment
    service = IngestionService(bucket_name="b" * 63, local_base_dir=original.local_base_dir,
                               local_processed_dir=original.local_processed_dir)

    result = service.upload_files_to_gcs([("f" * 216 + ".wav", synthetic_wav())],
                                         "d" * 100, "c" * 100, db=db)

    assert result["uploaded"] == 1
    assert result["db_persisted"] is True
    assert len(objects) == 1


def test_partial_upload_continues_and_registers_only_accepted_files(upload_environment, monkeypatch):
    service, db, objects = upload_environment
    monkeypatch.setattr("google.cloud.storage.Client.failures", {"datasets/AvesChilenas/Chucao/failed.wav"})
    content = synthetic_wav(frames=524288)

    result = service.upload_files_to_gcs(
        [("first.wav", content), ("failed.wav", content), ("last.wav", content)],
        "AvesChilenas", "Chucao", db=db
    )

    assert result["uploaded"] == 2
    assert result["failed"] == 1
    assert result["files"] == ["first.wav", "last.wav"]
    assert result["errors"] == [{"filename": "failed.wav", "error": "No se pudo subir el archivo."}]
    assert result["db_persisted"] is True
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["audio_count"] == 2
    assert dataset["size_mb"] == 2.0
    assert dataset["estado"] == "subida_parcial"
    assert set(objects) == {"datasets/AvesChilenas/Chucao/first.wav", "datasets/AvesChilenas/Chucao/last.wav"}


def test_total_upload_failure_registers_no_new_audio(upload_environment, monkeypatch):
    service, db, objects = upload_environment
    monkeypatch.setattr("google.cloud.storage.Client.failures", {"datasets/AvesChilenas/Chucao/audio.wav"})

    result = service.upload_files_to_gcs([("audio.wav", synthetic_wav())], "AvesChilenas", "Chucao", db=db)

    assert result["status"] == "failed"
    assert result["uploaded"] == 0
    assert result["failed"] == 1
    assert result["files"] == []
    assert objects == {}
    assert result["db_persisted"] is False
    assert training.training_service.get_available_datasets(db=db) == []


def test_failed_conflicting_refresh_and_retry_preserve_previous_audio(upload_environment, monkeypatch):
    service, db, objects = upload_environment
    original = synthetic_wav(frames=524288)
    replacement = synthetic_wav(frames=1048576)
    first = service.upload_files_to_gcs([("audio.wav", original)], "AvesChilenas", "Chucao", db=db)
    assert first["status"] == "completed"
    monkeypatch.setattr("google.cloud.storage.Client.failures", {"datasets/AvesChilenas/Chucao/audio.wav"})

    failed = service.upload_files_to_gcs([("audio.wav", replacement)], "AvesChilenas", "Chucao", db=db)

    assert failed["status"] == "failed"
    assert failed["db_persisted"] is False
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["audio_count"] == 1
    assert dataset["size_mb"] == 1.0
    assert dataset["estado"] == "subido"
    assert objects["datasets/AvesChilenas/Chucao/audio.wav"] == original

    monkeypatch.setattr("google.cloud.storage.Client.failures", set())
    retried = service.upload_files_to_gcs([("audio.wav", replacement)], "AvesChilenas", "Chucao", db=db)

    assert retried["status"] == "failed"
    assert retried["failed"] == 1
    assert retried["errors"][0]["code"] == "already_exists"
    dataset, = training.training_service.get_available_datasets(db=db)
    assert dataset["audio_count"] == 1
    assert dataset["size_mb"] == 1.0
    assert dataset["estado"] == "subido"


def test_upload_without_database_reports_only_transfer_completion(upload_environment):
    service, _, _ = upload_environment

    result = service.upload_files_to_gcs([("audio.wav", synthetic_wav())], "AvesChilenas", "Chucao")

    assert result["status"] == "completed"
    assert result["db_persisted"] is False
    assert result["db_error"] is None
    assert result["failed"] == 0
