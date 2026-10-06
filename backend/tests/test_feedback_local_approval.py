"""Local-first approval through public seams, with no deployed services."""
import csv
import io
import wave
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from unittest.mock import patch

with patch("dotenv.load_dotenv", return_value=False):
    from app.database import Base
    from app.models.prediction import Prediccion
    from app.services import storage
    from app.services.feedback import FeedbackService
    from app.services.feedback_sync import FeedbackSyncQueue
from training.datasets.local_folder import LocalFolderPAMIngestor


@pytest.fixture
def local_workflow(tmp_path, monkeypatch):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x01\x00" * 800)
    audio = stream.getvalue()
    calls = []

    class Client:
        def list_blobs(self, *args, **kwargs):
            calls.append("list")
            raise OSError("Cloud catalogue offline")

        def bucket(self, name):
            return self

        def blob(self, key):
            assert key == "raw_audios/0123456789abcdef0123456789abcdef.wav"
            return self

        def download_as_bytes(self):
            calls.append("download")
            return audio

        def upload_from_string(self, *args, **kwargs):
            calls.append("upload")
            raise OSError("Uploads offline")

    monkeypatch.setattr(storage.storage, "Client", Client)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = FeedbackService(tmp_path / "raw")
        (service.raw_data_dir / "AvesChilenas/rayadito").mkdir(parents=True)
        pred = Prediccion(ruta_audio_prueba="raw_audios/0123456789abcdef0123456789abcdef.wav",
                          etiqueta_predicha="Rayadito", dataset_name="AvesChilenas", confianza=.9)
        db.add(pred)
        db.commit()
        fb = service.record_feedback(db, pred.id_prediccion, True)
        yield SimpleNamespace(service=service, db=db, pred=pred, fb=fb,
                              audio=audio, calls=calls, root=tmp_path)
    engine.dispose()


def test_approved_sample_is_trainable_before_cloud_sync(local_workflow):
    w = local_workflow
    result = w.service.approve_feedback(w.db, w.fb.id_retroalimentacion)
    assert result["filename"] == "feedback_1.wav"
    assert result["local_status"] == "incorporated"
    assert result["sync_status"] == "pending"
    assert result["clase"] == "Rayadito"
    dataset = w.service.raw_data_dir / "AvesChilenas"
    assert (dataset / "rayadito/feedback_1.wav").read_bytes() == w.audio
    assert w.calls == ["download"]
    intent = FeedbackSyncQueue().get(w.db, 1)
    assert intent.object_key == "datasets/AvesChilenas/rayadito/feedback_1.wav"
    assert intent.local_relative_path == "AvesChilenas/rayadito/feedback_1.wav"
    assert intent.status == "pending"
    assert intent.attempts == 0
    assert w.service.get_pending_feedback(w.db) == []
    metadata = dataset / "metadata.csv"
    with metadata.open() as stream:
        row = list(csv.DictReader(stream))[0]
    assert row["nombre_archivo"] == "feedback_1.wav"
    assert row["clase"] == "Rayadito"
    assert row["frecuencia_muestreo"] == "8000"
    assert row["duracion_segundos"] == "0.1"
    assert row["xc_id"] == "feedback_1"
    # Training prioritizes file_path; class directories need not equal label.lower().
    assert row["file_path"] == "rayadito/feedback_1.wav"
    assert row["file_stage"] == "raw"
    # The real local ingestor accepts this metadata as semantic annotations.
    samples = LocalFolderPAMIngestor(dataset, annotations_csv=metadata).ingest()
    assert len(samples) == 1
    sample = samples.iloc[0]
    assert sample["nombre_archivo"] == "feedback_1.wav"
    assert sample["clase"] == "Rayadito"
    assert sample["frecuencia_muestreo"] == 8000
    assert sample["duracion_segundos"] == .1
    assert sample["file_path"] == "rayadito/feedback_1.wav"
    assert sample["file_stage"] == "raw"


