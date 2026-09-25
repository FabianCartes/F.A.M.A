"""
backend/tests/test_multitask_mapping.py
Pruebas unitarias para el mapeo y factorización multi-task de clases diagnósticas automotrices.
"""
import pytest
import numpy as np
import torch

from training.pipelines.multitask_mapping import (
    MECHANICAL_ATTRIBUTES,
    CLASS_NAMES_13,
    encode_class_to_attributes,
    build_multitask_targets_batch,
    decode_joint_predictions,
)


def test_mechanical_attributes_definition():
    # Debe contar con atributos ortogonales para los subsistemas clave
    expected_attrs = [
        "has_oil_fault",
        "has_belt_fault",
        "has_steering_fault",
        "has_ignition_fault",
        "has_battery_fault",
        "has_brake_fault",
        "is_normal",
    ]
    assert MECHANICAL_ATTRIBUTES == expected_attrs
    assert len(CLASS_NAMES_13) == 13


def test_encode_class_to_attributes_single_faults():
    # Falla de aceite individual
    oil_vec = encode_class_to_attributes("low_oil")
    assert oil_vec.shape == (len(MECHANICAL_ATTRIBUTES),)
    # has_oil_fault debe ser 1, los demás fallos 0, is_normal 0
    assert oil_vec[0] == 1.0
    assert oil_vec[1] == 0.0
    assert oil_vec[-1] == 0.0

    # Batería descargada
    battery_vec = encode_class_to_attributes("dead_battery")
    # has_battery_fault es el índice 4
    assert battery_vec[4] == 1.0
    assert battery_vec[0] == 0.0
    assert battery_vec[-1] == 0.0

    # Normal idle
    idle_vec = encode_class_to_attributes("normal_engine_idle")
    assert idle_vec[-1] == 1.0
    assert np.sum(idle_vec[:-1]) == 0.0


def test_encode_class_to_attributes_composite_faults():
    # power steering combined_no oil_serpentine belt: debe activar dirección, aceite y correa
    combo_triple = encode_class_to_attributes("power steering combined_no oil_serpentine belt")
    assert combo_triple[0] == 1.0  # oil
    assert combo_triple[1] == 1.0  # belt
    assert combo_triple[2] == 1.0  # steering
    assert combo_triple[3] == 0.0  # ignition
    assert combo_triple[-1] == 0.0  # normal

    # no oil_serpentine belt: debe activar aceite y correa
    combo_double = encode_class_to_attributes("no oil_serpentine belt")
    assert combo_double[0] == 1.0  # oil
    assert combo_double[1] == 1.0  # belt
    assert combo_double[2] == 0.0  # steering


def test_build_multitask_targets_batch():
    batch_classes = ["low_oil", "serpentine_belt", "normal_engine_idle"]
    targets_tensor = build_multitask_targets_batch(batch_classes)
    assert targets_tensor.shape == (3, len(MECHANICAL_ATTRIBUTES))
    assert targets_tensor.dtype == torch.float32


def test_decode_joint_predictions_favors_constrained_consistency():
    # Verificamos que decode_joint_predictions reciba logits de 13 clases y logits de atributos
    # y produzca predicciones válidas
    bsz = 2
    class_logits = torch.zeros(bsz, 13)
    attr_logits = torch.zeros(bsz, len(MECHANICAL_ATTRIBUTES))

    # Forzamos que la muestra 0 tenga alta probabilidad en los atributos oil y belt
    attr_logits[0, 0] = 5.0  # oil
    attr_logits[0, 1] = 5.0  # belt

    preds = decode_joint_predictions(class_logits, attr_logits, alpha_prior=0.3)
    assert len(preds) == bsz
    assert 0 <= preds[0] < 13

    preds_with_p, probs = decode_joint_predictions(class_logits, attr_logits, alpha_prior=0.3, return_probs=True)
    assert np.array_equal(preds, preds_with_p)
    assert probs.shape == (bsz, 13)
    assert np.allclose(probs.sum(axis=-1), 1.0, atol=1e-5)
