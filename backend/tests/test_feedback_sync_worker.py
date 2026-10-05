"""Synchronization via owned sessions and real local approval; cloud is fake."""
import io
import wave
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Prediccion
from app.services.feedback import FeedbackService
from app.services.feedback_sync import FeedbackSyncQueue
from app.services import storage


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    service = FeedbackService(tmp_path / 'raw')
    (service.raw_data_dir / 'AvesChilenas/rayadito').mkdir(parents=True)
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\x01\x00' * 80)
    audio = stream.getvalue()
    monkeypatch.setattr(storage, 'download_prediction_audio', lambda source: audio)
    with sessions() as db:
        pred = Prediccion(ruta_audio_prueba='raw_audios/' + 'a' * 32 + '.wav',
                          etiqueta_predicha='Rayadito', dataset_name='AvesChilenas', confianza=.9)
        db.add(pred)
        db.commit()
        fb = service.record_feedback(db, pred.id_prediccion, True)
        service.approve_feedback(db, fb.id_retroalimentacion)
    yield SimpleNamespace(engine=engine, sessions=sessions, service=service, audio=audio,
                          path=service.raw_data_dir / 'AvesChilenas/rayadito/feedback_1.wav')
    engine.dispose()


def snapshot(w):
    with w.sessions() as db:
        return FeedbackSyncQueue().get(db, 1)


def test_acknowledged_upload_is_durable_and_replay_does_not_upload(workflow):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    uploaded = []

    def upload(data, filename, **kwargs):
        uploaded.append((data, filename, kwargs))
        return True

    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir, uploader=upload)
    assert worker.run_once() == {'attempted': 1, 'synced': 1, 'failed': 0}
    assert snapshot(w).status == 'synced'
    assert snapshot(w).attempts == 1
    assert uploaded == [(w.audio, 'feedback_1.wav', {
        'destination_folder': 'datasets/AvesChilenas/rayadito', 'timeout': 30})]
    assert worker.run_once()['attempted'] == 0
    with w.sessions() as db:
        assert w.service.approve_feedback(db, 1)['sync_status'] == 'synced'
    assert len(uploaded) == 1


@pytest.mark.parametrize('outcome', [False, 'exception', None])
def test_unacknowledged_upload_remains_pending_and_retries_same_key(workflow, outcome):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    keys = []

    def upload(data, filename, **kwargs):
        keys.append(kwargs['destination_folder'] + '/' + filename)
        if outcome == 'exception':
            raise OSError('secret provider message')
        return outcome

    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir, uploader=upload)
    for _ in range(2):
        assert worker.run_once() == {'attempted': 1, 'synced': 0, 'failed': 1}
    assert snapshot(w).status == 'pending'
    assert snapshot(w).error_code == 'upload_failed'
    assert snapshot(w).attempts == 2
    assert keys == ['datasets/AvesChilenas/rayadito/feedback_1.wav'] * 2
    assert w.path.read_bytes() == w.audio