def test_legacy_index_rejection_preserves_durable_intent(local_workflow, monkeypatch):
    w = local_workflow
    commit = w.db.commit
    monkeypatch.setattr(w.db, "commit", lambda: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(HTTPException):
        w.service.approve_feedback(w.db, 1)
    monkeypatch.setattr(w.db, "commit", commit)
    dataset = w.service.raw_data_dir / "AvesChilenas"
    metadata = dataset / "metadata.csv"
    with metadata.open() as stream:
        reader = csv.DictReader(stream)
        columns = [field for field in reader.fieldnames if field != "file_stage"]
        rows = [{field: row[field] for field in columns} for row in reader]
    with metadata.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    original = metadata.read_bytes()
    intent = w.service.raw_data_dir / ".feedback_1.json"
    recorded = intent.read_bytes()
    audio = (dataset / "rayadito/feedback_1.wav").read_bytes()
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 422
    assert metadata.read_bytes() == original
    assert intent.read_bytes() == recorded
    assert (dataset / "rayadito/feedback_1.wav").read_bytes() == audio
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert w.service.get_pending_feedback(w.db)[0]["procesado"] is False


def test_raw_index_ignores_historical_processed_link(local_workflow):
    w = local_workflow
    dataset = w.service.raw_data_dir / "AvesChilenas"
    (dataset / "rayadito/42.mp3").write_bytes(b"raw original")
    processed = w.root / "processed"
    processed.mkdir()
    (processed / "42.wav").write_bytes(b"derived sentinel")
    (dataset / "processed_wav").symlink_to(processed, target_is_directory=True)
    metadata = dataset / "metadata.csv"
    metadata.write_text("nombre_archivo,clase,file_path,file_stage\n42.mp3,Rayadito,rayadito/42.mp3,raw\n")
    assert w.service.approve_feedback(w.db, 1)["local_status"] == "incorporated"
    with metadata.open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["file_path"] == "rayadito/42.mp3"
    assert rows[0]["file_stage"] == "raw"
    assert (processed / "42.wav").read_bytes() == b"derived sentinel"
    assert LocalFolderPAMIngestor(dataset, annotations_csv=metadata).ingest().iloc[0]["file_path"] == "rayadito/42.mp3"


def mixed_class_catalogue(w, label="Chucao", canonical="chucao", alternate="Chucao"):
    dataset = w.service.raw_data_dir / "AvesChilenas"
    (dataset / canonical).mkdir()
    (dataset / alternate).mkdir()
    (dataset / canonical / "XC123.mp3").write_bytes(b"indexed mp3")
    (dataset / canonical / "XC124.mp3").write_bytes(b"indexed mp3")
    (dataset / alternate / "chucao_01.wav").write_bytes(w.audio)
    w.service.record_feedback(w.db, w.pred.id_prediccion, False, label)
    return dataset


def write_class_metadata(dataset, rows, *, explicit=False):
    # Synthetic canonical fixtures; historical test names retain their business cases.
    columns = ["nombre_archivo", "clase", "xc_id", "file_path", "file_stage"]
    rows = [dict(row, file_stage=row.get("file_stage", "raw"),
                 file_path=row.get("file_path", f"chucao/{row['nombre_archivo']}")) for row in rows]
    with (dataset / "metadata.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_mixed_legacy_catalogue_approval_uses_indexed_directory_and_replays(local_workflow):
    w = local_workflow
    dataset = mixed_class_catalogue(w)
    write_class_metadata(dataset, [
        {"nombre_archivo": "XC123.mp3", "clase": "Chucao", "xc_id": "123"},
        {"nombre_archivo": "XC124.mp3", "clase": "chucao", "xc_id": "124"},
    ])
    result = w.service.approve_feedback(w.db, 1)
    assert result["destination_path"] == str(dataset / "chucao/feedback_1.wav")
    assert result["clase"] == "Chucao"
    assert result["sync_status"] == "pending"
    assert (dataset / "chucao/feedback_1.wav").read_bytes() == w.audio
    assert (dataset / "Chucao/chucao_01.wav").read_bytes() == w.audio
    queue = FeedbackSyncQueue()
    assert queue.get(w.db, 1).storage_class == "chucao"
    assert queue.get(w.db, 1).class_label == "Chucao"
    assert queue.get(w.db, 1).attempts == 0
    assert w.service.get_pending_feedback(w.db) == []
    with (dataset / "metadata.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert [row["file_path"] for row in rows] == [
        "chucao/XC123.mp3", "chucao/XC124.mp3", "chucao/feedback_1.wav"]
    assert rows[-1]["clase"] == "Chucao"
    samples = LocalFolderPAMIngestor(dataset, annotations_csv=dataset / "metadata.csv").ingest()
    accepted = samples[samples["nombre_archivo"] == "feedback_1.wav"].iloc[0]
    assert accepted["file_path"] == "chucao/feedback_1.wav"
    assert accepted["file_stage"] == "raw"
    assert accepted["clase"] == "Chucao"
    before = (dataset / "metadata.csv").read_bytes()
    assert FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1) == result
    assert (dataset / "metadata.csv").read_bytes() == before
    assert len(queue.pending(w.db)) == 1
    assert w.calls == ["download"]


@pytest.mark.parametrize("absolute", [False, True])
def test_mixed_catalogue_explicit_path_overrides_label_and_legacy_copies(local_workflow, absolute):
    w = local_workflow
    dataset = mixed_class_catalogue(w, label="CHUCAO")
    # Explicit references, not capitalization or legacy filename copies, are authoritative.
    (dataset / "Chucao/XC123.mp3").write_bytes(b"other copy")
    target = dataset / "Chucao/chucao_01.wav"
    reference = str(target) if absolute else "Chucao/chucao_01.wav"
    write_class_metadata(dataset, [
        {"nombre_archivo": "XC123.mp3", "clase": "chucao", "xc_id": "123",
         "file_path": reference},
    ], explicit=True)
    if absolute:
        before = (dataset / "metadata.csv").read_bytes()
        with pytest.raises(HTTPException) as error:
            w.service.approve_feedback(w.db, 1)
        assert error.value.status_code == 422
        assert (dataset / "metadata.csv").read_bytes() == before
        assert w.calls == []
        return
    result = w.service.approve_feedback(w.db, 1)
    assert result["destination_path"] == str(dataset / "Chucao/feedback_1.wav")
    assert result["clase"] == "CHUCAO"
    with (dataset / "metadata.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["file_path"] == "Chucao/chucao_01.wav"
    assert rows[-1]["file_path"] == "Chucao/feedback_1.wav"
    assert w.calls == ["download"]


@pytest.mark.parametrize("failure", [
    "absent_csv", "empty_csv", "unrelated_rows", "missing_audio", "duplicate_copy",
    "contradictory_legacy", "contradictory_explicit", "missing_explicit", "external_path",
    "traversal", "unrelated_path", "filename_traversal", "audio_symlink",
    "class_symlink", "metadata_symlink", "malformed_row", "short_row", "duplicate_header",
    "blank_filename", "malformed_explicit",
])
def test_mixed_catalogue_without_unanimous_safe_evidence_stays_pending(local_workflow, failure):
    w = local_workflow
    dataset = mixed_class_catalogue(w)
    rows = [{"nombre_archivo": "XC123.mp3", "clase": "Chucao", "xc_id": "123"}]
    explicit = False
    outside = w.root / "outside.mp3"
    outside.write_bytes(b"external sentinel")
    if failure == "empty_csv":
        rows = []
    elif failure == "unrelated_rows":
        rows[0]["clase"] = "Rayadito"
    elif failure == "missing_audio":
        rows.append({"nombre_archivo": "missing.mp3", "clase": "chucao", "xc_id": "999"})
    elif failure == "duplicate_copy":
        (dataset / "Chucao/XC123.mp3").write_bytes(b"duplicate")
        rows.append({"nombre_archivo": "XC123.mp3", "clase": "Chucao", "xc_id": "123",
                     "file_path": "Chucao/XC123.mp3"})
    elif failure == "contradictory_legacy":
        rows.append({"nombre_archivo": "chucao_01.wav", "clase": "CHUCAO", "xc_id": "999",
                     "file_path": "Chucao/chucao_01.wav"})
    elif failure in ("contradictory_explicit", "missing_explicit", "external_path", "traversal",
                     "unrelated_path", "malformed_explicit"):
        explicit = True
        rows[0]["file_path"] = {
            "contradictory_explicit": "chucao/XC123.mp3",
            "missing_explicit": "chucao/missing.mp3",
            "external_path": str(outside),
            "traversal": "Chucao/../chucao/XC123.mp3",
            "unrelated_path": "rayadito/seed.mp3",
            "malformed_explicit": "chucao//XC123.mp3",
        }[failure]
        if failure == "contradictory_explicit":
            rows.append({"nombre_archivo": "chucao_01.wav", "clase": "Chucao", "xc_id": "999",
                         "file_path": "Chucao/chucao_01.wav"})
        elif failure == "unrelated_path":
            (dataset / "rayadito/seed.mp3").write_bytes(b"unrelated")
    elif failure == "filename_traversal":
        rows[0]["nombre_archivo"] = "../chucao/XC123.mp3"
    elif failure == "audio_symlink":
        # A dangling explicit reference must not fall back to the real filename copy.
        (dataset / "Chucao/XC123.mp3").symlink_to(w.root / "missing_external.mp3")
        rows[0]["file_path"] = "Chucao/XC123.mp3"
    elif failure == "class_symlink":
        (dataset / "Chucao").rename(dataset / "unrelated")
        (dataset / "Chucao").symlink_to(dataset / "chucao", target_is_directory=True)
    elif failure == "blank_filename":
        rows[0]["nombre_archivo"] = ""
    if failure != "absent_csv":
        write_class_metadata(dataset, rows, explicit=explicit)
    metadata = dataset / "metadata.csv"
    if failure == "metadata_symlink":
        metadata.rename(w.root / "external.csv")
        metadata.symlink_to(w.root / "external.csv")
    elif failure == "malformed_row":
        metadata.write_text("nombre_archivo,clase,xc_id\nXC123.mp3,Chucao,123,extra\n")
    elif failure == "short_row":
        metadata.write_text("nombre_archivo,clase,xc_id\nXC123.mp3,Chucao\n")
    elif failure == "duplicate_header":
        metadata.write_text("nombre_archivo,clase,clase\nXC123.mp3,Chucao,Chucao\n")
    before = metadata.read_bytes() if metadata.exists() else None
    directories = sorted(path.name for path in dataset.iterdir())
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 422
    assert w.calls == []
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert w.service.get_pending_feedback(w.db)[0]["procesado"] is False
    assert not (w.service.raw_data_dir / ".feedback_1.json").exists()
    assert not list(dataset.rglob("feedback_1.wav*"))
    assert sorted(path.name for path in dataset.iterdir()) == directories
    assert (metadata.read_bytes() if metadata.exists() else None) == before
    assert outside.read_bytes() == b"external sentinel"


@pytest.mark.parametrize("label,canonical,alternate", [
    ("Canastero", "canastero", "Canastero"),
    ("Churrín de la Mocha", "churrín_de_la_mocha", "Churrín de la Mocha"),
    ("Churri\u0301n de la Mocha", "churrín_de_la_mocha", "CHURRÍN DE LA MOCHA"),
])
def test_mixed_legacy_catalogue_normalizes_all_relevant_rows(local_workflow, label, canonical, alternate):
    w = local_workflow
    dataset = mixed_class_catalogue(w, label, canonical, alternate)
    write_class_metadata(dataset, [
        {"nombre_archivo": "XC123.mp3", "clase": label, "xc_id": "123",
         "file_path": f"{canonical}/XC123.mp3"},
        {"nombre_archivo": "XC124.mp3", "clase": canonical, "xc_id": "124",
         "file_path": f"{canonical}/XC124.mp3"},
    ])
    result = w.service.approve_feedback(w.db, 1)
    assert result["destination_path"] == str(dataset / canonical / "feedback_1.wav")
    assert result["clase"] == label
    assert FeedbackSyncQueue().get(w.db, 1).storage_class == canonical
    assert w.calls == ["download"]


def test_failed_database_commit_keeps_recoverable_intent_not_approval(local_workflow, monkeypatch):
    w = local_workflow
    commit = w.db.commit
    monkeypatch.setattr(w.db, "commit", lambda: (_ for _ in ()).throw(OSError("DB offline")))
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 503
    assert w.service.get_pending_feedback(w.db)[0]["procesado"] is False
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert (w.service.raw_data_dir / "AvesChilenas/rayadito/feedback_1.wav").read_bytes() == w.audio
    monkeypatch.setattr(w.db, "commit", commit)
    # Discard cannot abandon a durable incorporation intent after a failed commit.
    with pytest.raises(HTTPException) as error:
        w.service.reject_feedback(w.db, 1)
    assert error.value.status_code == 409
    w.calls.clear()
    reconstructed = FeedbackService(w.service.raw_data_dir)
    assert reconstructed.approve_feedback(w.db, 1)["sync_status"] == "pending"
    assert w.calls == []
    assert w.service.get_pending_feedback(w.db) == []
    assert len(FeedbackSyncQueue().pending(w.db)) == 1
    with (w.service.raw_data_dir / "AvesChilenas/metadata.csv").open() as stream:
        assert len(list(csv.DictReader(stream))) == 1


@pytest.mark.parametrize("committed", [False, True])
def test_durable_class_replay_without_current_local_catalogue(local_workflow, monkeypatch, committed):
    w = local_workflow
    if committed:
        w.service.approve_feedback(w.db, 1)
    else:
        commit = w.db.commit
        monkeypatch.setattr(w.db, "commit", lambda: (_ for _ in ()).throw(OSError("DB offline")))
        with pytest.raises(HTTPException) as error:
            w.service.approve_feedback(w.db, 1)
        assert error.value.status_code == 503
        monkeypatch.setattr(w.db, "commit", commit)
        assert FeedbackSyncQueue().get(w.db, 1) is None
    dataset = w.service.raw_data_dir / "AvesChilenas"
    previous = w.root / "previous_dataset"
    dataset.rename(previous)
    metadata = (previous / "metadata.csv").read_bytes()
    intent = w.service.raw_data_dir / ".feedback_1.json"
    recorded = intent.read_bytes()
    w.calls.clear()
    result = FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)
    assert result["destination_path"] == str(dataset / "rayadito/feedback_1.wav")
    assert result["sync_status"] == "pending"
    assert w.calls == ["download"]
    assert (dataset / "rayadito/feedback_1.wav").read_bytes() == w.audio
    assert (previous / "rayadito/feedback_1.wav").read_bytes() == w.audio
    assert (previous / "metadata.csv").read_bytes() == metadata
    assert intent.read_bytes() == recorded
    assert FeedbackSyncQueue().get(w.db, 1).storage_class == "rayadito"
    assert len(FeedbackSyncQueue().pending(w.db)) == 1
    assert w.service.get_pending_feedback(w.db) == []


def test_queue_flush_failure_rolls_back_both_relational_changes(local_workflow, monkeypatch):
    w = local_workflow
    flush = w.db.flush

    def fail_queue_flush(*args, **kwargs):
        if any(type(row).__name__ == "FeedbackSync" for row in w.db.new):
            raise OSError("Database write failure")
        return flush(*args, **kwargs)

    monkeypatch.setattr(w.db, "flush", fail_queue_flush)
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 503
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert w.service.get_pending_feedback(w.db)[0]["procesado"] is False
    monkeypatch.setattr(w.db, "flush", flush)
    assert FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)["local_status"] == "incorporated"


