"""Reception metadata through inference, with SQLite and fake external boundaries."""
import asyncio
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from tests.test_api_feedback import test_db
from app.models.prediction import Prediccion
import app.main as main


@pytest.mark.parametrize("size, expected_status", [(7, 200), (8, 200), (9, 413), (24, 413)])
def test_public_http_audio_limit_before_external_effects(test_db, monkeypatch, size, expected_status):
    # Threshold-scale contract test, not a 100 MiB transport measurement.
    monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 8, raising=False)
    from starlette.datastructures import UploadFile as MultipartUpload
    original_read = MultipartUpload.read
    reads = []

    async def bounded_read(upload, size=-1):
        assert 0 < size <= 1024 * 1024
        reads.append(size)
        upload.size = 1  # Metadata is not authoritative.
        return await original_read(upload, size)

    monkeypatch.setattr(MultipartUpload, "read", bounded_read)
    uploader = AsyncMock(return_value=True)
    predictor = SimpleNamespace(model_id="fake-model", dataset_name="AvesChilenas",
                                predict=Mock(return_value=SimpleNamespace(clase="Chucao", confianza=.9)))
    monkeypatch.setattr(main, "upload_audio_to_gcp", uploader)
    monkeypatch.setattr(main.ensemble_service, "get_status", lambda **kwargs: {})
    main.app.dependency_overrides[main.get_model_registry] = lambda: SimpleNamespace(get=lambda _: predictor)
    try:
        # No context manager: do not run startup/lifespan or discover real models.
        client = TestClient(main.app)
        response = client.post("/api/predict", files={"file": ("large.wav", b"x" * size, "audio/wav")},
                               headers={"Content-Length": "1"})
        assert response.status_code == expected_status
        assert reads
        if expected_status == 413:
            assert "100 MiB" in response.json()["detail"]
            uploader.assert_not_awaited()
            predictor.predict.assert_not_called()
            assert test_db.query(Prediccion).count() == 0
        else:
            assert response.json()["clase"] == "Chucao"
            assert uploader.call_args.args[0] == b"x" * size
            assert test_db.query(Prediccion).count() == 1
    finally:
        client.close()
        main.app.dependency_overrides.pop(main.get_model_registry, None)


@pytest.mark.parametrize("filename, expected", [
    ("/private/uploads/canto original.wav", "canto original.wav"),
    (r"C:\uploads\canto original.wav", "canto original.wav"),
    ("../" + "a" * 300 + ".wav", "a" * 255),
    ("", None), (None, None),
])
def test_inference_persists_original_name_and_reception_before_read(test_db, monkeypatch, filename, expected):
    received = datetime(2026, 10, 6, 20, 30, 17, tzinfo=timezone.utc)
    later = datetime(2026, 10, 6, 20, 31, 42, tzinfo=timezone.utc)

    class Clock(datetime):
        current = received

        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return cls.current

    class SlowUpload(UploadFile):
        async def read(self, size=-1):
            Clock.current = later
            return await super().read(size)

    monkeypatch.setattr(main, "datetime", Clock, raising=False)
    uploaded = AsyncMock(return_value=True)
    monkeypatch.setattr(main, "upload_audio_to_gcp", uploaded)
    monkeypatch.setattr(main.ensemble_service, "get_status", lambda **kwargs: {})
    predictor = SimpleNamespace(model_id="fake-model", dataset_name="AvesChilenas",
                                predict=lambda path: SimpleNamespace(clase="Chucao", confianza=.9))
    response = asyncio.run(main.predict_audio(
        file=SlowUpload(filename=filename, file=io.BytesIO(b"fake audio")),
        model_id=None, dataset_name=None, db=test_db,
        registry=SimpleNamespace(get=lambda model_id: predictor),
    ))
    test_db.expire_all()
    stored = test_db.get(Prediccion, response["db_id"])
    assert stored.nombre_original == expected
    # SQLite drops timezone metadata; this column's contract is explicitly UTC.
    assert stored.fecha_carga.replace(tzinfo=timezone.utc) == received
    assert stored.fecha_carga.replace(tzinfo=timezone.utc) != later
    key = uploaded.call_args.kwargs["filename"]
    assert len(key) == 36 and key.endswith(".wav")
    assert stored.ruta_audio_prueba == "raw_audios/" + key
    assert response["filename"] == (filename or "audio.wav")
