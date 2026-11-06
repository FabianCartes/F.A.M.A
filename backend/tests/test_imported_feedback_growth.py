"""Public local approval seam; SQLite memory and synthetic WAV only."""
import hashlib
import io
import wave
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models.prediction import Prediccion
from app.models.imported_training_source import ImportedModelSource
from app.models import training_snapshot  # register referenced immutable cohort tables
from app.models.dataset_import import ImportedDataset
from app.models.dataset_import_job import ImportJobGate
from app.models.dataset_import_metadata import DatasetSummary
from app.services.feedback import FeedbackService
from app.services.dataset_imports import DatasetImports
from app.services import storage


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\x01\x00' * 800)
    audio = stream.getvalue()
    calls = []
    def download(source):
        calls.append(source)
        return audio
    monkeypatch.setattr(storage, 'download_prediction_audio', download)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    ImportedModelSource.__table__.create(engine, checkfirst=True)
    with Session(engine) as db:
        db.add(ImportJobGate(id=1, version=1, generation=0))
        dataset_id = 'd' * 32
        db.add(ImportedDataset(id=dataset_id, owner_id=7, name='Synthetic', revision=0))
        db.add(DatasetSummary(dataset_id=dataset_id, revision=0, file_count=0,
                              class_count=0, total_size_bytes=0))
        db.add(ImportedModelSource(model_id=3, owner_id=7, dataset_id=dataset_id,
                                   snapshot_id='s' * 32, identity={}))
        pred = Prediccion(modelo_id='3', dataset_name='imported:' + dataset_id,
                          etiqueta_predicha='ants', confianza=.9,
                          ruta_audio_prueba='synthetic.wav')
        db.add(pred)
        db.commit()
        service = FeedbackService(tmp_path / 'raw', import_root=tmp_path / 'imports')
        fb = service.record_feedback(db, pred.id_prediccion, True, id_usuario=7)
        yield SimpleNamespace(db=db, dataset_id=dataset_id, pred=pred, fb=fb,
                              service=service, imports=DatasetImports(tmp_path / 'imports'),
                              audio=audio, calls=calls, root=tmp_path)
    engine.dispose()


def test_legacy_numeric_model_approval_does_not_require_imported_source_schema(workflow):
    w = workflow
    w.pred.dataset_name = 'Legacy'
    w.pred.modelo_id = '999'
    w.db.commit()
    ImportedModelSource.__table__.drop(w.db.get_bind())
    dataset = w.root / 'raw/Legacy'
    (dataset / 'ants').mkdir(parents=True)
    (dataset / 'metadata.csv').write_text('nombre_archivo,clase,file_path,file_stage\n')
    result = w.service.approve_feedback(w.db, w.fb.id_retroalimentacion)
    assert result['status'] == 'approved'
    assert result['sync_status'] == 'pending'
    assert (dataset / 'ants/feedback_1.wav').read_bytes() == w.audio


def test_accept_grows_public_catalog_with_exact_local_bytes_and_replay(workflow):
    w = workflow
    assert w.imports.list_datasets(w.db, 7)['datasets'][0]['file_count'] == 0
    result = w.service.approve_feedback(w.db, w.fb.id_retroalimentacion, owner_id=7)
    assert result['sync_status'] == 'pending'
    catalog, = w.imports.list_datasets(w.db, 7)['datasets']
    assert (catalog['revision'], catalog['file_count']) == (1, 1)
    digest = hashlib.sha256(w.audio).hexdigest()
    assert w.imports.download(w.db, 7, w.dataset_id, digest).read_bytes() == w.audio
    assert (w.root / 'raw' / ('imported:' + w.dataset_id) / 'ants/feedback_1.wav').read_bytes() == w.audio
    assert w.service.approve_feedback(w.db, 1, owner_id=7) == result
    assert len(w.calls) == 1
    assert w.imports.list_datasets(w.db, 7)['datasets'][0]['revision'] == 1
    job, = w.imports.list_jobs(w.db, 7)['imports']
    assert job['execution'] is None
    assert job['preview_token'] is None
    assert job['preview']['origin'] == dict(kind='feedback', feedback_id=1, prediction_id=1)
    assert w.imports.review_page(w.db, 7, job['id'], 'classes')['classes'] == ['ants']
    assert w.imports.dataset_page(w.db, 7, w.dataset_id)['files'][0]['sha256'] == digest


@pytest.mark.parametrize('owner', [None, 8])
def test_foreign_owner_rejected_before_download_or_filesystem(workflow, owner):
    w = workflow
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1, owner_id=owner)
    assert error.value.status_code == 404
    assert w.calls == []
    assert not (w.root / 'raw').exists()
    assert not (w.root / 'imports').exists()


@pytest.mark.parametrize('model,dataset', [('3junk', None), ('03', None), ('-3', None),
    ('999', None), ('3', 'Legacy')])
def test_unbound_imported_identity_never_falls_through_legacy(workflow, model, dataset):
    w = workflow
    w.pred.modelo_id = model
    if dataset is not None:
        w.pred.dataset_name = dataset
    w.db.commit()
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1, owner_id=7)
    assert error.value.status_code == 404
    assert not w.calls
    assert not (w.root / 'raw').exists()


def test_processed_imported_feedback_still_hides_identity_from_foreign_owner(workflow):
    w = workflow
    w.service.reject_feedback(w.db, 1)
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1, owner_id=8)
    assert error.value.status_code == 404
    assert not w.calls


def test_rejection_does_not_admit_and_cannot_be_approved(workflow):
    w = workflow
    assert w.service.reject_feedback(w.db, 1)['status'] == 'rejected'
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1, owner_id=7)
    assert error.value.status_code == 409
    assert not w.calls
    assert w.imports.list_datasets(w.db, 7)['datasets'][0]['revision'] == 0


def test_imported_admission_preserves_existing_dataset_quota(workflow, monkeypatch):
    w = workflow
    monkeypatch.setenv('FAMA_IMPORT_DATASET_BYTES', '1')
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1, owner_id=7)
    assert error.value.status_code == 409
    assert w.imports.list_datasets(w.db, 7)['datasets'][0]['revision'] == 0
    assert not list((w.root / 'imports/objects').iterdir())


def test_failed_commit_retry_retains_verified_objects_without_redownload(workflow, monkeypatch):
    w = workflow
    commit = w.db.commit
    def fail():
        raise RuntimeError('synthetic commit fault')
    monkeypatch.setattr(w.db, 'commit', fail)
    with pytest.raises(HTTPException) as error:
        w.service.approve_feedback(w.db, 1, owner_id=7)
    assert error.value.status_code == 503
    assert w.imports.list_datasets(w.db, 7)['datasets'][0]['revision'] == 0
    monkeypatch.setattr(w.db, 'commit', commit)
    assert w.service.approve_feedback(w.db, 1, owner_id=7)['status'] == 'approved'
    assert len(w.calls) == 1
    assert w.imports.list_datasets(w.db, 7)['datasets'][0]['file_count'] == 1