def test_commit_acknowledgement_loss_replays_committed_approval(local_workflow, monkeypatch):
    w = local_workflow
    commit = w.db.commit

    def lost_ack():
        commit()
        raise OSError("Commit acknowledgement lost")

    monkeypatch.setattr(w.db, "commit", lost_ack)
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 503
    monkeypatch.setattr(w.db, "commit", commit)
    assert w.service.get_pending_feedback(w.db) == []
    assert FeedbackSyncQueue().get(w.db, 1).status == "pending"
    assert FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)["sync_status"] == "pending"


def test_approval_replay_preserves_sync_outcome_without_new_attempt(local_workflow):
    w = local_workflow
    w.service.approve_feedback(w.db, 1)
    queue = FeedbackSyncQueue()
    # Simulate a later, independently verified uploader outcome via the public queue.
    queue.mark_outcome(w.db, 1, success=True)
    w.db.commit()
    result = FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)
    assert result["local_status"] == "incorporated"
    assert result["sync_status"] == "synced"
    assert queue.get(w.db, 1).attempts == 1
    assert queue.pending(w.db) == []
    assert w.calls == ["download"]


def test_processed_rejected_item_has_no_approved_replay(local_workflow):
    w = local_workflow
    assert w.service.reject_feedback(w.db, 1)["status"] == "rejected"
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 409
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert w.calls == []
    assert list(w.service.raw_data_dir.rglob("*.wav")) == []


