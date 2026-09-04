from pathlib import Path
import torch
import torch.nn as nn
import pandas as pd
import numpy as np
import pytest

from poc.train import AudioCNN
from poc.evaluate import evaluate_test_set, compute_metrics_and_matrix

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
