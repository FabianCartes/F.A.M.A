"""Reduced soft budgets at public ASGI seams, with controlled fake workers."""
import asyncio
import json
from threading import Event
from types import SimpleNamespace

import pytest
from starlette import formparsers

import app.main as main
from tests.test_api_feedback import test_db
from tests.test_inference_execution import external_adapters, ASGIClient, AUDIO
from tests.test_inference_input_limits import raw_request, multipart, request_body
from tests.test_inference_storage_timing import stage_events
from app.services import storage
from app.models.prediction import Prediccion


def test_partial_multipart_budget_returns_single_504_and_closes_spool(external_adapters, monkeypatch):
    monkeypatch.setattr(main, "INFERENCE_WAIT_SECONDS", .05, raising=False)
    spools = []
    original = formparsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        file = original(*args, **kwargs)
        spools.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool)
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)

    async def scenario():
        reads = 0

        async def stall_second():
            nonlocal reads
            reads += 1
            if reads == 2:
                await asyncio.Event().wait()

        chunks = [{"type": "http.request", "body": multipart(AUDIO)[:-12], "more_body": True}]
        status, response, _ = await asyncio.wait_for(
            raw_request(chunks, [(b"origin", b"http://frontend")], before_receive=stall_second), .5)
        assert status == 504
        assert "detail" in response
        assert spools and all(file.closed for file in spools)
        assert (await raw_request(request_body(AUDIO)))[0] == 200

    try:
        asyncio.run(scenario())
    finally:
        for file in spools:
            file.close()


@pytest.mark.parametrize("stage", ["validation", "upload", "predict"])
def test_budget_keeps_actual_worker_busy_until_finish(external_adapters, test_db, monkeypatch, caplog, stage):
    monkeypatch.setattr(main, "INFERENCE_WAIT_SECONDS", .1)
    caplog.set_level("INFO", logger="app.services.inference_execution")
    started, release = Event(), Event()
    calls = []
    original_validation = main.validate_audio
    paths = []

    def hold():
        started.set()
        assert release.wait(5), "test watchdog"

    def validate(data):
        if stage == "validation": hold()
        return original_validation(data)

    class Client:
        def bucket(self, name): return self
        def blob(self, key): return self
        def upload_from_string(self, data, **kwargs):
            calls.append("upload")
            if stage == "upload": hold()

    def predict(path):
        calls.append("predict")
        if stage == "predict":
            paths.append(path)
            hold()
            assert path.read_bytes() == AUDIO
        return SimpleNamespace(clase="Chucao", confianza=.9)

    monkeypatch.setattr(main, "validate_audio", validate)
    monkeypatch.setattr(storage.storage, "Client", Client)
    monkeypatch.setattr(main, "upload_audio_to_gcp", storage.upload_audio_to_gcp)
    external_adapters.predict = predict

    async def scenario():
        task = asyncio.create_task(raw_request(request_body(AUDIO), [(b"origin", b"http://frontend")]))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            status, _, _ = await asyncio.wait_for(task, 1)
            assert status == 504
            assert (await ASGIClient().get("/health")).status_code == 200
            assert (await raw_request([]))[0] == 503
            assert test_db.query(Prediccion).count() == 0
            assert not any(event["stage"] == stage for event in stage_events(caplog))
            total = [event for event in stage_events(caplog) if event["stage"] == "total"]
            assert len(total) == 1 and total[0]["outcome"] == "timeout"
            assert total[0]["worker_finished"] is False
            if paths: assert paths[0].exists()
        finally:
            release.set()
            await task

    asyncio.run(scenario())
    assert calls == {"validation": [], "upload": ["upload"], "predict": ["upload", "predict"]}[stage]
    assert test_db.query(Prediccion).count() == 0
    assert all(not path.exists() for path in paths)
    finished = [event for event in stage_events(caplog) if event["stage"] == stage]
    assert len(finished) == 1 and finished[0]["worker_finished"] is True
    assert asyncio.run(raw_request(request_body(AUDIO)))[0] == 200


def test_external_cancellation_is_not_converted_to_504(external_adapters, monkeypatch):
    monkeypatch.setattr(main, "INFERENCE_WAIT_SECONDS", .5)
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)

    async def scenario():
        reading = asyncio.Event()

        async def stall():
            reading.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(raw_request([], before_receive=stall))
        await reading.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert (await raw_request(request_body(AUDIO)))[0] == 200

    asyncio.run(scenario())


def test_expiry_after_headers_never_starts_a_second_response():
    from app.middleware.inference_limits import InferenceLimits
    from app.services.inference_execution import InferenceExecution
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"partial", "more_body": True})
        await asyncio.Event().wait()

    async def send(message): messages.append(message)
    async def receive(): return {"type": "http.disconnect"}

    middleware = InferenceLimits(app, InferenceExecution(), lambda: 100, wait_seconds=lambda: .01)
    scope = {"type": "http", "method": "POST", "path": "/api/predict"}
    with pytest.raises(TimeoutError):
        asyncio.run(middleware(scope, receive, send))
    assert [m["status"] for m in messages if m["type"] == "http.response.start"] == [200]


def test_other_routes_have_no_inference_budget():
    from app.middleware.inference_limits import InferenceLimits
    from app.services.inference_execution import InferenceExecution
    messages = []

    async def app(scope, receive, send):
        await asyncio.sleep(.02)
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def send(message): messages.append(message)
    async def receive(): return {"type": "http.disconnect"}

    middleware = InferenceLimits(app, InferenceExecution(), lambda: 100, wait_seconds=lambda: .001)
    asyncio.run(middleware({"type": "http", "method": "GET", "path": "/health"}, receive, send))
    assert messages[0]["status"] == 200