@pytest.mark.parametrize("mutation", ["dataset", "label", "source"])
def test_replay_refuses_changed_identity(local_workflow, mutation):
    w = local_workflow
    w.service.approve_feedback(w.db, 1)
    if mutation == "dataset":
        w.pred.dataset_name = "OtherDataset"
    elif mutation == "label":
        w.fb.fue_correcta = False
        w.fb.etiqueta_corregida = "Turca"
    else:
        w.pred.ruta_audio_prueba = "raw_audios/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.wav"
    w.db.commit()
    with pytest.raises(HTTPException) as error:
        FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)
    assert error.value.status_code == 422
    intent = FeedbackSyncQueue().get(w.db, 1)
    assert intent.class_label == "Rayadito"
    assert intent.dataset_name == "AvesChilenas"
    assert intent.local_relative_path == "AvesChilenas/rayadito/feedback_1.wav"
    assert w.calls == ["download"]


@pytest.mark.parametrize("same_bytes", [True, False])
def test_existing_canonical_audio_is_only_reused_when_hash_verified(local_workflow, same_bytes):
    w = local_workflow
    destination = w.service.raw_data_dir / "AvesChilenas/rayadito/feedback_1.wav"
    original = w.audio if same_bytes else b"unrelated recording"
    destination.write_bytes(original)
    inode = destination.stat().st_ino
    if same_bytes:
        assert w.service.approve_feedback(w.db, 1)["local_status"] == "incorporated"
        assert FeedbackSyncQueue().get(w.db, 1).status == "pending"
    else:
        with pytest.raises(HTTPException) as error:
            w.service.approve_feedback(w.db, 1)
        assert error.value.status_code == 422
        assert FeedbackSyncQueue().get(w.db, 1) is None
        assert len(w.service.get_pending_feedback(w.db)) == 1
        assert not (w.service.raw_data_dir / "AvesChilenas/metadata.csv").exists()
    assert destination.stat().st_ino == inode
    assert destination.read_bytes() == original


