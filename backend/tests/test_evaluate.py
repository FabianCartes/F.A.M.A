import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import torch
import torch.nn as nn
import pandas as pd
import numpy as np
import pytest

from poc.train import AudioCNN
from poc.preprocess import TARGET_SR, DURATION_SECONDS
from poc.evaluate import (
    evaluate_test_set,
    compute_metrics_and_matrix,
    predict_audio_tta,
    EnsembleClassifier,
)


def test_compute_metrics_and_matrix(tmp_path):
    y_true = np.array([0, 1, 0, 1, 2, 2, 0, 1, 2])
    y_pred = np.array([0, 1, 0, 0, 2, 2, 1, 1, 2])
    classes = ["Clase A", "Clase B", "Clase C"]
    output_png = tmp_path / "confusion_matrix.png"
    
    metrics = compute_metrics_and_matrix(y_true, y_pred, classes, output_png)
    
    assert "accuracy" in metrics
    assert "precision_macro" in metrics
    assert "recall_macro" in metrics
    assert "f1_macro" in metrics
    assert "confusion_matrix" in metrics
    assert output_png.exists()
    assert output_png.stat().st_size > 0

def test_evaluate_test_set(tmp_path):
    classes = ["Chincol", "Zorzal"]
    model = AudioCNN(num_classes=len(classes))
    model.eval()
    
    features = torch.randn(6, 1, 64, 216)
    labels = torch.tensor([0, 1, 0, 1, 0, 1])
    dataset = torch.utils.data.TensorDataset(features, labels)
    loader = torch.utils.data.DataLoader(dataset, batch_size=2)
    
    output_img = tmp_path / "matrix.png"
    results = evaluate_test_set(model, loader, classes, output_image_path=output_img, device=torch.device("cpu"))
    
    assert "accuracy" in results
    assert 0.0 <= results["accuracy"] <= 1.0
    assert output_img.exists()


def test_predict_audio_tta_short_audio():
    """Verifica que procesa audios cortos (< 5s) con zero-padding sin error (N=1)."""
    model = AudioCNN(num_classes=3)
    model.eval()
    
    # Audio de 2.0 segundos (< 5.0 segundos)
    short_audio = np.random.randn(int(TARGET_SR * 2.0)).astype(np.float32)
    
    pred_mean, probs_mean = predict_audio_tta(
        model=model,
        audio_input=short_audio,
        n_mels=64,
        mode="mean",
        device=torch.device("cpu"),
    )
    
    pred_max, probs_max = predict_audio_tta(
        model=model,
        audio_input=short_audio,
        n_mels=64,
        mode="max",
        device=torch.device("cpu"),
    )
    
    assert isinstance(pred_mean, int)
    assert 0 <= pred_mean < 3
    assert probs_mean.shape == (3,)
    assert torch.isclose(probs_mean.sum(), torch.tensor(1.0), atol=1e-4)
    assert pred_mean == int(torch.argmax(probs_mean).item())
    
    # En N=1, mean y max deben ser idénticos
    assert torch.allclose(probs_mean, probs_max, atol=1e-5)


def test_predict_audio_tta_long_audio_aggregation():
    """Verifica que en audios largos (> 10s) extrae N ventanas e infiere con agregación mean y max."""
    class DeterministicTTAClassifier(nn.Module):
        def forward(self, x):
            # x shape: [N, 1, 64, 216]
            N = x.shape[0]
            logits = torch.zeros(N, 2)
            # Ventana 0 tiene alta probabilidad para Clase 0 (logit 2.0 vs 0.0)
            logits[0] = torch.tensor([2.0, 0.0])
            # Ventanas 1..N-1 tienen alta probabilidad para Clase 1 (logit 0.0 vs 2.0)
            for i in range(1, N):
                logits[i] = torch.tensor([0.0, 2.0])
            return logits

    model = DeterministicTTAClassifier()
    model.eval()
    
    # Audio largo de 11.5 segundos (> 10s)
    long_audio = np.random.randn(int(TARGET_SR * 11.5)).astype(np.float32)
    
    pred_mean, probs_mean = predict_audio_tta(
        model=model,
        audio_input=long_audio,
        n_mels=64,
        mode="mean",
        device=torch.device("cpu"),
    )
    
    pred_max, probs_max = predict_audio_tta(
        model=model,
        audio_input=long_audio,
        n_mels=64,
        mode="max",
        device=torch.device("cpu"),
    )
    
    assert probs_mean.shape == (2,)
    assert probs_max.shape == (2,)
    # En 'mean', la mayoría de ventanas son clase 1, por lo que gana clase 1
    assert pred_mean == 1
    assert probs_mean[1] > probs_mean[0]
    assert torch.isclose(probs_mean.sum(), torch.tensor(1.0), atol=1e-4)
    
    # En 'max', ambas clases alcanzaron el pico máximo de certeza en al menos una ventana
    # softmax([2.0, 0.0])[0] = 1 / (1 + exp(-2)) ≈ 0.8808
    expected_peak = float(torch.softmax(torch.tensor([2.0, 0.0]), dim=0)[0].item())
    assert torch.isclose(probs_max[0], torch.tensor(expected_peak), atol=1e-3)
    assert torch.isclose(probs_max[1], torch.tensor(expected_peak), atol=1e-3)


