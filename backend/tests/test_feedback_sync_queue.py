"""Behavior through the durable queue's public interface; no cloud or audio IO."""
from dataclasses import FrozenInstanceError
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Prediccion, Retroalimentacion


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Prediccion(id_prediccion=1, ruta_audio_prueba="raw_audios/source.wav",
                          etiqueta_predicha="Rayadito", confianza=0.9,
                          dataset_name="AvesChilenas"))
        db.add(Retroalimentacion(id_retroalimentacion=7, id_prediccion=1,
                                 fue_correcta=True, procesado=False))
        db.commit()
    yield engine
    engine.dispose()


def test_pending_intent_survives_session_and_service_reconstruction(engine):
    from app.services.feedback_sync import FeedbackSyncQueue

    with Session(engine) as db:
        queue = FeedbackSyncQueue()
        item = queue.enqueue(db, 7, dataset_name="AvesChilenas",
                             storage_class="rayadito", sha256="a" * 64)
        assert item.status == "pending"
        assert item.object_key == "datasets/AvesChilenas/rayadito/feedback_7.wav"
        assert item.local_relative_path == "AvesChilenas/rayadito/feedback_7.wav"
        assert item.class_label == "Rayadito"
        assert db.get(Retroalimentacion, 7).procesado is False
        with pytest.raises(FrozenInstanceError):
            item.dataset_name = "Other"
        db.commit()
    with Session(engine) as db:
        queue = FeedbackSyncQueue()
        assert queue.get(db, 7) == item
        assert queue.pending(db) == [item]
        assert queue.get(db, 999) is None


def test_exact_duplicates_reuse_identity_and_conflicts_leave_it_unchanged(engine):
    from app.services.feedback_sync import FeedbackSyncQueue

    queue = FeedbackSyncQueue()
    identity = dict(dataset_name="AvesChilenas", storage_class="rayadito", sha256="a" * 64)
    with Session(engine) as db:
        original = queue.enqueue(db, 7, **identity)
        assert queue.enqueue(db, 7, **identity) == original
        for field, value in (("dataset_name", "Other"), ("storage_class", "chucao"),
                             ("sha256", "b" * 64)):
            with pytest.raises(ValueError):
                queue.enqueue(db, 7, **{**identity, field: value})
        assert queue.pending(db) == [original]
        db.get(Retroalimentacion, 7).procesado = True
        db.flush()
        db.rollback()
    with Session(engine) as db:
        assert queue.pending(db) == []
        assert db.get(Retroalimentacion, 7).procesado is False


@pytest.mark.parametrize("field,value", [
    ("dataset_name", "Other"), ("dataset_name", "../AvesChilenas"),
    ("storage_class", "a/b"), ("storage_class", "a\\\\b"),
    ("storage_class", ".."), ("storage_class", ""),
    ("storage_class", " class"), ("storage_class", "a\n"),
    ("storage_class", "a" * 101), ("sha256", "x" * 64),
    ("sha256", "a" * 63),
])
def test_invalid_identity_is_rejected_without_recording(engine, field, value):
    from app.services.feedback_sync import FeedbackSyncQueue

    with Session(engine) as db:
        queue = FeedbackSyncQueue()
        identity = dict(dataset_name="AvesChilenas", storage_class="rayadito", sha256="a" * 64)
        with pytest.raises(ValueError):
            queue.enqueue(db, 7, **{**identity, field: value})
        assert queue.pending(db) == []


def test_outcomes_persist_without_changing_identity_or_committing_feedback(engine):
    from app.services.feedback_sync import FeedbackSyncQueue

    queue = FeedbackSyncQueue()
    with Session(engine) as db:
        original = queue.enqueue(db, 7, dataset_name="AvesChilenas",
                                 storage_class="rayadito", sha256="a" * 64)
        db.get(Retroalimentacion, 7).procesado = True
        db.commit()
    with Session(engine) as db:
        failed = queue.mark_outcome(db, 7, success=False, error_code="upload_failed")
        assert (failed.status, failed.attempts, failed.error_code) == ("pending", 1, "upload_failed")
        db.commit()
    with Session(engine) as db:
        assert FeedbackSyncQueue().pending(db) == [failed]
        with pytest.raises(ValueError):
            queue.mark_outcome(db, 7, success=False, error_code="secret URL /token")
        synced = queue.mark_outcome(db, 7, success=True)
        assert (synced.status, synced.attempts, synced.error_code) == ("synced", 2, None)
        assert synced.object_key == original.object_key
        assert synced.sha256 == original.sha256
        assert queue.pending(db) == []
        db.rollback()
    with Session(engine) as db:
        assert queue.get(db, 7) == failed
        synced = queue.mark_outcome(db, 7, success=True)
        db.commit()
    with Session(engine) as db:
        assert queue.get(db, 7) == synced
        assert queue.mark_outcome(db, 7, success=True) == synced
        with pytest.raises(ValueError):
            queue.mark_outcome(db, 7, success=False, error_code="upload_failed")
        assert db.get(Retroalimentacion, 7).procesado is True
        assert queue.enqueue(db, 7, dataset_name="AvesChilenas",
                             storage_class="rayadito", sha256="a" * 64) == synced


def test_corrected_unicode_label_and_directory_are_pinned(engine):
    from app.services.feedback_sync import FeedbackSyncQueue

    with Session(engine) as db:
        feedback = db.get(Retroalimentacion, 7)
        feedback.fue_correcta = False
        feedback.etiqueta_corregida = "Churrín de la Mocha"
        queue = FeedbackSyncQueue()
        item = queue.enqueue(db, 7, dataset_name="AvesChilenas",
                             storage_class="churrín_de_la_mocha", sha256="a" * 64)
        assert item.class_label == "Churrín de la Mocha"
        assert item.object_key == "datasets/AvesChilenas/churrín_de_la_mocha/feedback_7.wav"
        feedback.etiqueta_corregida = "Other"
        with pytest.raises(ValueError, match="Conflicting"):
            queue.enqueue(db, 7, dataset_name="AvesChilenas",
                          storage_class="churrín_de_la_mocha", sha256="a" * 64)
        assert queue.get(db, 7) == item


@pytest.mark.parametrize("feedback_id", [True, "007", -1])
def test_feedback_identity_must_be_a_positive_integer(engine, feedback_id):
    from app.services.feedback_sync import FeedbackSyncQueue

    with Session(engine) as db, pytest.raises(ValueError):
        FeedbackSyncQueue().enqueue(db, feedback_id, dataset_name="AvesChilenas",
                                    storage_class="rayadito", sha256="a" * 64)


def test_missing_feedback_cannot_be_enqueued(engine):
    from app.services.feedback_sync import FeedbackSyncQueue

    with Session(engine) as db, pytest.raises(ValueError, match="Feedback not found"):
        FeedbackSyncQueue().enqueue(db, 999, dataset_name="AvesChilenas",
                                    storage_class="rayadito", sha256="a" * 64)
    with Session(engine) as db, pytest.raises(ValueError, match="intent not found"):
        FeedbackSyncQueue().mark_outcome(db, 999, success=True)