def test_corrupt_local_replay_cannot_claim_success_or_replace_audio(local_workflow):
    w = local_workflow
    w.service.approve_feedback(w.db, 1)
    destination = w.service.raw_data_dir / "AvesChilenas/rayadito/feedback_1.wav"
    destination.write_bytes(b"corrupted")
    with pytest.raises(HTTPException) as error:
        FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)
    assert error.value.status_code == 422
    assert destination.read_bytes() == b"corrupted"
    assert FeedbackSyncQueue().get(w.db, 1).status == "pending"
    assert w.calls == ["download"]


@pytest.mark.parametrize("path", ["class", "audio", "metadata", "intent", "stage", "dataset", "raw_ancestor"])
def test_symlinks_cannot_redirect_local_incorporation(local_workflow, path):
    w = local_workflow
    dataset = w.service.raw_data_dir / "AvesChilenas"
    outside = w.root / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"must survive")
    if path == "class":
        (dataset / "rayadito").rename(dataset / "old_class")
        (dataset / "rayadito").symlink_to(outside, target_is_directory=True)
    elif path == "dataset":
        dataset.rename(w.root / "old_dataset")
        dataset.symlink_to(outside, target_is_directory=True)
    elif path == "raw_ancestor":
        alias = w.root / "alias"
        alias.symlink_to(w.service.raw_data_dir, target_is_directory=True)
        w.service = FeedbackService(alias / "nested")
    else:
        selected = {"audio": dataset / "rayadito/feedback_1.wav",
                    "metadata": dataset / "metadata.csv",
                    "intent": w.service.raw_data_dir / ".feedback_1.json",
                    "stage": dataset / "rayadito/feedback_1.wav.pending"}[path]
        selected.symlink_to(sentinel)
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 422
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert len(w.service.get_pending_feedback(w.db)) == 1
    assert sentinel.read_bytes() == b"must survive"
    assert sorted(p.name for p in outside.iterdir()) == ["sentinel"]


