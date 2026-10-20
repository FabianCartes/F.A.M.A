"""Preserved public audio contracts, including rejection side effects."""
import asyncio
import hashlib
import io
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.main as main
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services.predictors.base import AudioPredictor
from tests.test_api_feedback import test_db
from tests.test_inference_input_limits import raw_request, request_body


class ProbePredictor(AudioPredictor):
    metadata = ModelMetadata(
        id="independent", name="Independent", description="Synthetic CPU probe",
        target_sr=2, duration_seconds=300, classes=["A", "B"],
    )

    def predict(self, path):
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == self.expected
        return PredictionResult(clase="A", confianza=0.75, detalles={"is_mock": True})


def wav(frames):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(2)
        stream.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


@pytest.mark.parametrize("audio,status,detail", [
    (wav(599), 200, None), (wav(600), 200, None),
    (wav(601), 400, "El audio supera la duración máxima de 300 segundos. No se recorta."),
    (wav(0), 400, "Audio inválido. Proporcione un WAV con muestras válidas."),
    (b"invalid", 400, "Audio inválido. Proporcione un archivo WAV válido."),
], ids=["below-duration-limit", "inclusive-duration-limit", "over-duration-limit", "empty-wav", "malformed"])
def test_preserved_public_audio_contract(test_db, monkeypatch, audio, status, detail):
    predictor = ProbePredictor()
    predictor.expected = hashlib.sha256(audio).hexdigest()
    uploader = AsyncMock(return_value=True)
    monkeypatch.setattr(main, "upload_audio_to_gcp", uploader)
    main.app.dependency_overrides[main.get_model_registry] = lambda: SimpleNamespace(get=lambda _: predictor)
    connection = test_db.connection().connection.driver_connection
    before = hashlib.sha256(connection.serialize()).hexdigest()
    try:
        actual, body, _ = asyncio.run(raw_request(request_body(audio)))
        assert actual == status
        if status != 200:
            assert body == {"detail": detail}
            assert hashlib.sha256(connection.serialize()).hexdigest() == before
            uploader.assert_not_awaited()
        else:
            assert body["clase"] == "A"
            assert body["modelo_id"] == "independent"
            assert body["modelo"] == "Independent"
            assert body["modelos_activos"] is None
            assert body["detalles"] == {"is_mock": True, "dataset_name": None}
            assert uploader.call_args.args[0] == audio
    finally:
        main.app.dependency_overrides.pop(main.get_model_registry, None)