def test_predict_audio_tta_invalid_mode():
    """Comprueba que un modo no válido lanza ValueError."""
    model = AudioCNN(num_classes=2)
    dummy_audio = np.zeros(TARGET_SR, dtype=np.float32)
    with pytest.raises(ValueError, match="Modo TTA no soportado"):
        predict_audio_tta(model, dummy_audio, mode="unsupported_mode", device=torch.device("cpu"))


def test_evaluate_test_set_preserves_standard_evaluation(tmp_path):
    """Comprueba que no rompe la evaluación estándar cuando use_tta=False."""
    classes = ["Clase A", "Clase B"]
    model = AudioCNN(num_classes=len(classes))
    model.eval()
    
    features = torch.randn(4, 1, 64, 216)
    labels = torch.tensor([0, 1, 0, 1])
    dataset = torch.utils.data.TensorDataset(features, labels)
    loader = torch.utils.data.DataLoader(dataset, batch_size=2)
    
    output_img = tmp_path / "matrix_standard.png"
    results = evaluate_test_set(
        model=model,
        test_loader=loader,
        classes=classes,
        output_image_path=output_img,
        device=torch.device("cpu"),
        use_tta=False,
    )
    
    assert "accuracy" in results
    assert "f1_macro" in results
    assert output_img.exists()


def test_predict_audio_tta_custom_hop():
    """Verifica que predict_audio_tta acepte hop_seconds personalizado."""
    model = AudioCNN(num_classes=2)
    model.eval()
    audio = np.random.randn(int(TARGET_SR * 10.0)).astype(np.float32)

    pred_125, probs_125 = predict_audio_tta(
        model=model,
        audio_input=audio,
        n_mels=64,
        mode="mean",
        device=torch.device("cpu"),
        hop_seconds=1.25,
    )
    assert isinstance(pred_125, int)
    assert probs_125.shape == (2,)

    pred_100, probs_100 = predict_audio_tta(
        model=model,
        audio_input=audio,
        n_mels=64,
        mode="mean",
        device=torch.device("cpu"),
        hop_seconds=1.0,
    )
    assert isinstance(pred_100, int)
    assert probs_100.shape == (2,)


def test_evaluate_test_set_accepts_and_propagates_hop_seconds(tmp_path, monkeypatch):
    """Verifica que evaluate_test_set acepte hop_seconds y lo propague a predict_audio_tta."""
    classes = ["Clase A", "Clase B"]
    model = AudioCNN(num_classes=len(classes))
    model.eval()

    features = torch.randn(2, int(TARGET_SR * 6.0))
    labels = torch.tensor([0, 1])
    dataset = torch.utils.data.TensorDataset(features, labels)
    loader = torch.utils.data.DataLoader(dataset, batch_size=1)

    captured_hops = []
    original_predict_tta = sys.modules["poc.evaluate"].predict_audio_tta

    def spy_predict_tta(*args, **kwargs):
        captured_hops.append(kwargs.get("hop_seconds"))
        return original_predict_tta(*args, **kwargs)

    monkeypatch.setattr("poc.evaluate.predict_audio_tta", spy_predict_tta)

    output_img = tmp_path / "matrix_hop.png"
    results = evaluate_test_set(
        model=model,
        test_loader=loader,
        classes=classes,
        output_image_path=output_img,
        device=torch.device("cpu"),
        use_tta=True,
        tta_mode="mean",
        n_mels=64,
        hop_seconds=1.25,
    )

    assert "accuracy" in results
    assert len(captured_hops) == 2
    assert all(h == 1.25 for h in captured_hops)