@pytest.mark.parametrize("catalogue", ["ambiguous", "unknown", "metadata", "spaces", "cloud", "cloud_empty_index"])
def test_trusted_local_class_resolution_without_cloud_listing(local_workflow, monkeypatch, catalogue):
    w = local_workflow
    dataset = w.service.raw_data_dir / "AvesChilenas"
    if catalogue in ("cloud", "cloud_empty_index"):
        (dataset / "rayadito").rename(w.root / "old_class")
        if catalogue == "cloud_empty_index":
            (dataset / "metadata.csv").write_text("nombre_archivo,clase,file_path,file_stage\n")
        metadata = dataset / "metadata.csv"
        before = metadata.read_bytes() if metadata.exists() else None
        pending = w.service.get_pending_feedback(w.db)

        class Client:
            def list_blobs(self, *args, **kwargs):
                w.calls.append("list")
                return [SimpleNamespace(name="datasets/AvesChilenas/rayadito/seed.wav")]

            def bucket(self, name):
                return self

            def blob(self, key):
                assert key == w.pred.ruta_audio_prueba
                return self

            def download_as_bytes(self):
                w.calls.append("download")
                return w.audio

        monkeypatch.setattr(storage.storage, "Client", Client)
        with pytest.raises(HTTPException) as error:
            w.service.approve_feedback(w.db, 1)
        assert error.value.status_code == 422
        assert w.calls == []
        assert w.service.get_pending_feedback(w.db) == pending
        assert FeedbackSyncQueue().get(w.db, 1) is None
        assert not (w.service.raw_data_dir / ".feedback_1.json").exists()
        assert not list(dataset.rglob("*.wav*"))
        assert sorted(path.name for path in dataset.iterdir()) == (["metadata.csv"] if before else [])
        assert (metadata.read_bytes() if metadata.exists() else None) == before
        return
    if catalogue == "ambiguous":
        (dataset / "Rayadito").mkdir()
    elif catalogue == "unknown":
        w.pred.etiqueta_predicha = "Unknown"
        w.db.commit()
    elif catalogue == "metadata":
        # Verified explicit metadata establishes semantic labels independently of directories.
        (dataset / "metadata.csv").write_text("nombre_archivo,clase,file_path,file_stage\nseed.wav,Turca,Turca/seed.wav,raw\n")
        (dataset / "Turca").mkdir()
        (dataset / "Turca/seed.wav").write_bytes(w.audio)
        w.service.record_feedback(w.db, w.pred.id_prediccion, False, "Turca")
    else:
        (dataset / "Churrín_de_la_Mocha").mkdir()
        w.service.record_feedback(w.db, w.pred.id_prediccion, False, "Churrín de la Mocha")
    if catalogue in ("ambiguous", "unknown"):
        with pytest.raises(HTTPException) as error:
            w.service.approve_feedback(w.db, 1)
        assert error.value.status_code == 422
        assert w.calls == []
        assert FeedbackSyncQueue().get(w.db, 1) is None
    else:
        result = w.service.approve_feedback(w.db, 1)
        assert result["clase"] == ("Turca" if catalogue == "metadata" else "Churrín de la Mocha")
        assert w.calls == ["download"]
        with (dataset / "metadata.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        assert rows[-1]["file_path"] == ("Turca/feedback_1.wav" if catalogue == "metadata"
                                        else "Churrín_de_la_Mocha/feedback_1.wav")
        assert rows[-1]["clase"] == result["clase"]