@pytest.mark.parametrize('damage', [
    'hash', 'missing', 'symlink', 'external', 'object', 'dataset', 'class',
    'source', 'unprocessed', 'intent_hash', 'intent_source', 'intent_storage',
    'unmanaged_source',
])
def test_invalid_evidence_never_uploads_and_preserves_files_and_identity(workflow, damage):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    from app.models import Retroalimentacion
    from app.models.feedback_sync import FeedbackSync
    import json
    w = workflow
    if damage == 'unmanaged_source':
        intent_path = w.service.raw_data_dir / '.feedback_1.json'
        value = json.loads(intent_path.read_text())
        value['source'] = '/external/unmanaged.wav'
        intent_path.write_text(json.dumps(value))
        with w.sessions() as db:
            db.get(Retroalimentacion, 1).prediccion.ruta_audio_prueba = value['source']
            db.commit()
    elif damage == 'hash':
        w.path.write_bytes(b'corrupt')
    elif damage == 'missing':
        # Rename inside the fixture directory, without deleting original bytes.
        w.path.rename(w.path.with_suffix('.saved'))
    elif damage == 'symlink':
        saved = w.path.with_suffix('.saved')
        w.path.rename(saved)
        w.path.symlink_to(saved)
    elif damage.startswith('intent_'):
        intent_path = w.service.raw_data_dir / '.feedback_1.json'
        value = json.loads(intent_path.read_text())
        value[{'intent_hash': 'sha256', 'intent_source': 'source',
               'intent_storage': 'storage_class'}[damage]] = 'forged'
        intent_path.write_text(json.dumps(value))
    else:
        with w.sessions() as db:
            row = db.get(FeedbackSync, 1)
            fb = db.get(Retroalimentacion, 1)
            if damage == 'external':
                row.local_relative_path = str(w.path)
            elif damage == 'object':
                row.object_key = 'datasets/forged/feedback_1.wav'
            elif damage == 'dataset':
                fb.prediccion.dataset_name = 'Other'
            elif damage == 'class':
                fb.prediccion.etiqueta_predicha = 'Other'
            elif damage == 'source':
                fb.prediccion.ruta_audio_prueba = 'raw_audios/forged.wav'
            elif damage == 'unprocessed':
                fb.procesado = False
            db.commit()
    original = snapshot(w)
    uploaded = []
    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir,
                                uploader=lambda *a, **k: uploaded.append(a))
    assert worker.run_once()['failed'] == 1
    assert uploaded == []
    current = snapshot(w)
    assert current.status == 'pending'
    assert current.error_code == 'integrity_mismatch'
    assert current.sha256 == original.sha256
    assert current.object_key == original.object_key
    assert current.local_relative_path == original.local_relative_path


@pytest.mark.parametrize('ack_lost', [False, True])
def test_database_failure_does_not_report_false_synced(workflow, ack_lost):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    from sqlalchemy.orm import Session
    w = workflow
    uploads = []

    class FailingSession(Session):
        def commit(self):
            if ack_lost:
                super().commit()
            raise OSError('database ack lost')

    failing = sessionmaker(bind=w.engine, class_=FailingSession)
    upload = lambda *a, **k: uploads.append(a) or True
    with pytest.raises(OSError):
        FeedbackSyncWorker(failing, w.service.raw_data_dir, uploader=upload).run_once()
    assert snapshot(w).status == ('synced' if ack_lost else 'pending')
    result = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir, uploader=upload).run_once()
    assert result['attempted'] == (0 if ack_lost else 1)
    assert len(uploads) == (1 if ack_lost else 2)


@pytest.mark.parametrize('broken_lock', [False, True])
def test_failed_first_entry_does_not_starve_next_bounded_batch(workflow, broken_lock):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    with w.sessions() as db:
        pred = Prediccion(ruta_audio_prueba='raw_audios/' + 'b' * 32 + '.wav',
                          etiqueta_predicha='Rayadito', dataset_name='AvesChilenas', confianza=.9)
        db.add(pred)
        db.commit()
        fb = w.service.record_feedback(db, pred.id_prediccion, True)
        w.service.approve_feedback(db, fb.id_retroalimentacion)
    w.path.write_bytes(b'broken')
    if broken_lock:
        lock = w.service.raw_data_dir / '.feedback_1.json.lock'
        saved = lock.with_suffix('.saved')
        lock.rename(saved)
        lock.symlink_to(saved)
    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir,
                                uploader=lambda *a, **k: True, batch_size=1)
    if broken_lock:
        with pytest.raises(ValueError):
            worker.run_once()
    else:
        assert worker.run_once()['failed'] == 1
    assert worker.run_once()['synced'] == 1


def test_threads_skip_inflight_uploader_and_approval_replays_after_same_lock(workflow):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    entered, release = threading.Event(), threading.Event()
    uploads = []

    def upload(*args, **kwargs):
        uploads.append(args)
        entered.set()
        assert release.wait(5)
        return True

    first = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir, uploader=upload)
    second = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir, uploader=upload)

    def replay():
        with w.sessions() as db:
            return w.service.approve_feedback(db, 1)

    with ThreadPoolExecutor(max_workers=3) as threads:
        pending = threads.submit(first.run_once)
        assert entered.wait(2)
        skipped = threads.submit(second.run_once)
        assert skipped.result(timeout=2)['attempted'] == 0
        approval = threads.submit(replay)
        try:
            assert not approval.done()
        finally:
            release.set()
        assert pending.result(timeout=2)['synced'] == 1
        assert approval.result(timeout=2)['sync_status'] == 'synced'
    assert len(uploads) == 1