def test_ensemble_classifier_soft_voting():
    """Verifica que EnsembleClassifier combine probabilidades vía Soft Voting ponderado."""
    class MockModelA(nn.Module):
        def forward(self, x):
            # Clase 0 casi 100%
            return torch.tensor([[10.0, -10.0]])

    class MockModelB(nn.Module):
        def forward(self, x):
            # Clase 1 casi 100%
            return torch.tensor([[-10.0, 10.0]])

    mA = MockModelA()
    mB = MockModelB()
    ensemble = EnsembleClassifier([mA, mB], weights=[0.8, 0.2])

    dummy_x = torch.zeros(1, 1, 64, 216)
    out_logits = ensemble(dummy_x)
    probs = torch.softmax(out_logits, dim=-1)

    assert probs.shape == (1, 2)
    # Debe ser muy cercano a [0.8, 0.2]
    assert torch.isclose(probs[0, 0], torch.tensor(0.8), atol=1e-3)
    assert torch.isclose(probs[0, 1], torch.tensor(0.2), atol=1e-3)


def test_ensemble_classifier_weights_validation():
    """Verifica normalización automática de pesos y validación de dimensiones."""
    mA = AudioCNN(num_classes=2)
    mB = AudioCNN(num_classes=2)

    # Normalización automática: [3.0, 1.0] -> [0.75, 0.25]
    ens = EnsembleClassifier([mA, mB], weights=[3.0, 1.0])
    assert pytest.approx(ens.weights[0]) == 0.75
    assert pytest.approx(ens.weights[1]) == 0.25

    # Pesos uniformes si None
    ens_none = EnsembleClassifier([mA, mB], weights=None)
    assert pytest.approx(ens_none.weights[0]) == 0.5
    assert pytest.approx(ens_none.weights[1]) == 0.5

    # Error en longitud desigual
    with pytest.raises(ValueError, match="no coincide"):
        EnsembleClassifier([mA, mB], weights=[0.5])


def test_predict_audio_tta_with_ensemble():
    """Verifica que predict_audio_tta funcione transparentemente con EnsembleClassifier."""
    mA = AudioCNN(num_classes=3)
    mB = AudioCNN(num_classes=3)
    mA.eval()
    mB.eval()
    ensemble = EnsembleClassifier([mA, mB], weights=[0.6, 0.4])

    audio = np.random.randn(int(TARGET_SR * 6.0)).astype(np.float32)
    pred, probs = predict_audio_tta(
        model=ensemble,
        audio_input=audio,
        n_mels=64,
        mode="max",
        device=torch.device("cpu"),
        hop_seconds=1.0,
    )

    assert isinstance(pred, int)
    assert 0 <= pred < 3
    assert probs.shape == (3,)
    assert torch.isclose(probs.sum(), torch.tensor(1.0), atol=1e-3)


def test_load_checkpoint_model_convnext(tmp_path):
    """Verifica que load_checkpoint_model cargue sin error un checkpoint con model_type='convnext_nano.d1h_in1k'."""
    from poc.evaluate import load_checkpoint_model
    from poc.train import BioacousticModel

    classes = [f"Especie_{i}" for i in range(15)]
    model = BioacousticModel(
        model_name="convnext_nano.d1h_in1k",
        num_classes=len(classes),
        pretrained=False,
        pool_type="avg",
    )
    ckpt_path = tmp_path / "convnext_checkpoint.pt"
    torch.save(
        {
            "model_type": "convnext_nano.d1h_in1k",
            "classes": classes,
            "pool_type": "avg",
            "model_state_dict": model.state_dict(),
        },
        ckpt_path,
    )

    device = torch.device("cpu")
    loaded_model, ckpt_data = load_checkpoint_model(ckpt_path, device)

    assert ckpt_data["model_type"] == "convnext_nano.d1h_in1k"
    assert ckpt_data["classes"] == classes
    assert isinstance(loaded_model, BioacousticModel)

    x = torch.randn(2, 1, 128, 216)
    out = loaded_model(x)
    assert out.shape == (2, 15)
    assert not torch.isnan(out).any()