def test_metadata_only_class_catalogue_is_usable(local_workflow):
    w = local_workflow
    dataset = w.service.raw_data_dir / "AvesChilenas"
    (dataset / "rayadito").rename(w.root / "old_class")
    (dataset / "metadata.csv").write_text("nombre_archivo,clase,file_path,file_stage\nseed.wav,Rayadito,seed.wav,raw\n")
    (dataset / "seed.wav").write_bytes(w.audio)
    result = w.service.approve_feedback(w.db, 1)
    assert result["destination_path"] == str(dataset / "Rayadito/feedback_1.wav")
    assert w.calls == ["download"]
    with (dataset / "metadata.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["file_path"] == "seed.wav"
    assert rows[1]["file_path"] == "Rayadito/feedback_1.wav"
    samples = LocalFolderPAMIngestor(dataset, annotations_csv=dataset / "metadata.csv").ingest()
    assert len(samples) == 2
    assert set(samples["clase"]) == {"Rayadito"}


@pytest.mark.parametrize("source", ["absent", "empty", "invalid_wav", "unmanaged"])
def test_unusable_source_never_produces_local_success(local_workflow, monkeypatch, source):
    w = local_workflow
    if source == "unmanaged":
        w.pred.ruta_audio_prueba = "legacy/feedback.wav"
        w.db.commit()
    else:
        class Client:
            def bucket(self, name): return self
            def blob(self, key): return self
            def download_as_bytes(self):
                if source == "absent":
                    raise FileNotFoundError("Source offline")
                return b"" if source == "empty" else b"not a wav"
        monkeypatch.setattr(storage.storage, "Client", Client)
    with pytest.raises(HTTPException):
        w.service.approve_feedback(w.db, 1)
    assert len(w.service.get_pending_feedback(w.db)) == 1
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert list(w.service.raw_data_dir.rglob("*.wav")) == []


@pytest.mark.parametrize("column,value", [("frecuencia_muestreo", "0"), ("tamano_bytes", "1"),
                                           ("recordist", ""), ("file_path", "other.wav")])
def test_replay_checks_trainable_metadata_not_only_audio_hash(local_workflow, column, value):
    w = local_workflow
    w.service.approve_feedback(w.db, 1)
    metadata = w.service.raw_data_dir / "AvesChilenas/metadata.csv"
    with metadata.open() as stream:
        reader = csv.DictReader(stream)
        columns, rows = reader.fieldnames, list(reader)
    rows[0][column] = value
    with metadata.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    before = metadata.read_bytes()
    with pytest.raises(HTTPException) as error:
        FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)
    assert error.value.status_code == 422
    assert metadata.read_bytes() == before
    assert FeedbackSyncQueue().get(w.db, 1).status == "pending"