def _spawn_runner(database_url, raw, entered, release, results):
    """Top-level spawn target, no inherited sessions or cloud objects."""
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine)

    def upload(*args, **kwargs):
        entered.set()
        if not release.wait(8):
            raise TimeoutError('test release timeout')
        return True

    try:
        results.put(FeedbackSyncWorker(sessions, raw, uploader=upload).run_once())
    except Exception as error:
        results.put(type(error).__name__)
    finally:
        engine.dispose()


def test_spawn_processes_share_stable_feedback_lock(workflow):
    import multiprocessing
    w = workflow
    context = multiprocessing.get_context('spawn')
    entered, release, results = context.Event(), context.Event(), context.Queue()
    args = (str(w.engine.url), str(w.service.raw_data_dir), entered, release, results)
    first = context.Process(target=_spawn_runner, args=args)
    second = context.Process(target=_spawn_runner, args=args)
    first.start()
    try:
        assert entered.wait(8)
        second.start()
        skipped = results.get(timeout=8)
        assert skipped == {'attempted': 0, 'synced': 0, 'failed': 0}
    finally:
        release.set()
        first.join(timeout=10)
        if second.pid is not None:
            second.join(timeout=10)
    assert first.exitcode == second.exitcode == 0
    assert results.get(timeout=2) == {'attempted': 1, 'synced': 1, 'failed': 0}
    assert snapshot(w).attempts == 1
    results.close()
    results.join_thread()


def test_stop_during_upload_commits_ack_but_does_not_start_next_item(workflow):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    with w.sessions() as db:
        pred = Prediccion(ruta_audio_prueba='raw_audios/' + 'b' * 32 + '.wav',
                          etiqueta_predicha='Rayadito', dataset_name='AvesChilenas', confianza=.9)
        db.add(pred)
        db.commit()
        fb = w.service.record_feedback(db, pred.id_prediccion, True)
        w.service.approve_feedback(db, fb.id_retroalimentacion)

    def upload(*args, **kwargs):
        worker.stop()
        return True

    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir, uploader=upload)
    assert worker.run_once() == {'attempted': 1, 'synced': 1, 'failed': 0}
    with w.sessions() as db:
        assert FeedbackSyncQueue().get(db, 2).attempts == 0
        assert FeedbackSyncQueue().get(db, 2).status == 'pending'


def test_existing_storage_adapter_bounds_worker_upload_and_disables_sdk_retries(workflow, monkeypatch):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    sent = []

    class Client:
        def bucket(self, name):
            return self

        def blob(self, key):
            assert key == 'datasets/AvesChilenas/rayadito/feedback_1.wav'
            return self

        def upload_from_string(self, data, **kwargs):
            sent.append((data, kwargs))

    monkeypatch.setattr(storage.storage, 'Client', Client)
    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir)
    assert worker.run_once()['synced'] == 1
    assert sent == [(w.audio, {'content_type': 'audio/wav', 'timeout': 30, 'retry': None})]


def test_rotation_revisits_released_entry_despite_other_repeated_failures(workflow):
    import fcntl
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    with w.sessions() as db:
        pred = Prediccion(ruta_audio_prueba='raw_audios/' + 'b' * 32 + '.wav',
                          etiqueta_predicha='Rayadito', dataset_name='AvesChilenas', confianza=.9)
        db.add(pred)
        db.commit()
        fb = w.service.record_feedback(db, pred.id_prediccion, True)
        w.service.approve_feedback(db, fb.id_retroalimentacion)
    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir,
                                uploader=lambda *a, **k: False, batch_size=1)
    with (w.service.raw_data_dir / '.feedback_1.json.lock').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert worker.run_once()['attempted'] == 0
        assert worker.run_once()['failed'] == 1
    assert worker.run_once()['failed'] == 1
    assert snapshot(w).attempts == 1


@pytest.mark.parametrize('batch_size', [0, 501, True])
def test_runner_rejects_unbounded_batches(workflow, batch_size):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    with pytest.raises(ValueError):
        FeedbackSyncWorker(workflow.sessions, workflow.service.raw_data_dir, batch_size=batch_size)
