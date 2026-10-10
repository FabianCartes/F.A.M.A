"""Input contracts at raw ASGI/HTTP seams, with synthetic audio only."""
import asyncio
import json
import io
import pytest
import soundfile as sf
from types import SimpleNamespace
from unittest.mock import Mock

from tests.test_api_feedback import test_db
from tests.test_inference_execution import external_adapters
from tests.test_prediction_audio_metadata import synthetic_wav
import app.main as main


def multipart(data):
    return (b'--test\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
            b'Content-Type: application/octet-stream\r\n\r\n' + data + b'\r\n--test--\r\n')


async def raw_request(chunks, headers=(), method="POST", path="/api/predict", before_receive=None):
    messages, reads = [], []
    iterator = iter(chunks)

    async def receive():
        reads.append(True)
        if before_receive is not None:
            await before_receive()
        return next(iterator)

    async def send(message):
        messages.append(message)

    await main.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                    "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                    "query_string": b"", "root_path": "", "server": ("test", 80), "client": ("test", 1),
                    "headers": [(b"content-type", b"multipart/form-data; boundary=test"), *headers]}, receive, send)
    starts = [m for m in messages if m["type"] == "http.response.start"]
    assert len(starts) == 1
    if any(key == b"origin" for key, _ in headers):
        assert b"access-control-allow-origin" in dict(starts[0]["headers"])
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return starts[0]["status"], json.loads(body), reads


def request_body(data):
    return [{"type": "http.request", "body": multipart(data), "more_body": False}]


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")],
                                   [(b"content-length", b"1"), (b"content-length", b"9999")]])
def test_actual_body_counter_rejects_before_external_effects(external_adapters, test_db, monkeypatch, headers):
    from app.models.prediction import Prediccion
    external_adapters.predict = Mock(return_value=SimpleNamespace(clase="Chucao", confianza=.9))
    monkeypatch.setattr(main, "MAX_INFERENCE_BODY_BYTES", 180, raising=False)
    from starlette import formparsers
    original_spool = formparsers.SpooledTemporaryFile
    spools = []

    def tracked_spool(*args, **kwargs):
        spool = original_spool(*args, **kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked_spool)
    body = multipart(b"x" * 200)
    chunks = [{"type": "http.request", "body": body[:150], "more_body": True},
              {"type": "http.request", "body": body[150:], "more_body": False}]
    status, response, _ = asyncio.run(raw_request(chunks, headers))
    assert status == 413
    assert "110 MiB" in response["detail"]
    main.upload_audio_to_gcp.assert_not_awaited()
    assert spools and all(spool.closed for spool in spools)
    external_adapters.predict.assert_not_called()
    assert test_db.query(Prediccion).count() == 0
    monkeypatch.setattr(main, "MAX_INFERENCE_BODY_BYTES", 1024)
    assert asyncio.run(raw_request(request_body(synthetic_wav())))[0] == 200


def test_busy_rejected_without_reading_second_body(external_adapters):
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)

    async def scenario():
        reading, release = asyncio.Event(), asyncio.Event()

        async def stalled_receive():
            reading.set()
            await release.wait()

        first = asyncio.create_task(raw_request(request_body(synthetic_wav()), before_receive=stalled_receive))
        try:
            await asyncio.wait_for(reading.wait(), 1)
            status, _, reads = await raw_request([], [(b"origin", b"http://frontend")])
            assert status == 503
            assert not reads
        finally:
            release.set()
            assert (await first)[0] == 200

    asyncio.run(scenario())


def flac_bytes():
    stream = io.BytesIO()
    sf.write(stream, [0.0, 0.0], 48000, format="FLAC")
    return stream.getvalue()


def invalid_wav_field(offset, width):
    audio = bytearray(synthetic_wav())
    audio[offset:offset + width] = b"\x00" * width
    return bytes(audio)


@pytest.mark.parametrize("audio", [b"not a WAV", synthetic_wav(frames=0), flac_bytes(),
                                  invalid_wav_field(24, 4), invalid_wav_field(22, 2)],
                         ids=["malformed", "empty-wav", "flac-disguised-as-wav", "zero-rate", "zero-channels"])
def test_invalid_or_nonwav_input_rejected_before_effects(external_adapters, test_db, audio):
    from app.models.prediction import Prediccion
    external_adapters.predict = lambda path: pytest.fail("invalid input reached predictor")
    status, response, _ = asyncio.run(raw_request(request_body(audio)))
    assert status == 400
    assert "WAV" in response["detail"]
    main.upload_audio_to_gcp.assert_not_awaited()
    assert test_db.query(Prediccion).count() == 0


