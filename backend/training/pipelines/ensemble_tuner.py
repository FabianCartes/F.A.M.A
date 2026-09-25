"""
backend/training/pipelines/ensemble_tuner.py
Tuning de calibración por temperatura y ponderación de ensamble restringido estrictamente a validación.
"""
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, classification_report

from training.pipelines.test_guard import compute_expected_calibration_error, guard_against_test_tuning


@dataclass
class EnsembleCalibrationResult:
    optimal_weights: List[float]
    optimal_temperatures: List[float]
    val_accuracy: float
    val_macro_f1: float
    val_ece: float
    classes: List[str]


def tune_ensemble_calibration(
    models: List[nn.Module],
    val_loader: DataLoader,
    frontend: nn.Module,
    device: torch.device,
    classes: List[str],
    temperatures_grid: Optional[List[float]] = None,
    weights_grid: Optional[List[Tuple[float, ...]]] = None,
) -> EnsembleCalibrationResult:
    """
    Optimiza temperaturas de calibración y pesos de ensamble EXCLUSIVAMENTE sobre el conjunto de validación.
    """
    guard_against_test_tuning("val")

    if temperatures_grid is None:
        temperatures_grid = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]

    num_models = len(models)
    if weights_grid is None:
        if num_models == 1:
            weights_grid = [(1.0,)]
        elif num_models == 2:
            weights_grid = [
                (round(w, 2), round(1.0 - w, 2))
                for w in np.linspace(0.1, 0.9, 9)
            ]
        else:
            weights_grid = [tuple([1.0 / num_models] * num_models)]

    for m in models:
        m.eval()

    # 1. Extraer logits crudos de todos los modelos sobre el loader de validación
    model_logits: List[List[torch.Tensor]] = [[] for _ in range(num_models)]
    targets_list: List[int] = []

    with torch.no_grad():
        for x_batch, y_batch in val_loader:
            x_batch = x_batch.to(device)
            # Aplicar frontend si el modelo no procesa tensores crudos
            features = frontend(x_batch) if frontend is not None else x_batch

            for i, m in enumerate(models):
                out = m(features)
                model_logits[i].append(out.cpu())

            targets_list.extend(y_batch.numpy() if hasattr(y_batch, "numpy") else list(y_batch))

    all_logits = [torch.cat(m_l, dim=0) for m_l in model_logits]
    targets = np.array(targets_list)

    best_f1 = -1.0
    best_acc = 0.0
    best_weights: List[float] = list(weights_grid[0])
    best_temperatures: List[float] = [1.0] * num_models
    best_ece = 1.0

    # 2. Búsqueda de grid search sobre validación
    # Si son 2 modelos, evaluamos combinaciones de T1, T2
    if num_models == 2:
        for t1 in temperatures_grid:
            p1 = torch.softmax(all_logits[0] / t1, dim=-1).numpy()
            for t2 in temperatures_grid:
                p2 = torch.softmax(all_logits[1] / t2, dim=-1).numpy()

                for w_tuple in weights_grid:
                    w1, w2 = w_tuple
                    probs_ens = w1 * p1 + w2 * p2
                    preds = np.argmax(probs_ens, axis=-1)

                    acc = float(accuracy_score(targets, preds))
                    _, _, f1, _ = precision_recall_fscore_support(targets, preds, average="macro", zero_division=0)
                    ece = compute_expected_calibration_error(probs_ens, targets)

                    if f1 > best_f1:
                        best_f1 = float(f1)
                        best_acc = acc
                        best_weights = [float(w1), float(w2)]
                        best_temperatures = [float(t1), float(t2)]
                        best_ece = ece
    else:
        # Caso general (1 modelo o N modelos)
        for t in temperatures_grid:
            probs = [torch.softmax(lg / t, dim=-1).numpy() for lg in all_logits]
            for w_tuple in weights_grid:
                probs_ens = sum(w * p for w, p in zip(w_tuple, probs))
                preds = np.argmax(probs_ens, axis=-1)

                acc = float(accuracy_score(targets, preds))
                _, _, f1, _ = precision_recall_fscore_support(targets, preds, average="macro", zero_division=0)
                ece = compute_expected_calibration_error(probs_ens, targets)

                if f1 > best_f1:
                    best_f1 = float(f1)
                    best_acc = acc
                    best_weights = [float(w) for w in w_tuple]
                    best_temperatures = [float(t)] * num_models
                    best_ece = ece

    return EnsembleCalibrationResult(
        optimal_weights=best_weights,
        optimal_temperatures=best_temperatures,
        val_accuracy=round(best_acc, 4),
        val_macro_f1=round(best_f1, 4),
        val_ece=round(best_ece, 4),
        classes=classes,
    )


def evaluate_calibrated_ensemble(
    models: List[nn.Module],
    calibration_result: EnsembleCalibrationResult,
    data_loader: DataLoader,
    frontend: nn.Module,
    device: torch.device,
    classes: List[str],
) -> Dict[str, Any]:
    """
    Evaluación ciega (zero-tuning) aplicando los parámetros calibrados congelados.
    """
    for m in models:
        m.eval()

    num_models = len(models)
    model_logits: List[List[torch.Tensor]] = [[] for _ in range(num_models)]
    targets_list: List[int] = []

    with torch.no_grad():
        for x_batch, y_batch in data_loader:
            x_batch = x_batch.to(device)
            features = frontend(x_batch) if frontend is not None else x_batch

            for i, m in enumerate(models):
                out = m(features)
                model_logits[i].append(out.cpu())

            targets_list.extend(y_batch.numpy() if hasattr(y_batch, "numpy") else list(y_batch))

    all_logits = [torch.cat(m_l, dim=0) for m_l in model_logits]
    targets = np.array(targets_list)

    # Aplicar calibración congelada
    calibrated_probs = [
        torch.softmax(lg / temp, dim=-1).numpy()
        for lg, temp in zip(all_logits, calibration_result.optimal_temperatures)
    ]

    ensemble_probs = sum(
        w * p for w, p in zip(calibration_result.optimal_weights, calibrated_probs)
    )
    preds = np.argmax(ensemble_probs, axis=-1)

    acc = float(accuracy_score(targets, preds))
    _, _, f1_macro, _ = precision_recall_fscore_support(targets, preds, average="macro", zero_division=0)
    ece = compute_expected_calibration_error(ensemble_probs, targets)
    report = classification_report(targets, preds, target_names=classes, output_dict=True, zero_division=0)

    return {
        "accuracy": round(acc, 4),
        "macro_f1": round(float(f1_macro), 4),
        "ece": round(ece, 4),
        "per_class_report": report,
        "calibration_used": {
            "weights": calibration_result.optimal_weights,
            "temperatures": calibration_result.optimal_temperatures,
        },
    }
