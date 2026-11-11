"""Dataset-scoped standard prediction history through HTTP."""
from unittest.mock import AsyncMock

from app import main
from app.routes.prediction_history import router
from app.services.registry import ModelRegistry, get_model_registry
from tests.test_api_predict import ContractPredictor, create_dummy_wav_bytes
from tests.test_resource_access import access, assign, functional, web
from tests.test_web_sessions import ORIGIN


def test_cloud_backed_history_is_visible_only_for_the_selected_model(functional, monkeypatch):
    client, _ = functional
    client.app.include_router(router)
    registry = ModelRegistry()
    for model_id in ("birds-one", "birds-two"):
        predictor = ContractPredictor(model_id)
        predictor._metadata.dataset_name = "AvesChilenas"
        registry.register(predictor, is_default=(model_id == "birds-one"))
    client.app.dependency_overrides[get_model_registry] = lambda: registry
    monkeypatch.setattr(main.feedback_service, "import_root", None)
    monkeypatch.delenv("FAMA_IMPORT_ROOT", raising=False)
    monkeypatch.setattr(main, "upload_audio_to_gcp", AsyncMock(return_value=True))
    assign(client)
    prediction = client.post("/api/predict", headers={"Origin": ORIGIN},
        params={"model_id": "birds-one"},
        files={"file": ("cloud.wav", create_dummy_wav_bytes(), "audio/wav")})
    assert prediction.status_code == 200, prediction.text
    history = client.get("/api/inference/history", params={"model_id": "birds-one"})
    assert history.status_code == 200, history.text
    assert history.headers["cache-control"] == "no-store"
    assert [item["id"] for item in history.json()["items"]] == [prediction.json()["db_id"]]
    assert history.json()["items"][0]["filename"] == "cloud.wav"
    assert "raw_audios/" not in history.text
    other = client.get("/api/inference/history", params={"model_id": "birds-two"})
    assert other.status_code == 200, other.text
    assert other.json() == {"items": [], "next_cursor": None}
    for params in ({"limit": 0}, {"limit": 21}, {"cursor": 0}, {"cursor": "bad"}):
        response = client.get("/api/inference/history", params={"model_id": "birds-one", **params})
        assert response.status_code == 422
    client.cookies.clear()
    assert client.get("/api/inference/history", params={"model_id": "birds-one"}).status_code == 401
