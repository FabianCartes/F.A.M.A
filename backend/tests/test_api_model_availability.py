"""Availability preflight through HTTP, without real weights, startup or cloud."""
from unittest.mock import AsyncMock
import pytest

from tests.test_api_predict import (
    ContractPredictor, client, controlled_registry, mock_db_session,
    create_dummy_wav_bytes,
)


class AvailabilityPredictor(ContractPredictor):
    def __init__(self):
        super().__init__("availability-fixture")
        self.available = False
        self.predictions = 0

    @property
    def has_weights(self):
        return self.available

    def predict(self, path):
        self.predictions += 1
        return super().predict(path)


@pytest.mark.parametrize("use_default", [False, True])
@pytest.mark.parametrize("availability", [False, None])
def test_http_rejects_missing_weights_before_cloud_upload(
    client, controlled_registry, mock_db_session, monkeypatch, use_default, availability,
):
    predictor = AvailabilityPredictor()
    predictor.available = availability
    controlled_registry.register(predictor, is_default=use_default)
    uploader = AsyncMock(return_value=True)
    monkeypatch.setattr("app.main.upload_audio_to_gcp", uploader)

    response = client.post(
        "/api/predict", params={} if use_default else {"model_id": predictor.model_id},
        files={"file": ("audio.wav", create_dummy_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 503
    assert "pesos" in response.json()["detail"]
    uploader.assert_not_awaited()
    assert predictor.predictions == 0
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_called()


def test_http_rechecks_availability_after_catalogue_and_allows_recovery(
    client, controlled_registry, mock_db_session, monkeypatch,
):
    predictor = AvailabilityPredictor()
    predictor.available = True
    controlled_registry.register(predictor, is_default=True)
    uploader = AsyncMock(return_value=True)
    monkeypatch.setattr("app.main.upload_audio_to_gcp", uploader)
    catalogue = client.get("/api/models").json()
    model = next(model for model in catalogue["models"] if model["id"] == predictor.model_id)
    assert model["has_weights"] is True
    assert catalogue["default_model_id"] == predictor.model_id

    # A successful catalogue is not a reservation of the predictor's weights.
    predictor.available = False
    rejected = client.post("/api/predict", files={
        "file": ("audio.wav", create_dummy_wav_bytes(), "audio/wav"),
    })
    assert rejected.status_code == 503
    uploader.assert_not_awaited()
    mock_db_session.commit.assert_not_called()
    unavailable_catalogue = client.get("/api/models").json()
    model = next(model for model in unavailable_catalogue["models"] if model["id"] == predictor.model_id)
    assert model["has_weights"] is False
    assert unavailable_catalogue["default_model_id"] == predictor.model_id
    filtered = client.get("/api/models?only_available=true").json()
    assert predictor.model_id not in {model["id"] for model in filtered["models"]}

    predictor.available = True
    recovered = client.post("/api/predict", files={
        "file": ("audio.wav", create_dummy_wav_bytes(), "audio/wav"),
    })
    assert recovered.status_code == 200
    assert recovered.json()["modelo_id"] == predictor.model_id
    uploader.assert_awaited_once()
    assert predictor.predictions == 1
    mock_db_session.commit.assert_called_once()


def test_http_sanitizes_unverifiable_weights_and_does_not_upload(
    client, controlled_registry, mock_db_session, monkeypatch,
):
    class UnverifiablePredictor(AvailabilityPredictor):
        @property
        def has_weights(self):
            raise PermissionError("/private/checkpoints/weights.pt")

    predictor = UnverifiablePredictor()
    controlled_registry.register(predictor)
    uploader = AsyncMock(return_value=True)
    monkeypatch.setattr("app.main.upload_audio_to_gcp", uploader)

    response = client.post(
        "/api/predict", params={"model_id": predictor.model_id},
        files={"file": ("audio.wav", create_dummy_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 503
    assert "/private" not in response.text
    uploader.assert_not_awaited()
    assert predictor.predictions == 0
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_called()
