"""
backend/training/pipelines/test_guard.py
Módulo de gobernanza e higiene metodológica para prevenir fuga de datos y sobreajuste del conjunto de prueba.
"""
from pathlib import Path
from typing import Union, Optional
import hashlib
import numpy as np


FROZEN_ENGINE_TEST_SHA256 = "9d587189434b41b27d55de43aa86f50312f0b5d300d437b03cc3ecae52c153d2"


class TestIntegrityViolationError(RuntimeError):
    """Lanzada cuando el conjunto de prueba ha sido modificado o no coincide con el hash criptográfico congelado."""
    __test__ = False


class TestLeakageError(RuntimeError):
    """Lanzada cuando se intenta ejecutar una optimización o tuning de hiperparámetros sobre el conjunto de prueba."""
    __test__ = False


def verify_test_set_integrity(
    test_csv_path: Union[str, Path],
    expected_sha256: Optional[str] = None,
) -> bool:
    """
    Verifica que el archivo de metadata del conjunto de prueba exista y su hash SHA-256 coincida exactamente.
    """
    path = Path(test_csv_path)
    if not path.exists():
        raise TestIntegrityViolationError(f"El archivo de test set no existe en: {path}")

    target_hash = expected_sha256 if expected_sha256 is not None else FROZEN_ENGINE_TEST_SHA256
    current_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    if current_hash != target_hash:
        raise TestIntegrityViolationError(
            f"Fallo de integridad criptográfica en test set ({path}).\n"
            f"Esperado: {target_hash}\n"
            f"Obtenido: {current_hash}\n"
            f"¡El conjunto de prueba fue modificado o corrompido!"
        )

    return True


def guard_against_test_tuning(split_name: str) -> None:
    """
    Bloquea categóricamente cualquier intento de ajustar pesos, umbrales o hiperparámetros sobre el split de prueba.
    """
    normalized = str(split_name).strip().lower().replace("-", "_")
    forbidden = {"test", "test_set", "testing", "eval_test"}
    if normalized in forbidden:
        raise TestLeakageError(
            f"Violación metodológica grave: Tuning prohibido sobre el conjunto de prueba ('{split_name}'). "
            "Cualquier búsqueda de hiperparámetros (pesos, temperatura, thresholds) debe ejecutarse únicamente "
            "sobre validación ('val' o OOF cross-validation)."
        )


def compute_expected_calibration_error(
    probs: np.ndarray,
    targets: np.ndarray,
    n_bins: int = 10,
) -> float:
    """
    Calcula el Expected Calibration Error (ECE) para medir la fiabilidad de las probabilidades predichas.
    ECE = sum_{b=1}^B (|B_b| / N) * |acc(B_b) - conf(B_b)|
    """
    probs = np.asarray(probs)
    targets = np.asarray(targets)

    if probs.ndim != 2:
        raise ValueError(f"probs debe ser una matriz 2D [N, C], recibido ndim={probs.ndim}")

    confidences = np.max(probs, axis=1)
    predictions = np.argmax(probs, axis=1)
    accuracies = (predictions == targets)

    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n_samples = len(targets)

    if n_samples == 0:
        return 0.0

    for i in range(n_bins):
        bin_lower = bin_boundaries[i]
        bin_upper = bin_boundaries[i + 1]

        if i == n_bins - 1:
            in_bin = (confidences >= bin_lower) & (confidences <= bin_upper)
        else:
            in_bin = (confidences >= bin_lower) & (confidences < bin_upper)

        bin_size = int(np.sum(in_bin))
        if bin_size > 0:
            bin_acc = float(np.mean(accuracies[in_bin]))
            bin_conf = float(np.mean(confidences[in_bin]))
            ece += (bin_size / n_samples) * abs(bin_acc - bin_conf)

    return float(ece)
