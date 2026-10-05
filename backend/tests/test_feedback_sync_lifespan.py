"""Functional lifespan tests: fake startup dependencies, real owned runner."""
import asyncio
import threading

from tests.test_feedback_sync_worker import workflow, snapshot


def test_application_lifespan_recovers_without_blocking_and_awaits_inflight(workflow, monkeypatch):
    from app import main, database
    from app.services import auth
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    startup = []

    def upload(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        finished.set()
        return True

    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir, uploader=upload)
    monkeypatch.setattr(main.ensemble_service, 'load_models', lambda: startup.append('models'))
    monkeypatch.setattr(database, 'SessionLocal', w.sessions)
    monkeypatch.setattr(auth, 'seed_initial_admin', lambda db: startup.append('seed'))
    # Runtime construction seam; no cloud or model startup in tests.
    monkeypatch.setattr(main, 'FeedbackSyncWorker', lambda *a, **k: worker, raising=False)

    async def scenario():
        context = main.lifespan(main.app)
        await asyncio.wait_for(context.__aenter__(), timeout=1)
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(.01)
        assert entered.is_set(), 'Startup must launch an immediate recovery pass'
        assert startup == ['models', 'seed']
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        await asyncio.sleep(.02)
        assert worker.stopping.is_set()
        assert not closing.done(), 'Shutdown must own and await in-flight work'
        release.set()
        await asyncio.wait_for(closing, timeout=2)
        assert finished.is_set()
        assert snapshot(w).status == 'synced'

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_loop_surfaces_sanitized_database_failure_then_recovers(workflow, caplog):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    calls = []
    uploaded = threading.Event()

    def sessions():
        calls.append(1)
        if len(calls) == 1:
            raise OSError('private database connection string')
        return w.sessions()

    worker = FeedbackSyncWorker(sessions, w.service.raw_data_dir,
                                uploader=lambda *a, **k: uploaded.set() or True)

    async def scenario():
        async with worker.running(interval=.01):
            for _ in range(100):
                if uploaded.is_set():
                    break
                await asyncio.sleep(.01)
            assert uploaded.is_set()
        count = len(calls)
        await asyncio.sleep(.03)
        assert len(calls) == count
        assert worker.run_once()['attempted'] == 0

    asyncio.run(scenario())
    assert 'database_or_local_unavailable' in caplog.text
    assert 'private database' not in caplog.text
    assert snapshot(w).status == 'synced'


def test_periodic_cloud_failures_retry_until_shutdown_without_new_attempts(workflow):
    from app.services.feedback_sync_worker import FeedbackSyncWorker
    w = workflow
    attempts = []

    def upload(*a, **k):
        attempts.append(1)
        raise TimeoutError('private cloud error')

    worker = FeedbackSyncWorker(w.sessions, w.service.raw_data_dir, uploader=upload)

    async def scenario():
        async with worker.running(interval=.01):
            for _ in range(100):
                if len(attempts) >= 2:
                    break
                await asyncio.sleep(.01)
            assert len(attempts) >= 2
        count = len(attempts)
        await asyncio.sleep(.04)
        assert len(attempts) == count
        assert snapshot(w).status == 'pending'
        assert snapshot(w).error_code == 'upload_failed'
        assert snapshot(w).attempts == count

    asyncio.run(scenario())
