"""
backend/tests/test_engine_ensemble_predictor.py
Pruebas unitarias e integración para el predictor del Super-Ensamble Tri-Modelo
Campeón de Diagnóstico Acústico de Motores (All-RMS-Balanced).
Metodología: Strict TDD + RDD.
"""
import io
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
import numpy as np
import pytest
import soundfile as sf
import torch
import torch.nn as nn
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.schemas.prediction import PredictionResult
from app.services.registry import build_default_registry, get_model_registry
from app.services.predictors.engine_ensemble_predictor import (
    EngineEnsemblePredictor,
    DEFAULT_ENGINE_ENSEMBLE_WEIGHTS,
)
from training.pipelines.multitask_mapping import CLASS_NAMES_13


def create_engine_wav_bytes(sr: int = 32000, duration: float = 2.0, freq: float = 180.0) -> bytes:
    """Genera un archivo WAV en memoria con señal tonal representativa."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # Tono base + armónico para simular acústica de motor y evitar filtro de planitud o silencio
    signal = 0.3 * np.sin(2 * np.pi * freq * t) + 0.1 * np.sin(2 * np.pi * (freq * 2) * t)
    buf = io.BytesIO()
    sf.write(buf, signal.astype(np.float32), sr, format="WAV")
    buf.seek(0)
    return buf.read()


def test_engine_ensemble_metadata():
    """
    Verifica metadatos declarativos del Super-Ensamble Tri-Modelo Campeón:
    - ID exacto 'car-engine-diagnostics-super-ensemble'
    - Tasa de muestreo 32000 Hz, duración 2.0 s
    - 13 clases automotrices exactas
    - Métricas oficiales del recibo Fase 11 (Accuracy ~81.16%, Macro F1 ~80.33%)
    """
    predictor = EngineEnsemblePredictor(lazy_load=True)
    meta = predictor.metadata

    assert meta.id == "car-engine-diagnostics-super-ensemble"
    assert "Super-Ensamble" in meta.name
    assert meta.target_sr == 32000
    assert meta.duration_seconds == 2.0
    assert meta.classes == CLASS_NAMES_13
    assert len(meta.classes) == 13
    assert not meta.is_default

    # Métricas oficiales del recibo de fase 11
    assert "accuracy" in meta.metrics
    assert "f1_macro" in meta.metrics
    assert meta.metrics["accuracy"] == pytest.approx(0.8116, abs=1e-3)
    assert meta.metrics["f1_macro"] == pytest.approx(0.8033, abs=1e-3)


class StubSubModel(nn.Module):
    """Sub-modelo stub que retorna logits fijos correspondientes a probabilidades predeterminadas."""

    def __init__(self, target_probs: torch.Tensor):
        super().__init__()
        # Invertir softmax de manera simple: log(p)
        self.logits = nn.Parameter(torch.log(target_probs + 1e-8), requires_grad=False)

    def forward(self, x: torch.Tensor):
        batch_size = x.shape[0]
        # Devuelve tupla (class_logits, attr_logits) para compatibilidad multi-task
        return self.logits.repeat(batch_size, 1), torch.zeros((batch_size, 7))


def test_engine_ensemble_linear_combination_of_probabilities(tmp_path):
    """
    Verifica la combinación lineal exacta:
    P_ens = 0.60 * P_res + 0.10 * P_eff + 0.30 * P_panns

    Escenario de prueba:
    - ResNet34d asigna 1.0 a la clase 0 ('bad_ignition')
    - EfficientNet-B0 asigna 1.0 a la clase 1 ('dead_battery')
    - PANNs CNN14 asigna 1.0 a la clase 2 ('low_oil')

    Resultado esperado del ensamble:
    - Probabilidad clase 0 = 0.60
    - Probabilidad clase 1 = 0.10
    - Probabilidad clase 2 = 0.30
    - Clase ganadora = 'bad_ignition' con confianza 0.60
    """
    num_classes = 13
    p_res = torch.zeros(num_classes)
    p_res[0] = 1.0  # bad_ignition

    p_eff = torch.zeros(num_classes)
    p_eff[1] = 1.0  # dead_battery

    p_panns = torch.zeros(num_classes)
    p_panns[2] = 1.0  # low_oil

    stub_models = {
        "resnet": StubSubModel(p_res),
        "efficientnet": StubSubModel(p_eff),
        "panns": StubSubModel(p_panns),
    }

    predictor = EngineEnsemblePredictor(
        models=stub_models,
        weights=DEFAULT_ENGINE_ENSEMBLE_WEIGHTS,
        lazy_load=False,
    )

    wav_bytes = create_engine_wav_bytes(sr=32000, duration=2.0)
    audio_path = tmp_path / "test_engine.wav"
    audio_path.write_bytes(wav_bytes)

    result = predictor.predict(audio_path)

    assert isinstance(result, PredictionResult)
    assert result.clase == "bad_ignition"
    assert result.confianza == pytest.approx(0.60, abs=1e-3)

    # Verificar vector completo de probabilidades en detalles
    assert "ensemble_probabilities" in result.detalles
    probs = result.detalles["ensemble_probabilities"]
    assert probs["bad_ignition"] == pytest.approx(0.60, abs=1e-3)
    assert probs["dead_battery"] == pytest.approx(0.10, abs=1e-3)
    assert probs["low_oil"] == pytest.approx(0.30, abs=1e-3)


def test_engine_ensemble_consensus_high_confidence(tmp_path):
    """
    Verifica que cuando los tres modelos coinciden en la misma clase ('normal_engine_idle'),
    la confianza combinada converge a 1.0.
    """
    num_classes = 13
    p_idle = torch.zeros(num_classes)
    idle_idx = CLASS_NAMES_13.index("normal_engine_idle")
    p_idle[idle_idx] = 1.0

    stub_models = {
        "resnet": StubSubModel(p_idle),
        "efficientnet": StubSubModel(p_idle),
        "panns": StubSubModel(p_idle),
    }

    predictor = EngineEnsemblePredictor(
        models=stub_models,
        weights=DEFAULT_ENGINE_ENSEMBLE_WEIGHTS,
        lazy_load=False,
    )

    wav_bytes = create_engine_wav_bytes(sr=32000, duration=2.0)
    audio_path = tmp_path / "normal_idle.wav"
    audio_path.write_bytes(wav_bytes)

    result = predictor.predict(audio_path)
    assert result.clase == "normal_engine_idle"
    assert result.confianza == pytest.approx(1.00, abs=1e-3)


def test_engine_ensemble_silence_detection(tmp_path):
    """Verifica que el audio silencioso sea filtrado por el umbral de RMS."""
    predictor = EngineEnsemblePredictor(lazy_load=True)

    silence = np.zeros(64000, dtype=np.float32)
    silence_path = tmp_path / "silence.wav"
    sf.write(silence_path, silence, 32000)

    result = predictor.predict(silence_path)
    assert result.clase == "Silencio / No detectado"
    assert result.confianza == 0.0
    assert result.detalles["status"] == "silence"


def test_engine_ensemble_registry_integration():
    """
    Verifica que build_default_registry() registre automáticamente
    el predictor 'car-engine-diagnostics-super-ensemble'.
    """
    registry = build_default_registry()

    assert registry.has_model("car-engine-diagnostics-super-ensemble")
    predictor = registry.get("car-engine-diagnostics-super-ensemble")
    assert predictor.model_id == "car-engine-diagnostics-super-ensemble"

    all_models = registry.list_models()
    model_ids = [m.id for m in all_models]
    assert "car-engine-diagnostics-super-ensemble" in model_ids


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_fastapi_models_endpoint_lists_engine_ensemble(mock_upload):
    """Verifica que GET /api/models retorne el super-ensamble en el catálogo."""
    mock_upload.return_value = True
    client = TestClient(app)

    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    model_ids = [m["id"] for m in data["models"]]
    assert "car-engine-diagnostics-super-ensemble" in model_ids


@patch("app.main.upload_audio_to_gcp", new_callable=AsyncMock)
def test_fastapi_predict_with_engine_ensemble(mock_upload, tmp_path):
    """
    Verifica que POST /api/predict?model_id=car-engine-diagnostics-super-ensemble
    ejecute exitosamente la inferencia acústica a través de la API REST.
    """
    mock_upload.return_value = True

    # Usar sesión mock para BD si es necesario
    mock_db = MagicMock()
    mock_db.commit.return_value = None
    mock_db.refresh.side_effect = lambda inst: setattr(inst, "id_prediccion", 777)

    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app)
    wav_bytes = create_engine_wav_bytes(sr=32000, duration=2.0)

    response = client.post(
        "/api/predict?model_id=car-engine-diagnostics-super-ensemble",
        files={"file": ("motor_sample.wav", wav_bytes, "audio/wav")},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["modelo_id"] == "car-engine-diagnostics-super-ensemble"
    assert data["clase"] in CLASS_NAMES_13
    assert data["confianza"] > 0.0
    assert data["filename"] == "motor_sample.wav"


def test_engine_ensemble_predict_real_weights(tmp_path):
    """
    Verifica la inferencia real de extremo a extremo con los checkpoints en disco
    del Super-Ensamble Tri-Modelo All-RMS-Balanced.
    """
    predictor = EngineEnsemblePredictor(lazy_load=False)
    if predictor.sub_models is None:
        pytest.skip("Checkpoints del Super-Ensamble de motores no presentes en disco")
    assert predictor.sub_models is not None
    assert set(predictor.sub_models.keys()) == {"resnet", "efficientnet", "panns"}

    wav_bytes = create_engine_wav_bytes(sr=32000, duration=2.0, freq=220.0)
    audio_path = tmp_path / "engine_real_weights.wav"
    audio_path.write_bytes(wav_bytes)

    result = predictor.predict(audio_path)
    assert isinstance(result, PredictionResult)
    assert result.clase in CLASS_NAMES_13
    assert 0.0 < result.confianza <= 1.0
    assert result.detalles["status"] == "classified_super_ensemble"
    assert "ensemble_probabilities" in result.detalles
    assert len(result.detalles["ensemble_probabilities"]) == 13
    # La suma de las probabilidades combinadas del ensamble debe aproximar 1.0
    total_prob = sum(result.detalles["ensemble_probabilities"].values())
    assert total_prob == pytest.approx(1.0, abs=1e-2)

