import csv
import io
import wave
import multiprocessing
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.prediction import Prediccion
from app.models.feedback import Retroalimentacion
from app.services.feedback import FeedbackService
from app.services.feedback_sync import FeedbackSyncQueue
from app.services import storage


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b"\x01\x00\xff\xff" * 100)
    objects = {"raw_audios/0123456789abcdef0123456789abcdef.wav": buffer.getvalue()}

    class Blob:
        def __init__(self, key):
            self.key = key
        def download_as_bytes(self):
            return objects[self.key]
        def upload_from_string(self, data, **kwargs):
            objects[self.key] = data

    class Client:
        def list_blobs(self, bucket_name, prefix):
            return [SimpleNamespace(name="datasets/AvesChilenas/Chucao/seed.wav")]
        def bucket(self, name):
            return self
        def blob(self, key):
            return Blob(key)

    monkeypatch.setattr(storage.storage, "Client", Client)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = FeedbackService(raw_data_dir=tmp_path / "raw")
        pred = Prediccion(ruta_audio_prueba=next(iter(objects)), etiqueta_predicha="Chucao", confianza=.9,
                          dataset_name="AvesChilenas")
        db.add(pred)
        db.commit()
        fb = service.record_feedback(db, pred.id_prediccion, True)
        dataset = service.raw_data_dir / "AvesChilenas"
        (dataset / "Chucao").mkdir(parents=True)
        (dataset / "metadata.csv").write_text("nombre_archivo,clase,file_path,file_stage\n")
        yield service, db, pred, fb, objects


