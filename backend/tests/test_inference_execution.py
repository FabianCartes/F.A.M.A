"""Public ASGI contracts with controlled predictor threads; no lifespan startup."""
import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.main as main
from tests.test_api_feedback import test_db
from tests.test_prediction_audio_metadata import synthetic_wav

AUDIO = synthetic_wav()


@pytest.fixture
def external_adapters(test_db, monkeypatch):
    monkeypatch.setattr(main, "upload_audio_to_gcp", AsyncMock(return_value=True))
    monkeypatch.setattr(main.ensemble_service, "get_status", lambda **kwargs: {})
    predictor = SimpleNamespace(
        model_id="fake", dataset_name="AvesChilenas", has_weights=True,
        metadata=SimpleNamespace(name="Synthetic inference fixture"),
    )
    main.app.dependency_overrides[main.get_model_registry] = lambda: SimpleNamespace(get=lambda _: predictor, get_default_model_id=lambda: "fake")
    from tests.http_security import administrator_http
    with administrator_http(main.app):
        yield predictor
    main.app.dependency_overrides.pop(main.get_model_registry, None)


class ASGIClient:
    async def get(self, path):
        return await self.send(path, b"", "GET")

    async def post(self, path, files):
        name, data = files["file"]
        body = (f'--test\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                'Content-Type: audio/wav\r\n\r\n').encode() + data + b"\r\n--test--\r\n"
        return await self.send(path, body, "POST")

    async def send(self, path, body, method):
        messages = []
        consumed = False

        async def receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        await main.app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
                        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                        "query_string": b"", "root_path": "", "server": ("test", 80),
                        "client": ("test", 123), "headers": [(b"content-type", b"multipart/form-data; boundary=test")]},
                       receive, send)
        start = next(message for message in messages if message["type"] == "http.response.start")
        return SimpleNamespace(status_code=start["status"],
                               headers={key.decode().lower(): value.decode() for key, value in start["headers"]})


def test_health_responsive_and_saturation_rejected(external_adapters):
    started, release, finished = Event(), Event(), Event()

    def predict(path):
        started.set()
        try:
            assert release.wait(3), "test watchdog: event loop did not respond"
            return SimpleNamespace(clase="Chucao", confianza=.9)
        finally:
            finished.set()

    external_adapters.predict = predict

    async def scenario():
        client = ASGIClient()
        request = asyncio.create_task(client.post("/api/predict", files={"file": ("a.wav", AUDIO)}))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            health = await asyncio.wait_for(client.get("/health"), 1)
            assert health.status_code == 200
            assert not finished.is_set(), "prediction blocked the event loop"
            busy = await asyncio.wait_for(client.post("/api/predict", files={"file": ("b.wav", AUDIO)}), 1)
            assert busy.status_code == 503
            assert busy.headers["retry-after"] == "5"
        finally:
            release.set()
            response = await request
        assert response.status_code == 200
        assert (await client.post("/api/predict", files={"file": ("c.wav", AUDIO)})).status_code == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("late_error", [False, True])
def test_cancelled_request_keeps_slot_and_input_until_worker_finishes(external_adapters, late_error):
    started, release = Event(), Event()
    paths = []

    def predict(path):
        paths.append(path)
        started.set()
        assert release.wait(5), "test watchdog"
        assert path.read_bytes() == AUDIO
        if late_error and len(paths) == 1:
            raise RuntimeError("late predictor failure")
        return SimpleNamespace(clase="Chucao", confianza=.9)

    external_adapters.predict = predict

    async def scenario():
        client = ASGIClient()
        request = asyncio.create_task(client.post("/api/predict", files={"file": ("a.wav", AUDIO)}))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert paths[0].read_bytes() == AUDIO
            busy = await client.post("/api/predict", files={"file": ("b.wav", AUDIO)})
            assert busy.status_code == 503
        finally:
            release.set()

    asyncio.run(scenario())  # Runner drains executor threads, not a fabricated lifespan pass.
    assert not paths[0].exists()
    # A new loop must see the same process-wide slot, now released.
    assert asyncio.run(ASGIClient().post("/api/predict", files={"file": ("c.wav", AUDIO)})).status_code == 200
    assert all(not path.exists() for path in paths)


@pytest.mark.parametrize("error, expected", [
    (main.MalformedAudioError("invalid"), 400),
    (main.ModelWeightsError("unavailable"), 503),
    (RuntimeError("unexpected"), 500),
])
def test_worker_error_cleans_input_and_releases_admission(external_adapters, error, expected):
    paths = []

    def fail(path):
        paths.append(path)
        assert path.read_bytes() == AUDIO
        raise error

    external_adapters.predict = fail
    response = asyncio.run(ASGIClient().post("/api/predict", files={"file": ("a.wav", AUDIO)}))
    assert response.status_code == expected
    assert not paths[0].exists()
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)
    assert asyncio.run(ASGIClient().post("/api/predict", files={"file": ("b.wav", AUDIO)})).status_code == 200
