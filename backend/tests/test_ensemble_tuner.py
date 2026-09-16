"""
backend/tests/test_ensemble_tuner.py
Pruebas de TDD para optimización de calibración por temperatura y ensamble exclusivamente en validación.
"""
import pytest
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from training.pipelines.ensemble_tuner import (
    EnsembleCalibrationResult,
    tune_ensemble_calibration,
    evaluate_calibrated_ensemble,
)
from training.pipelines.test_guard import TestLeakageError


class DummyAcousticModel(nn.Module):
    def __init__(self, logits_matrix: torch.Tensor):
        super().__init__()
        self.logits = nn.Parameter(logits_matrix.clone(), requires_grad=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Devuelve logits preconfigurados según el batch
        indices = x[:, 0, 0, 0].long()
        return self.logits[indices]


def test_tune_ensemble_calibration_selects_best_val_parameters():
    # 4 muestras, 2 clases
    classes = ["normal", "fault"]
    # Modelo 1: logits medianamente buenos
    m1_logits = torch.tensor([
        [2.0, -1.0],  # clase 0
        [1.5, -0.5],  # clase 0
        [-1.0, 2.0],  # clase 1
        [-0.5, 1.5],  # clase 1
    ])
    # Modelo 2: logits ruidosos
    m2_logits = torch.tensor([
        [0.1, -0.1],
        [-0.2, 0.2],
        [0.0, 1.0],
        [-0.1, 0.5],
    ])

    m1 = DummyAcousticModel(m1_logits)
    m2 = DummyAcousticModel(m2_logits)

    # Loader sintético: tensor con índices 0, 1, 2, 3
    x = torch.tensor([[[[0.0]]], [[[1.0]]], [[[2.0]]], [[[3.0]]]])
    y = torch.tensor([0, 0, 1, 1])
    loader = DataLoader(TensorDataset(x, y), batch_size=2, shuffle=False)

    device = torch.device("cpu")
    # Frontend nulo (función identidad)
    frontend = nn.Identity()

    result = tune_ensemble_calibration(
        models=[m1, m2],
        val_loader=loader,
        frontend=frontend,
        device=device,
        classes=classes,
        temperatures_grid=[0.8, 1.0, 1.2],
        weights_grid=[(1.0, 0.0), (0.8, 0.2), (0.5, 0.5)],
    )

    assert isinstance(result, EnsembleCalibrationResult)
    assert len(result.optimal_weights) == 2
    assert sum(result.optimal_weights) == pytest.approx(1.0)
    assert result.val_accuracy == 1.0
    assert result.val_macro_f1 == 1.0
    assert result.val_ece >= 0.0


def test_evaluate_calibrated_ensemble_blind_evaluation():
    classes = ["c0", "c1"]
    m_logits = torch.tensor([
        [3.0, -3.0],
        [-3.0, 3.0],
    ])
    m = DummyAcousticModel(m_logits)
    x = torch.tensor([[[[0.0]]], [[[1.0]]]])
    y = torch.tensor([0, 1])
    test_loader = DataLoader(TensorDataset(x, y), batch_size=2, shuffle=False)

    calib = EnsembleCalibrationResult(
        optimal_weights=[1.0],
        optimal_temperatures=[1.0],
        val_accuracy=1.0,
        val_macro_f1=1.0,
        val_ece=0.01,
        classes=classes,
    )

    eval_out = evaluate_calibrated_ensemble(
        models=[m],
        calibration_result=calib,
        data_loader=test_loader,
        frontend=nn.Identity(),
        device=torch.device("cpu"),
        classes=classes,
    )

    assert eval_out["accuracy"] == 1.0
    assert eval_out["macro_f1"] == 1.0
    assert "ece" in eval_out
    assert "per_class_report" in eval_out
