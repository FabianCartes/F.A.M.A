"""Read-only synchronization HTTP contract, without application startup."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.test_feedback_sync_worker import workflow


def test_recent_accepted_states_are_bounded_read_only_and_separate_from_curation(workflow):
    from app.main import app
    from app.database import get_db
    from app.models import Prediccion
    from app.services.feedback_sync import FeedbackSyncQueue
    w = workflow
    with w.sessions() as db:
        pred = Prediccion(ruta_audio_prueba='raw_audios/' + 'b' * 32 + '.wav',
                          etiqueta_predicha='Rayadito', dataset_name='AvesChilenas', confianza=.9)
        db.add(pred)
        db.commit()
        fb = w.service.record_feedback(db, pred.id_prediccion, True)
        w.service.approve_feedback(db, fb.id_retroalimentacion)
        FeedbackSyncQueue().mark_outcome(db, 1, success=False, error_code='upload_failed')
        FeedbackSyncQueue().mark_outcome(db, 2, success=True)
        db.commit()
        # Uncurated feedback must remain in its original queue, not sync states.
        pred = Prediccion(ruta_audio_prueba='raw_audios/' + 'c' * 32 + '.wav',
                          etiqueta_predicha='Rayadito', dataset_name='AvesChilenas', confianza=.9)
        db.add(pred)
        db.commit()
        w.service.record_feedback(db, pred.id_prediccion, True)

    def database():
        with w.sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    try:
        response = client.get('/api/feedback/sync?limit=1')
        assert response.status_code == 200
        assert response.json() == [{
            'id_retroalimentacion': 2, 'id_prediccion': 2,
            'dataset_name': 'AvesChilenas', 'storage_class': 'rayadito',
            'class_label': 'Rayadito', 'local_status': 'incorporated',
            'sync_status': 'synced', 'attempts': 1, 'error_code': None,
        }]
        recent = client.get('/api/feedback/sync').json()
        assert [item['id_retroalimentacion'] for item in recent] == [2, 1]
        assert recent[1]['sync_status'] == 'pending'
        assert recent[1]['error_code'] == 'upload_failed'
        assert recent[1]['attempts'] == 1
        assert len(client.get('/api/feedback/pending').json()) == 1
        for limit in ('0', '501', '-1', 'bad'):
            assert client.get('/api/feedback/sync?limit=' + limit).status_code == 422
        assert client.post('/api/feedback/sync').status_code == 405
        with w.sessions() as db:
            assert FeedbackSyncQueue().get(db, 1).attempts == 1
        schema = client.get('/openapi.json').json()['components']['schemas']['FeedbackSyncState']
        assert set(schema['required']) == {
            'id_retroalimentacion', 'id_prediccion', 'dataset_name', 'storage_class',
            'class_label', 'local_status', 'sync_status', 'attempts', 'error_code',
        }
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)


def test_sync_schema_rejects_false_milestones_and_provider_messages():
    from app.schemas.feedback import FeedbackSyncState
    valid = dict(id_retroalimentacion=1, id_prediccion=1, dataset_name='AvesChilenas',
                 storage_class='rayadito', class_label='Rayadito',
                 local_status='incorporated', sync_status='pending', attempts=1,
                 error_code='upload_failed')
    assert FeedbackSyncState(**valid).sync_status == 'pending'
    for field, value in [('local_status', 'pending'), ('sync_status', 'failed'),
                         ('error_code', 'private provider message'), ('attempts', -1)]:
        with pytest.raises(ValidationError):
            FeedbackSyncState(**{**valid, field: value})
