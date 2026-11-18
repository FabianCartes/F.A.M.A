"""Descriptive read-only feedback states through the public HTTP interface."""
import pytest

from tests.test_api_feedback import client, test_db, fake_gcs  # noqa: F401  (fixtures)


def accept_intent(db, prediction_id, dataset_name):
    from app.models.feedback import Retroalimentacion
    from app.services.feedback_sync import FeedbackSyncQueue
    feedback = Retroalimentacion(id_prediccion=prediction_id, id_usuario=1,
                                 fue_correcta=True, procesado=True)
    db.add(feedback)
    db.flush()
    intent = FeedbackSyncQueue().enqueue(db, feedback.id_retroalimentacion,
        dataset_name=dataset_name, storage_class="reviewed", sha256="a" * 64)
    db.commit()
    return intent


def test_shared_record_exposes_original_and_actual_incorporated_names_without_writes(client, test_db):
    from app.models.prediction import Prediccion
    from app.services.feedback_sync import FeedbackSyncQueue
    prediction = Prediccion(ruta_audio_prueba="raw_audios/" + "c" * 32 + ".wav",
        nombre_original="canto_original.wav", etiqueta_predicha="Reviewed class",
        confianza=.9, dataset_name="AvesChilenas")
    test_db.add(prediction)
    test_db.flush()
    intent = accept_intent(test_db, prediction.id_prediccion, "AvesChilenas")
    before = FeedbackSyncQueue().get(test_db, intent.id_retroalimentacion)
    for _ in range(2):
        response = client.get("/api/feedback/sync")
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1
        row = response.json()[0]
        assert row["dataset_display_name"] == "AvesChilenas"
        assert row["audio_filename"] == "canto_original.wav"
        assert row["incorporated_filename"] == intent.local_relative_path.rsplit("/", 1)[-1]
        assert row["local_status"] == "incorporated"
        assert row["sync_status"] == "pending"
        assert row["attempts"] == 0
    assert FeedbackSyncQueue().get(test_db, intent.id_retroalimentacion) == before


def test_missing_original_name_is_not_replaced_with_a_storage_uuid(client, test_db):
    from app.models.prediction import Prediccion
    prediction = Prediccion(ruta_audio_prueba="raw_audios/" + "d" * 32 + ".wav",
        etiqueta_predicha="Reviewed class", confianza=.9, dataset_name="AvesChilenas")
    test_db.add(prediction)
    test_db.flush()
    accept_intent(test_db, prediction.id_prediccion, "AvesChilenas")
    response = client.get("/api/feedback/sync")
    assert response.status_code == 200, response.text
    assert response.json()[0]["audio_filename"] is None
    assert "d" * 32 not in response.text