@pytest.mark.parametrize("frames, expected", [(599, 200), (600, 200), (601, 400)])
def test_duration_300_seconds_inclusive_without_cropping(external_adapters, test_db, frames, expected):
    from app.models.prediction import Prediccion
    audio = synthetic_wav(frames=frames, rate=2)

    def predict(path):
        assert path.read_bytes() == audio
        return SimpleNamespace(clase="Chucao", confianza=.9)

    external_adapters.predict = predict
    status, response, _ = asyncio.run(raw_request(request_body(audio)))
    assert status == expected
    if expected == 200:
        assert response["clase"] == "Chucao"
        assert main.upload_audio_to_gcp.call_args.args[0] == audio
        assert test_db.query(Prediccion).count() == 1
    else:
        assert "300" in response["detail"]
        main.upload_audio_to_gcp.assert_not_awaited()
        assert test_db.query(Prediccion).count() == 0


@pytest.mark.parametrize("margin, expected", [(-1, 413), (0, 200), (1, 200)])
def test_whole_body_boundary_is_inclusive(external_adapters, monkeypatch, margin, expected):
    audio = synthetic_wav()
    body = multipart(audio)
    monkeypatch.setattr(main, "MAX_INFERENCE_BODY_BYTES", len(body) + margin)
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)
    status, _, _ = asyncio.run(raw_request(request_body(audio)))
    assert status == expected
    if expected == 413:
        main.upload_audio_to_gcp.assert_not_awaited()


@pytest.mark.parametrize("chunks, expected", [
    ([{"type": "http.request", "body": b"", "more_body": False}], 422),
    ([{"type": "http.request", "body": b"--test\r\nbad header\r\n\r\n", "more_body": False}], 400),
    ([{"type": "http.disconnect"}], 400),
])
def test_parser_failure_or_disconnect_releases_slot(external_adapters, chunks, expected):
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)
    assert asyncio.run(raw_request(chunks))[0] == expected
    main.upload_audio_to_gcp.assert_not_awaited()
    assert asyncio.run(raw_request(request_body(synthetic_wav())))[0] == 200


def test_partial_multipart_disconnect_closes_spool_and_releases_slot(external_adapters, monkeypatch):
    from starlette import formparsers
    original_spool = formparsers.SpooledTemporaryFile
    spools = []

    def tracked_spool(*args, **kwargs):
        spool = original_spool(*args, **kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked_spool)
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)
    chunks = [{"type": "http.request", "body": multipart(synthetic_wav())[:-12], "more_body": True},
              {"type": "http.disconnect"}]
    try:
        assert asyncio.run(raw_request(chunks))[0] == 400
        assert spools and all(spool.closed for spool in spools)
    finally:
        for spool in spools:
            spool.close()
    assert asyncio.run(raw_request(request_body(synthetic_wav())))[0] == 200


def test_compatible_pcm24_stereo_48k_and_untrusted_mime(external_adapters):
    audio = synthetic_wav(frames=48, rate=48000, channels=2, sample_width=3)

    def predict(path):
        assert path.read_bytes() == audio
        return SimpleNamespace(clase="Chucao", confianza=.9)

    external_adapters.predict = predict
    assert asyncio.run(raw_request(request_body(audio)))[0] == 200


@pytest.mark.parametrize("method, expected", [("GET", 200), ("POST", 405)])
def test_other_routes_unaffected_by_body_limit(external_adapters, monkeypatch, method, expected):
    monkeypatch.setattr(main, "MAX_INFERENCE_BODY_BYTES", 1)
    assert asyncio.run(raw_request(request_body(b"large"), method=method, path="/health"))[0] == expected


def test_413_remains_json_and_cors_visible(external_adapters, monkeypatch):
    monkeypatch.setattr(main, "MAX_INFERENCE_BODY_BYTES", 1)
    status, response, _ = asyncio.run(raw_request(request_body(synthetic_wav()),
                                                [(b"origin", b"http://frontend")]))
    assert status == 413
    assert "detail" in response


def test_trailing_body_excess_is_not_silently_ignored(external_adapters, monkeypatch):
    audio = synthetic_wav()
    body = multipart(audio)
    monkeypatch.setattr(main, "MAX_INFERENCE_BODY_BYTES", len(body))
    external_adapters.predict = lambda path: pytest.fail("oversized input reached predictor")
    chunks = [{"type": "http.request", "body": body, "more_body": True},
              {"type": "http.request", "body": b"x", "more_body": False}]
    assert asyncio.run(raw_request(chunks))[0] == 413
    main.upload_audio_to_gcp.assert_not_awaited()


def test_cancellation_before_body_releases_early_lease(external_adapters):
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)

    async def scenario():
        reading = asyncio.Event()

        async def stalled():
            reading.set()
            await asyncio.Event().wait()

        request = asyncio.create_task(raw_request([], before_receive=stalled))
        await asyncio.wait_for(reading.wait(), 1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert (await raw_request(request_body(synthetic_wav())))[0] == 200

    asyncio.run(scenario())
