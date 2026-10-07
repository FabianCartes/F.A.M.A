"""Reception metadata through inference, with SQLite and fake external boundaries."""
import asyncio
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from tests.test_api_feedback import test_db
from app.models.prediction import Prediccion
import app.main as main


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
