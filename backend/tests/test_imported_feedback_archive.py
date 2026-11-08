"""Archival rejects new feedback admission, not durable approval replay (S2-S4)."""
import pytest
from fastapi import HTTPException
from tests.test_imported_feedback_growth import workflow
from tests.test_imported_feedback_api import client, test_db, fake_gcs, owners, private_prediction


def test_new_feedback_approval_rejects_archived_dataset_without_growth(workflow):
    from app.services.dataset_import_archive import archive
    from app.models.dataset_import_metadata import DatasetSummary
    from app.services.feedback_sync import FeedbackSyncQueue
    w = workflow
    archive(w.imports, w.db, 7, w.dataset_id, 0)
    before = w.imports.dataset_page(w.db, 7, w.dataset_id)
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, w.fb.id_retroalimentacion, owner_id=7)
    assert error.value.status_code == 409
    assert w.imports.dataset_page(w.db, 7, w.dataset_id) == before
    summary = w.db.get(DatasetSummary, w.dataset_id)
    assert (summary.revision, summary.file_count, summary.total_size_bytes) == (0, 0, 0)
    assert FeedbackSyncQueue().get(w.db, w.fb.id_retroalimentacion) is None
    assert w.calls == []
    assert not list((w.root / 'imports' / 'objects').rglob('*.wav'))


def test_http_feedback_approval_after_archive_preserves_membership(
        client, test_db, fake_gcs, owners, private_prediction, tmp_path, monkeypatch):
    from app.models.dataset_import import ImportedDataset
    from app.models.dataset_import_metadata import DatasetSummary
    from app.routes.dataset_imports import get_import_service
    from app.services.dataset_imports import DatasetImports
    from app.services.feedback import feedback_service
    from app.services.feedback_sync import FeedbackSyncQueue
    from scripts.migrate_dataset_import_jobs import migrate_jobs
    dataset_id = 'a' * 32
    test_db.add(ImportedDataset(id=dataset_id, owner_id=1, name='Synthetic', revision=0))
    test_db.add(DatasetSummary(dataset_id=dataset_id, revision=0, file_count=0,
                              class_count=0, total_size_bytes=0))
    test_db.commit()
    migrate_jobs(test_db.get_bind(), writers_stopped=True)
    service = DatasetImports(tmp_path / 'imports')
    monkeypatch.setattr(feedback_service, 'import_root', service.root)
    client.app.dependency_overrides[get_import_service] = lambda: service
    try:
        recorded = client.post('/api/feedback', headers=owners[1], json={
            'id_prediccion': private_prediction, 'fue_correcta': True})
        assert recorded.status_code == 201, recorded.text
        feedback_id = recorded.json()['id_retroalimentacion']
        url = f'/api/ingestion/imports/datasets/{dataset_id}'
        before = client.get(url + '/files', headers=owners[1]).json()
        assert client.request('DELETE', url, headers=owners[1], json={'revision': 0}).status_code == 204
        approved = client.post(f'/api/feedback/{feedback_id}/approve', headers=owners[1])
        assert approved.status_code == 409, approved.text
        assert client.get(url + '/files', headers=owners[1]).json() == before
        test_db.expire_all()
        summary = test_db.get(DatasetSummary, dataset_id)
        assert (summary.revision, summary.file_count, summary.total_size_bytes) == (0, 0, 0)
        assert FeedbackSyncQueue().get(test_db, feedback_id) is None
        assert not list(service.root.rglob('*.wav'))
    finally:
        client.app.dependency_overrides.pop(get_import_service, None)


def test_approved_feedback_replay_survives_archival(workflow):
    from app.services.dataset_import_archive import archive
    w = workflow
    approved = w.service.approve_feedback(w.db, w.fb.id_retroalimentacion, owner_id=7)
    archive(w.imports, w.db, 7, w.dataset_id, 1)
    assert w.service.approve_feedback(w.db, w.fb.id_retroalimentacion, owner_id=7) == approved
    assert len(w.calls) == 1