def _concurrent_approval_worker(raw_dir, source, feedback_id, snapshot, uploaded,
                                release_read, attempt_done, retry, results):
    """Run a public approval in a separate process with isolated DB/cloud adapters."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    original_reader = csv.reader
    paused = False

    def controlled_reader(stream, *args, **kwargs):
        reader = original_reader(stream, *args, **kwargs)

        class Reader:
            @property
            def line_num(self):
                return reader.line_num

            def __iter__(self):
                return self

            def __next__(self):
                nonlocal paused
                try:
                    return next(reader)
                except StopIteration:
                    if not paused:
                        paused = True
                        snapshot.set()
                        if feedback_id == 1:
                            assert release_read.wait(10), "Parent did not release the first snapshot"
                    raise

        return Reader()

    class Client:
        def list_blobs(self, bucket_name, prefix):
            return [SimpleNamespace(name="datasets/AvesChilenas/Chucao/seed.wav")]
        def bucket(self, name): return self
        def blob(self, key): return self
        def download_as_bytes(self):
            uploaded.set()  # Source ready, before the shared dataset lock.
            return source
        def upload_from_string(self, data, **kwargs):
            raise AssertionError("Approval must not upload synchronously")

    try:
        with Session(engine) as db, patch.object(storage.storage, "Client", Client), \
                patch.object(csv, "reader", controlled_reader):
            pred = Prediccion(id_prediccion=feedback_id,
                              ruta_audio_prueba="raw_audios/0123456789abcdef0123456789abcdef.wav",
                              etiqueta_predicha="Chucao", confianza=.9, dataset_name="AvesChilenas")
            fb = Retroalimentacion(id_retroalimentacion=feedback_id,
                                   id_prediccion=feedback_id, fue_correcta=True, procesado=False)
            db.add_all([pred, fb])
            db.commit()
            service = FeedbackService(raw_data_dir=raw_dir)
            # Fail after both destinations and metadata were written, then retry.
            with patch.object(db, "commit", side_effect=OSError("commit unavailable")):
                with pytest.raises(HTTPException) as error:
                    service.approve_feedback(db, feedback_id)
                assert error.value.status_code == 503
            attempt_done.set()
            assert retry.wait(10), "Parent did not release retries"
            result = service.approve_feedback(db, feedback_id)
            assert (raw_dir / "AvesChilenas/Chucao" / result["filename"]).read_bytes() == source
            assert service.get_pending_feedback(db) == []
            results.put((feedback_id, "ok"))
    except BaseException as error:
        attempt_done.set()
        results.put((feedback_id, repr(error)))
        raise


def test_concurrent_process_approvals_preserve_both_rows_and_retries(workflow):
    service, db, pred, fb, objects = workflow
    # Independent admissions need different valid audio, not duplicate hashes.
    second_source = io.BytesIO()
    with wave.open(second_source, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b"\x02\x00\xfe\xff" * 100)
    sources = [objects[pred.ruta_audio_prueba], second_source.getvalue()]
    context = multiprocessing.get_context("fork")
    release_read, retry = context.Event(), context.Event()
    snapshots = [context.Event(), context.Event()]
    uploaded = [context.Event(), context.Event()]
    done = [context.Event(), context.Event()]
    results = context.Queue()
    processes = [context.Process(target=_concurrent_approval_worker, args=(
        service.raw_data_dir, sources[index], index + 1,
        snapshots[index], uploaded[index], release_read, done[index], retry, results,
    )) for index in range(2)]
    metadata = service.raw_data_dir / "AvesChilenas/metadata.csv"
    started = []
    try:
        processes[0].start()
        started.append(processes[0])
        assert snapshots[0].wait(10), "First approval never reached the metadata read"
        processes[1].start()
        started.append(processes[1])
        assert uploaded[1].wait(10), "Second approval never reached the shared dataset"
        # Without serialization the second reader completes while the first holds
        # its stale snapshot. Wait for its replacement before releasing the first.
        if snapshots[1].wait(1):
            assert done[1].wait(10)
        release_read.set()
        assert all(event.wait(10) for event in done)
        with metadata.open() as stream:
            rows_before_retry = list(csv.reader(stream))
    finally:
        release_read.set()
        retry.set()
        for process in started:
            process.join(15)
    assert all(process.exitcode == 0 for process in started)
    assert sorted(results.get(timeout=2) for _ in started) == [(1, "ok"), (2, "ok")]
    expected = {"feedback_1.wav", "feedback_2.wav"}
    assert {row[0] for row in rows_before_retry[1:]} == expected
    with metadata.open() as stream:
        rows_after_retry = list(csv.reader(stream))
    assert len(rows_after_retry) == 3
    assert {row[0] for row in rows_after_retry[1:]} == expected
    assert rows_after_retry == rows_before_retry


def test_approval_preserves_exact_source_locally_and_enqueues_cloud_identity(workflow):
    service, db, pred, fb, objects = workflow
    before = objects.copy()
    result = service.approve_feedback(db, fb.id_retroalimentacion)
    assert objects == before
    assert result["filename"] == "feedback_1.wav"
    assert result["sync_status"] == "pending"
    assert (service.raw_data_dir / "AvesChilenas/Chucao/feedback_1.wav").read_bytes() == objects[pred.ruta_audio_prueba]
    assert FeedbackSyncQueue().get(db, 1).object_key == "datasets/AvesChilenas/Chucao/feedback_1.wav"
    assert service.get_pending_feedback(db) == []


@pytest.mark.parametrize("failure", ["missing", "local", "metadata"])
def test_failed_approval_stays_pending_and_retry_has_no_duplicates(workflow, monkeypatch, failure):
    service, db, pred, fb, objects = workflow
    source = objects[pred.ruta_audio_prueba]
    if failure == "missing":
        objects.clear()
    elif failure == "local":
        destination = service.raw_data_dir / "AvesChilenas/Chucao"
        # Obstruct publication only after the real local catalogue was resolved.
        original_client = storage.storage.Client

        class ObstructingClient(original_client):
            def blob(self, key):
                def download():
                    destination.rename(service.raw_data_dir / ".saved_chucao")
                    destination.write_text("not a directory")
                    return objects[key]
                return SimpleNamespace(download_as_bytes=download)

        monkeypatch.setattr(storage.storage, "Client", ObstructingClient)
    else:
        (service.raw_data_dir / "AvesChilenas/metadata.csv.pending").mkdir()
    with pytest.raises(HTTPException) as error:
        service.approve_feedback(db, fb.id_retroalimentacion)
    assert error.value.status_code == 503
    assert len(service.get_pending_feedback(db)) == 1
    intent = service.raw_data_dir / f".feedback_{fb.id_retroalimentacion}.json"
    if failure == "missing":
        # No source bytes means no durable admission intent yet.
        assert not intent.exists()
        assert service.record_feedback(db, pred.id_prediccion, True).id_retroalimentacion == fb.id_retroalimentacion
    else:
        assert intent.exists()
        with pytest.raises(HTTPException) as error:
            service.record_feedback(db, pred.id_prediccion, False, "Turca")
        assert error.value.status_code == 409
    assert (service.raw_data_dir / "AvesChilenas/metadata.csv").read_text() == "nombre_archivo,clase,file_path,file_stage\n"
    audio_path = service.raw_data_dir / "AvesChilenas/Chucao/feedback_1.wav"
    if failure == "metadata":
        assert audio_path.read_bytes() == source
    else:
        assert not audio_path.exists()
    intent_before_retry = intent.read_bytes() if intent.exists() else None
    if failure == "local":
        # The obstruction is a test fixture, not production data.
        destination.rename(service.raw_data_dir / "obstruction")
        (service.raw_data_dir / ".saved_chucao").rename(destination)
    if failure == "metadata":
        (service.raw_data_dir / "AvesChilenas/metadata.csv.pending").rename(service.raw_data_dir / "metadata_obstruction")
    monkeypatch.undo()
    # Restore the fake after undoing the injected failure.
    objects[pred.ruta_audio_prueba] = source
    class Client:
        def list_blobs(self, bucket_name, prefix):
            return [SimpleNamespace(name="datasets/AvesChilenas/Chucao/seed.wav")]
        def bucket(self, name): return self
        def blob(self, key):
            class Blob:
                def download_as_bytes(self): return objects[key]
                def upload_from_string(self, data, **kwargs): objects[key] = data
            return Blob()
    monkeypatch.setattr(storage.storage, "Client", Client)
    service.approve_feedback(db, fb.id_retroalimentacion)
    assert service.approve_feedback(db, fb.id_retroalimentacion)["sync_status"] == "pending"
    with (service.raw_data_dir / "AvesChilenas/metadata.csv").open() as f:
        assert len(list(csv.reader(f))) == 2
    assert len(objects) == 1
    assert audio_path.read_bytes() == source
    assert service.get_pending_feedback(db) == []
    assert len(FeedbackSyncQueue().pending(db)) == 1
    if intent_before_retry is not None:
        assert intent.read_bytes() == intent_before_retry


def test_database_failure_after_both_writes_retries_without_metadata_duplicates(workflow, monkeypatch):
    service, db, pred, fb, objects = workflow
    commit = db.commit
    commit_attempts = []
    def fail_commit():
        commit_attempts.append(True)
        raise OSError("database commit unavailable")
    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(HTTPException) as error:
        service.approve_feedback(db, fb.id_retroalimentacion)
    assert error.value.status_code == 503
    assert commit_attempts == [True]
    assert (service.raw_data_dir / "AvesChilenas/Chucao/feedback_1.wav").read_bytes() == objects[pred.ruta_audio_prueba]
    metadata_before_retry = (service.raw_data_dir / "AvesChilenas/metadata.csv").read_bytes()
    assert len(service.get_pending_feedback(db)) == 1
    monkeypatch.setattr(db, "commit", commit)
    service.approve_feedback(db, fb.id_retroalimentacion)
    with (service.raw_data_dir / "AvesChilenas/metadata.csv").open() as stream:
        assert len(list(csv.reader(stream))) == 2
    assert len(objects) == 1
    assert len(FeedbackSyncQueue().pending(db)) == 1
    assert (service.raw_data_dir / "AvesChilenas/metadata.csv").read_bytes() == metadata_before_retry


def test_rejection_preserves_source_and_final_decision(workflow):
    service, db, pred, fb, objects = workflow
    original = objects.copy()
    service.reject_feedback(db, fb.id_retroalimentacion)
    assert objects == original
    assert service.get_pending_feedback(db) == []
    for operation in [lambda: service.approve_feedback(db, fb.id_retroalimentacion),
                      lambda: service.reject_feedback(db, fb.id_retroalimentacion),
                      lambda: service.record_feedback(db, pred.id_prediccion, False, "Turca")]:
        with pytest.raises(HTTPException) as error:
            operation()
        assert error.value.status_code == 409


@pytest.mark.parametrize("dataset,label", [("../escape", "Chucao"), ("AvesChilenas", "../escape"), ("AvesChilenas", " ")])
def test_unsafe_paths_never_write(workflow, dataset, label):
    service, db, pred, fb, objects = workflow
    pred.etiqueta_predicha = label
    db.commit()
    with pytest.raises(HTTPException) as error:
        service.approve_feedback(db, fb.id_retroalimentacion, dataset)
    assert error.value.status_code == 422
    assert len(objects) == 1
    assert len(service.get_pending_feedback(db)) == 1
    assert list(service.raw_data_dir.rglob("*.wav")) == []
    assert not (service.raw_data_dir / f".feedback_{fb.id_retroalimentacion}.json").exists()


def test_legacy_unassociated_prediction_cannot_be_rescued_by_override(workflow):
    service, db, pred, fb, objects = workflow
    pred.dataset_name = None
    db.commit()
    before = objects.copy()
    for override in (None, "AvesChilenas"):
        with pytest.raises(HTTPException) as error:
            service.approve_feedback(db, fb.id_retroalimentacion, override)
        assert error.value.status_code == 409
    assert objects == before
    assert len(service.get_pending_feedback(db)) == 1
    assert list(service.raw_data_dir.rglob("*.wav")) == []
    assert not (service.raw_data_dir / f".feedback_{fb.id_retroalimentacion}.json").exists()


@pytest.mark.parametrize("catalogue", ["ambiguous", "absent"])
def test_unverifiable_local_class_stays_pending_without_artifact_writes(workflow, catalogue):
    service, db, pred, fb, objects = workflow
    pred.etiqueta_predicha = "RAYADITO"
    db.commit()
    before = objects.copy()

    if catalogue == "ambiguous":
        for label in ("Rayadito", "rayadito"):
            (service.raw_data_dir / "AvesChilenas" / label).mkdir()
    with patch.object(storage.storage, "Client") as client:
        with pytest.raises(HTTPException) as error:
            service.approve_feedback(db, fb.id_retroalimentacion)
        assert error.value.status_code == 422
        client.assert_not_called()
    assert (service.raw_data_dir / "AvesChilenas/metadata.csv").read_text() == "nombre_archivo,clase,file_path,file_stage\n"
    assert FeedbackSyncQueue().pending(db) == []
    assert objects == before
    assert len(service.get_pending_feedback(db)) == 1
    assert list(service.raw_data_dir.rglob("*.wav")) == []
    assert not (service.raw_data_dir / f".feedback_{fb.id_retroalimentacion}.json").exists()


def test_known_local_class_approval_succeeds_despite_unavailable_cloud_catalogue(workflow, monkeypatch):
    service, db, pred, fb, objects = workflow
    before = objects.copy()
    catalogue_calls = []
    original_client = storage.storage.Client

    class UnavailableCatalogueClient(original_client):
        def list_blobs(self, bucket_name, prefix):
            catalogue_calls.append((bucket_name, prefix))
            raise OSError("catalogue unavailable")

    monkeypatch.setattr(storage.storage, "Client", UnavailableCatalogueClient)
    result = service.approve_feedback(db, fb.id_retroalimentacion)
    assert result["status"] == "approved"
    assert result["sync_status"] == "pending"
    assert catalogue_calls == []
    assert objects == before
    assert (service.raw_data_dir / "AvesChilenas/Chucao/feedback_1.wav").read_bytes() == objects[pred.ruta_audio_prueba]
    assert service.get_pending_feedback(db) == []
    assert len(FeedbackSyncQueue().pending(db)) == 1
