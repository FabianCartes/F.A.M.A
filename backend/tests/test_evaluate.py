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
from poc.evaluate import evaluate_test_set, compute_metrics_and_matrix, predict_audio_tta


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

