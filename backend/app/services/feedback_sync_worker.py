"""Verified local-to-cloud synchronization with owned transactions and lifecycle."""
import asyncio
from contextlib import asynccontextmanager
import fcntl
import hashlib
import json
import logging
import os
import re
from pathlib import Path
import threading

from app.models.feedback import Retroalimentacion
from app.models.feedback_sync import FeedbackSync
from app.services.feedback import FeedbackService
from app.services.feedback_sync import FeedbackSyncQueue, _snapshot, _validate_component
from app.services.storage import upload_audio_to_gcp_sync

logger = logging.getLogger(__name__)


class FeedbackSyncWorker:
    """run_once owns sessions; stop prevents new attempts, not an in-flight ack.

    All cooperating writers lock feedback row -> stable filesystem inode -> sync
    row. SQLite relies on the same filesystem inode used by approval. Cloud IO
    uses captured verified bytes, never a pathname reopened by the adapter.
    """

    def __init__(self, session_factory, raw_data_dir, *, uploader=upload_audio_to_gcp_sync,
                 batch_size=50, upload_timeout=30):
        if type(batch_size) is not int or not 1 <= batch_size <= 500:
            raise ValueError('Batch size must be between 1 and 500')
        if not 0 < upload_timeout <= 60:
            raise ValueError('Upload timeout must be between 0 and 60 seconds')
        self.sessions = session_factory
        self.local = FeedbackService(Path(raw_data_dir))
        self.uploader = uploader
        self.batch_size = batch_size
        self.upload_timeout = upload_timeout
        self.stopping = threading.Event()
        self._cursor = None

    def stop(self):
        self.stopping.set()

    def _verified_bytes(self, feedback, intent):
        pred = feedback.prediccion
        label = pred.etiqueta_predicha if feedback.fue_correcta else feedback.etiqueta_corregida
        for component in (intent.dataset_name, intent.storage_class, intent.class_label):
            _validate_component(component)
        filename = f'feedback_{intent.id_retroalimentacion}.wav'
        relative = f'{intent.dataset_name}/{intent.storage_class}/{filename}'
        if (not re.fullmatch(r'raw_audios/[0-9a-f]{32}\.wav', pred.ruta_audio_prueba or '')
                or not feedback.procesado or pred.dataset_name != intent.dataset_name
                or label != intent.class_label or intent.local_relative_path != relative
                or intent.object_key != f'datasets/{relative}'):
            raise ValueError('Inconsistent synchronization identity')
        path = self.local.raw_data_dir / relative
        intent_path = self.local._intent_path(intent.id_retroalimentacion)
        self.local._safe_path(path)
        self.local._safe_path(intent_path)
        recorded = json.loads(intent_path.read_text(encoding='utf-8'))
        expected = dict(dataset=intent.dataset_name, **{'class': label},
                        source=pred.ruta_audio_prueba, storage_class=intent.storage_class,
                        filename=filename, sha256=intent.sha256)
        if any(recorded.get(key) != value for key, value in expected.items()):
            raise ValueError('Inconsistent local intent')
        data = path.read_bytes()
        if not data or hashlib.sha256(data).hexdigest() != intent.sha256:
            raise ValueError('Local integrity mismatch')
        return data

    def run_once(self):
        result = dict(attempted=0, synced=0, failed=0)
        queue = FeedbackSyncQueue()
        with self.sessions() as db:
            query = db.query(FeedbackSync).filter_by(status='pending').order_by(
                FeedbackSync.id_retroalimentacion)
            page = query
            if self._cursor is not None:
                page = query.filter(FeedbackSync.id_retroalimentacion > self._cursor)
            rows = page.limit(self.batch_size).all()
            if not rows and self._cursor is not None:
                rows = query.limit(self.batch_size).all()
            candidates = [_snapshot(row) for row in rows]
        for candidate in candidates:
            if self.stopping.is_set():
                break
            # Advance even when a lock is unsafe/busy or its commit fails. These
            # cannot safely increment durable attempts; keyset rotation still
            # prevents a broken first entry from starving later bounded batches.
            self._cursor = candidate.id_retroalimentacion
            with self.sessions() as db:
                feedback = db.query(Retroalimentacion).filter_by(
                    id_retroalimentacion=candidate.id_retroalimentacion
                ).with_for_update(skip_locked=True).first()
                if feedback is None:
                    continue
                lock = self.local._intent_path(candidate.id_retroalimentacion).with_suffix('.json.lock')
                self.local._safe_path(lock)
                descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
                try:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    db.refresh(feedback)
                    row = db.query(FeedbackSync).filter_by(
                        id_retroalimentacion=candidate.id_retroalimentacion
                    ).with_for_update(skip_locked=True).populate_existing().first()
                    if row is None or row.status != 'pending' or self.stopping.is_set():
                        continue
                    intent = _snapshot(row)
                    error = None
                    try:
                        data = self._verified_bytes(feedback, intent)
                    except (ValueError, OSError, KeyError, TypeError, AttributeError):
                        error = 'integrity_mismatch'
                    if error is None:
                        if self.stopping.is_set():
                            break
                        try:
                            acknowledged = self.uploader(
                                data, f'feedback_{intent.id_retroalimentacion}.wav',
                                destination_folder=intent.object_key.rsplit('/', 1)[0],
                                timeout=self.upload_timeout)
                            if acknowledged is not True:
                                error = 'upload_failed'
                        except Exception:
                            error = 'upload_failed'
                    queue.mark_outcome(db, intent.id_retroalimentacion,
                                       success=error is None, error_code=error)
                    # A failed/indeterminate commit propagates; never report synced
                    # based solely on the external upload. Retry uses the same key.
                    db.commit()
                    result['attempted'] += 1
                    result['synced' if error is None else 'failed'] += 1
                finally:
                    os.close(descriptor)
        return result

    @asynccontextmanager
    async def running(self, *, interval=60):
        """Immediate recovery off the serving thread, bounded periodic passes.

        Shutdown signals first and awaits the owned loop and its thread; there
        is no cancellation masquerading as termination of to_thread work.
        """
        if not 0 < interval <= 3600:
            raise ValueError('Retry interval must be between 0 and 3600 seconds')
        wake = asyncio.Event()

        async def loop():
            while not self.stopping.is_set():
                try:
                    await asyncio.to_thread(self.run_once)
                except Exception:
                    logger.warning('Feedback synchronization pass failed: database_or_local_unavailable')
                if self.stopping.is_set():
                    break
                try:
                    await asyncio.wait_for(wake.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(loop(), name='feedback-sync')
        try:
            yield self
        finally:
            self.stop()
            wake.set()
            await task
