"""Real storage wrapper with fake SDK boundaries, never cloud or model startup."""
import asyncio
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.main as main
from app.services import storage
from app.models.prediction import Prediccion
from tests.test_api_feedback import test_db
from tests.test_inference_execution import ASGIClient, AUDIO, external_adapters
from tests.test_inference_input_limits import raw_request, request_body


@pytest.mark.parametrize("late_error", [False, True])
def test_cancelled_upload_keeps_admission_until_actual_sdk_finishes(
    external_adapters, test_db, monkeypatch, late_error, caplog
):
    caplog.set_level("INFO", logger="app.services.inference_execution")
    started, release = Event(), Event()
    calls = []

    class Client:
        def bucket(self, name): return self
        def blob(self, key): return self
        def upload_from_string(self, data, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                started.set()
                assert release.wait(5), "test watchdog"
                if late_error:
                    raise RuntimeError("private-bucket/private-object secret-error")

    monkeypatch.setattr(storage.storage, "Client", Client)
    monkeypatch.setattr(main, "upload_audio_to_gcp", storage.upload_audio_to_gcp)
    external_adapters.predict = Mock(return_value=SimpleNamespace(clase="Chucao", confianza=.9))

    async def scenario():
        client = ASGIClient()
        request = asyncio.create_task(client.post("/api/predict", files={"file": ("private.wav", AUDIO)}))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert (await client.get("/health")).status_code == 200
            busy = await client.post("/api/predict", files={"file": ("second.wav", AUDIO)})
            assert busy.status_code == 503
            external_adapters.predict.assert_not_called()
            assert test_db.query(Prediccion).count() == 0
            events = stage_events(caplog)
            assert not any(event["stage"] == "upload" for event in events)
            total = [event for event in events if event["stage"] == "total"]
            assert len(total) == 1 and total[0]["outcome"] == "cancelled"
            assert total[0]["worker_finished"] is False
        finally:
            release.set()

    asyncio.run(scenario())  # Drains actual SDK thread, including late failure.
    external_adapters.predict.assert_not_called()
    assert test_db.query(Prediccion).count() == 0
    assert calls == [{"content_type": "audio/wav", "timeout": 60, "retry": None}]
    upload = [event for event in stage_events(caplog) if event["stage"] == "upload"]
    assert len(upload) == 1 and upload[0]["worker_finished"] is True
    assert upload[0]["outcome"] == ("error" if late_error else "ok")
    assert "private-bucket" not in caplog.text and "secret-error" not in caplog.text
    assert asyncio.run(ASGIClient().post("/api/predict", files={"file": ("next.wav", AUDIO)})).status_code == 200
    assert test_db.query(Prediccion).count() == 1


def stage_events(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.name == "app.services.inference_execution"]


def test_success_emits_sanitized_stage_timings(external_adapters, monkeypatch, caplog):
    caplog.set_level("INFO", logger="app.services.inference_execution")

    class Client:
        def bucket(self, name): return self
        def blob(self, key): return self
        def upload_from_string(self, data, **kwargs): pass

    monkeypatch.setattr(storage.storage, "Client", Client)
    monkeypatch.setattr(main, "upload_audio_to_gcp", storage.upload_audio_to_gcp)
    external_adapters.model_id = "private-model"
    external_adapters.predict = lambda path: SimpleNamespace(clase="Chucao", confianza=.9)
    assert asyncio.run(raw_request(request_body(AUDIO)))[0] == 200
    events = stage_events(caplog)
    assert {event["stage"] for event in events} == {
        "ingress", "read", "validation", "upload", "predict", "persist", "total"
    }
    assert len({event["id"] for event in events}) == 1
    for event in events:
        assert set(event) == {"event", "id", "stage", "duration_ms", "outcome", "worker_finished"}
        assert event["event"] == "inference_stage"
        assert len(event["id"]) == 32 and all(c in "0123456789abcdef" for c in event["id"])
        assert event["duration_ms"] >= 0
        assert event["outcome"] == "ok"
        assert event["worker_finished"] is (event["stage"] in {"validation", "upload", "predict"})
    assert "private-model" not in caplog.text


def test_upload_error_is_sanitized_and_allows_recovery(
    external_adapters, test_db, monkeypatch, caplog, capsys
):
    caplog.set_level("INFO", logger="app.services.inference_execution")
    private = "gs://private-bucket/private.wav token=private-token /private/path"

    class Client:
        fail = True
        def bucket(self, name): return self
        def blob(self, key): return self
        def upload_from_string(self, data, **kwargs):
            if self.fail:
                raise RuntimeError(private)

    monkeypatch.setattr(storage.storage, "Client", Client)
    monkeypatch.setattr(main, "upload_audio_to_gcp", storage.upload_audio_to_gcp)
    external_adapters.predict = Mock(return_value=SimpleNamespace(clase="Chucao", confianza=.9))
    status, response, _ = asyncio.run(raw_request(request_body(AUDIO)))
    assert status == 500
    external_adapters.predict.assert_not_called()
    assert test_db.query(Prediccion).count() == 0
    output = capsys.readouterr()
    for marker in ["private-bucket", "private.wav", "private-token", "/private/path", "Traceback"]:
        assert marker not in json.dumps(response) + caplog.text + output.out + output.err
    upload = [event for event in stage_events(caplog) if event["stage"] == "upload"]
    assert len(upload) == 1 and upload[0]["outcome"] == "error" and upload[0]["worker_finished"] is True
    total = [event for event in stage_events(caplog) if event["stage"] == "total"]
    assert len(total) == 1 and total[0]["outcome"] == "error" and total[0]["worker_finished"] is False
    Client.fail = False
    assert asyncio.run(raw_request(request_body(AUDIO)))[0] == 200