def test_load_checkpoint_model_resnet34d(tmp_path):
    """Verifica que load_checkpoint_model cargue sin error un checkpoint con model_type='resnet34d'."""
    from poc.evaluate import load_checkpoint_model
    from poc.train import BioacousticModel

    classes = [f"Especie_{i}" for i in range(15)]
    model = BioacousticModel(
        model_name="resnet34d",
        num_classes=len(classes),
        pretrained=False,
        pool_type="avg",
    )
    ckpt_path = tmp_path / "resnet34d_checkpoint.pt"
    torch.save(
        {
            "model_type": "resnet34d",
            "classes": classes,
            "pool_type": "avg",
            "model_state_dict": model.state_dict(),
        },
        ckpt_path,
    )

    device = torch.device("cpu")
    loaded_model, ckpt_data = load_checkpoint_model(ckpt_path, device)

    assert ckpt_data["model_type"] == "resnet34d"
    assert ckpt_data["classes"] == classes
    assert isinstance(loaded_model, BioacousticModel)

    x = torch.randn(2, 1, 128, 216)
    out = loaded_model(x)
    assert out.shape == (2, 15)
    assert not torch.isnan(out).any()


def test_predict_audio_tta_micro_batching():
    """Genera un audio largo con 40+ ventanas y verifica que con max_window_batch_size=16
    devuelva idénticas probabilidades que sin micro-batching (o con batch completo)."""
    torch.manual_seed(42)
    np.random.seed(42)
    model = AudioCNN(num_classes=3)
    model.eval()

    # 45 segundos con hop=1.0s y duration=5.0s genera 41 ventanas
    long_audio = np.random.randn(int(TARGET_SR * 45.0)).astype(np.float32)

    # 1. Con batch completo (sin micro-batching o límite alto)
    pred_full, probs_full = predict_audio_tta(
        model=model,
        audio_input=long_audio,
        n_mels=64,
        mode="mean",
        device=torch.device("cpu"),
        hop_seconds=1.0,
        max_window_batch_size=64,
    )

    # 2. Con micro-batching (max_window_batch_size=16)
    pred_micro, probs_micro = predict_audio_tta(
        model=model,
        audio_input=long_audio,
        n_mels=64,
        mode="mean",
        device=torch.device("cpu"),
        hop_seconds=1.0,
        max_window_batch_size=16,
    )

    # 3. También en modo 'max'
    pred_max_full, probs_max_full = predict_audio_tta(
        model=model,
        audio_input=long_audio,
        n_mels=64,
        mode="max",
        device=torch.device("cpu"),
        hop_seconds=1.0,
        max_window_batch_size=64,
    )
    pred_max_micro, probs_max_micro = predict_audio_tta(
        model=model,
        audio_input=long_audio,
        n_mels=64,
        mode="max",
        device=torch.device("cpu"),
        hop_seconds=1.0,
        max_window_batch_size=16,
    )

    assert pred_full == pred_micro
    assert torch.allclose(probs_full, probs_micro, atol=1e-5)
    assert pred_max_full == pred_max_micro
    assert torch.allclose(probs_max_full, probs_max_micro, atol=1e-5)


def test_ensemble_classifier_arbitrary_weights():
    """Verifica que EnsembleClassifier aplique ponderaciones asimétricas [0.35, 0.65] con normalización estricta."""
    class MockModelA(nn.Module):
        def forward(self, x):
            return torch.tensor([[10.0, -10.0]])  # Clase 0 ~ 1.0, Clase 1 ~ 0.0

    class MockModelB(nn.Module):
        def forward(self, x):
            return torch.tensor([[-10.0, 10.0]])  # Clase 0 ~ 0.0, Clase 1 ~ 1.0

    mA = MockModelA()
    mB = MockModelB()
    ensemble = EnsembleClassifier([mA, mB], weights=[0.35, 0.65])

    assert pytest.approx(ensemble.weights[0]) == 0.35
    assert pytest.approx(ensemble.weights[1]) == 0.65

    dummy_x = torch.zeros(1, 1, 64, 216)
    out_logits = ensemble(dummy_x)
    probs = torch.softmax(out_logits, dim=-1)

    assert probs.shape == (1, 2)
    assert torch.isclose(probs[0, 0], torch.tensor(0.35), atol=1e-3)
    assert torch.isclose(probs[0, 1], torch.tensor(0.65), atol=1e-3)

    # Verificar también que ponderaciones proporcionales no normalizadas [35, 65] se normalicen a [0.35, 0.65]
    ens_unnorm = EnsembleClassifier([mA, mB], weights=[35.0, 65.0])
    assert pytest.approx(ens_unnorm.weights[0]) == 0.35
    assert pytest.approx(ens_unnorm.weights[1]) == 0.65


