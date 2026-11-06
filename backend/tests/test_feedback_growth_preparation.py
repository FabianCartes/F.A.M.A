"""Reviewed feedback growth through public services and a new frozen preparation."""
import pytest
from fastapi import HTTPException

from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create
from tests.test_dataset_zip_validation import wav_bytes
from app.models.imported_training_source import ImportedModelSource
from app.models.training import Modelo
from app.models.prediction import Prediccion
from app.services.feedback import FeedbackService
from app.services.feedback_sync import FeedbackSyncQueue
from app.services.imported_training_source import ImportedTrainingSource, ImportedSourceError
from training.imported_dataset_preparation import ImportedDatasetPreparation, PreparationError


def test_reviewed_audio_grows_dataset_then_requires_new_provenance_and_partitions(cohort, tmp_path, monkeypatch):
    snapshots, old_snapshot, old_mapping, profile, _, dataset_id = cohort
    preparations = ImportedDatasetPreparation(snapshots, tmp_path / 'prepared-feedback')
    old_prepared = create(preparations, cohort)
    sources = ImportedTrainingSource(preparations)
    old_source = sources.resolve_for_training(1, dataset_id, old_snapshot['id'],
                                             old_prepared['version_id'], architecture='AudioCNN')
    before_members = list(snapshots.iter_verified(1, old_snapshot['id']))
    audio = wav_bytes(73)
    monkeypatch.setattr('app.services.storage.download_prediction_audio', lambda _: audio)
    service = FeedbackService(tmp_path / 'feedback-raw', import_root=snapshots.source.root)
    with snapshots.sessions() as db:
        model = Modelo(arquitectura='AudioCNN', epocas=1, tasa_aprendizaje=.001,
                       tamano_lote=1, ruta_binario_gcp='synthetic-local.pt')
        db.add(model)
        db.flush()
        db.add(ImportedModelSource(model_id=model.id_modelo, owner_id=1, dataset_id=dataset_id,
                                   snapshot_id=old_snapshot['id'], identity=old_source['identity']))
        pred = Prediccion(modelo_id=str(model.id_modelo), dataset_name='imported:' + dataset_id,
                          etiqueta_predicha='ants', confianza=.9, ruta_audio_prueba='synthetic-feedback.wav')
        db.add(pred)
        db.commit()
        feedback = service.record_feedback(db, pred.id_prediccion, False,
                                           etiqueta_corregida='zebra', id_usuario=1)
        assert snapshots.source.list_datasets(db, 1)['datasets'][0]['file_count'] == 6
        assert len(service.get_pending_feedback(db)) == 1
        accepted = service.approve_feedback(db, feedback.id_retroalimentacion, owner_id=1)
        assert accepted['local_status'] == 'incorporated'
        assert accepted['sync_status'] == 'pending'
        assert FeedbackSyncQueue().get(db, feedback.id_retroalimentacion).class_label == 'zebra'
        current, = snapshots.source.list_datasets(db, 1)['datasets']
        assert current['file_count'] == 7
        assert current['revision'] == old_snapshot['dataset_revision'] + 1
        assert service.get_pending_feedback(db) == []
    assert list(snapshots.iter_verified(1, old_snapshot['id'])) == before_members
    assert preparations.get(1, old_snapshot['id'], old_prepared['version_id']) == old_prepared
    assert sources.resolve(1, dataset_id, old_snapshot['id'], old_prepared['version_id'],
                           architecture='AudioCNN') == old_source
    with pytest.raises(ImportedSourceError) as stale:
        sources.resolve_for_training(1, dataset_id, old_snapshot['id'], old_prepared['version_id'],
                                     architecture='AudioCNN')
    assert stale.value.code == 'preparation_stale'
    latest = snapshots.create(1, dataset_id)
    latest_members = {m['member_id']: m for m, _ in snapshots.iter_verified(1, latest['id'])}
    added = set(latest_members) - {m['member_id'] for m, _ in before_members}
    assert len(added) == 1
    member_id = added.pop()
    assert latest_members[member_id]['class_name'] == 'zebra'
    assert latest_members[member_id]['size_bytes'] == len(audio)
    with pytest.raises(PreparationError) as incomplete:
        preparations.create(1, latest['id'], mapping=old_mapping, profile=profile,
                            provenance={'source': 'synthetic known recording origins'}, seed=42)
    assert incomplete.value.code == 'invalid_mapping'
    mapping = old_mapping + [dict(member_id=member_id, recording_id='known-new-recording-7',
                                  group_id='known-new-group-7')]
    prepared = preparations.create(1, latest['id'], mapping=mapping, profile=profile,
                                   provenance={'source': 'synthetic known recording origins'}, seed=42)
    admitted = sources.resolve_for_training(1, dataset_id, latest['id'], prepared['version_id'],
                                           architecture='AudioCNN')
    split_ids = [{row['member_id'] for row in admitted['splits'][split]} for split in ('train', 'val', 'test')]
    assert set.union(*split_ids) == set(latest_members)
    assert not any(split_ids[a] & split_ids[b] for a, b in ((0, 1), (0, 2), (1, 2)))
    split_groups = [{row['group_id'] for row in admitted['splits'][split]} for split in ('train', 'val', 'test')]
    assert not any(split_groups[a] & split_groups[b] for a, b in ((0, 1), (0, 2), (1, 2)))
    assert preparations.get(1, old_snapshot['id'], old_prepared['version_id']) == old_prepared