def test_interrupted_csv_replace_preserves_old_index_and_recovers(local_workflow, monkeypatch):
    import os
    w = local_workflow
    metadata = w.service.raw_data_dir / "AvesChilenas/metadata.csv"
    original = b"nombre_archivo,clase,file_path,file_stage\n"
    metadata.write_bytes(original)
    replace = os.replace

    def interrupt(source, target, *args, **kwargs):
        if str(target).endswith("metadata.csv"):
            raise OSError("Interrupted metadata publication")
        return replace(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 503
    assert metadata.read_bytes() == original
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert len(w.service.get_pending_feedback(w.db)) == 1
    monkeypatch.setattr(os, "replace", replace)
    assert FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)["local_status"] == "incorporated"
    with metadata.open() as stream:
        assert len(list(csv.DictReader(stream))) == 1


def test_concurrent_foreign_audio_publication_is_not_overwritten(local_workflow, monkeypatch):
    import os
    w = local_workflow
    link = os.link
    destination = w.service.raw_data_dir / "AvesChilenas/rayadito/feedback_1.wav"

    def foreign_publication(source, target, *args, **kwargs):
        destination.write_bytes(b"foreign recording")
        return link(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "link", foreign_publication)
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 503
    assert destination.read_bytes() == b"foreign recording"
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert len(w.service.get_pending_feedback(w.db)) == 1
    monkeypatch.setattr(os, "link", link)
    with pytest.raises(HTTPException) as error:
        FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)
    assert error.value.status_code == 422
    assert destination.read_bytes() == b"foreign recording"


def test_fsync_failure_never_confirms_approval_and_can_retry(local_workflow, monkeypatch):
    import os
    w = local_workflow
    fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("Durability unavailable")))
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1)
    assert error.value.status_code == 503
    assert FeedbackSyncQueue().get(w.db, 1) is None
    assert len(w.service.get_pending_feedback(w.db)) == 1
    monkeypatch.setattr(os, "fsync", fsync)
    assert FeedbackService(w.service.raw_data_dir).approve_feedback(w.db, 1)["local_status"] == "incorporated"
