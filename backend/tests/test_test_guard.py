"""
backend/tests/test_test_guard.py
Pruebas de higiene metodológica para congelamiento de test set y prevención de fuga de tuning.
"""
import pytest
from pathlib import Path
import numpy as np
import torch

from training.pipelines.test_guard import (
    verify_test_set_integrity,
    guard_against_test_tuning,
    compute_expected_calibration_error,
    TestIntegrityViolationError,
    TestLeakageError,
    FROZEN_ENGINE_TEST_SHA256,
)


def test_test_set_integrity_verified_with_frozen_hash(tmp_path):
    test_file = tmp_path / "test_metadata.csv"
    test_file.write_text("dummy,test,header\n1,2,3\n", encoding="utf-8")
    import hashlib
    expected_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()

    # Debe pasar sin excepciones
    assert verify_test_set_integrity(test_file, expected_sha256=expected_hash) is True


def test_test_set_integrity_fails_when_tampered(tmp_path):
    test_file = tmp_path / "test_metadata.csv"
    test_file.write_text("original content", encoding="utf-8")

    with pytest.raises(TestIntegrityViolationError):
        verify_test_set_integrity(test_file, expected_sha256="badhash1234567890abcdef")


def test_guard_against_test_tuning_raises_on_test_split():
    # Split permitido (val o train)
    guard_against_test_tuning("val")
    guard_against_test_tuning("validation")
    guard_against_test_tuning("train")

    # Split prohibido para tuning
    with pytest.raises(TestLeakageError, match="Tuning prohibido sobre el conjunto de prueba"):
        guard_against_test_tuning("test")

    with pytest.raises(TestLeakageError):
        guard_against_test_tuning("test_set")


def test_compute_expected_calibration_error_properties():
    # Modelo perfectamente calibrado (confianza = probabilidad real)
    # Por ejemplo, 100% confiado y 100% acertado
    probs = np.array([
        [1.0, 0.0],
        [1.0, 0.0],
        [0.0, 1.0],
        [0.0, 1.0],
    ])
    targets = np.array([0, 0, 1, 1])

    ece = compute_expected_calibration_error(probs, targets, n_bins=5)
    assert 0.0 <= ece < 0.01  # ECE prácticamente cero

    # Modelo descalibrado (sobreconfiado en predicciones erróneas)
    bad_probs = np.array([
        [0.99, 0.01],
        [0.99, 0.01],
        [0.99, 0.01],
        [0.99, 0.01],
    ])
    wrong_targets = np.array([1, 1, 1, 1])
    bad_ece = compute_expected_calibration_error(bad_probs, wrong_targets, n_bins=5)
    assert bad_ece > 0.80  # ECE muy alto por sobreconfianza errónea
