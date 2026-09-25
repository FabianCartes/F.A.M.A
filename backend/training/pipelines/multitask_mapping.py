"""
backend/training/pipelines/multitask_mapping.py
Factorización de clases mecánicas monolíticas a atributos ortogonales multi-task y decodificación conjunta.
"""
from typing import List, Dict
import numpy as np
import torch


MECHANICAL_ATTRIBUTES: List[str] = [
    "has_oil_fault",
    "has_belt_fault",
    "has_steering_fault",
    "has_ignition_fault",
    "has_battery_fault",
    "has_brake_fault",
    "is_normal",
]

CLASS_NAMES_13: List[str] = [
    "bad_ignition",
    "dead_battery",
    "low_oil",
    "no oil_serpentine belt",
    "normal_brakes",
    "normal_engine_idle",
    "normal_engine_startup",
    "power steering combined_no oil",
    "power steering combined_no oil_serpentine belt",
    "power steering combined_serpentine belt",
    "power_steering",
    "serpentine_belt",
    "worn_out_brakes",
]

# Tabla de verdad ontológica de componentes mecánicos para cada una de las 13 clases
_CLASS_TO_ATTRIBUTES_MAP: Dict[str, Dict[str, float]] = {
    "bad_ignition": {"has_ignition_fault": 1.0},
    "dead_battery": {"has_battery_fault": 1.0},
    "low_oil": {"has_oil_fault": 1.0},
    "no oil_serpentine belt": {"has_oil_fault": 1.0, "has_belt_fault": 1.0},
    "normal_brakes": {"is_normal": 1.0},
    "normal_engine_idle": {"is_normal": 1.0},
    "normal_engine_startup": {"is_normal": 1.0},
    "power steering combined_no oil": {"has_steering_fault": 1.0, "has_oil_fault": 1.0},
    "power steering combined_no oil_serpentine belt": {"has_steering_fault": 1.0, "has_oil_fault": 1.0, "has_belt_fault": 1.0},
    "power steering combined_serpentine belt": {"has_steering_fault": 1.0, "has_belt_fault": 1.0},
    "power_steering": {"has_steering_fault": 1.0},
    "serpentine_belt": {"has_belt_fault": 1.0},
    "worn_out_brakes": {"has_brake_fault": 1.0},
}


def encode_class_to_attributes(clase: str) -> np.ndarray:
    """Convierte el nombre de una clase diagnóstica a un vector binario de atributos mecánicos."""
    vec = np.zeros(len(MECHANICAL_ATTRIBUTES), dtype=np.float32)
    attr_dict = _CLASS_TO_ATTRIBUTES_MAP.get(clase, {})
    for i, attr in enumerate(MECHANICAL_ATTRIBUTES):
        if attr_dict.get(attr, 0.0) == 1.0:
            vec[i] = 1.0
    return vec


# Matriz de compatibilidad precalculada [13, num_attributes]
CLASS_ATTRIBUTE_MATRIX: np.ndarray = np.array(
    [encode_class_to_attributes(c) for c in CLASS_NAMES_13],
    dtype=np.float32,
)


def build_multitask_targets_batch(batch_classes: List[str]) -> torch.Tensor:
    """Construye un tensor PyTorch [B, num_attributes] para supervisar la cabeza auxiliar multi-task."""
    vectors = [encode_class_to_attributes(c) for c in batch_classes]
    return torch.tensor(np.array(vectors), dtype=torch.float32)


def decode_joint_predictions(
    class_logits: torch.Tensor,
    attr_logits: torch.Tensor,
    alpha_prior: float = 0.3,
    return_probs: bool = False,
):
    """
    Decodifica predicciones conjuntas usando compatibilidad de atributos para reforzar clases compuestas.
    P_joint(c) = (1 - alpha) * Softmax(class_logits) + alpha * Compatibility(c, Sigmoid(attr_logits))
    Si return_probs=True, retorna tupla (preds, fused_probs).
    """
    with torch.no_grad():
        class_probs = torch.softmax(class_logits, dim=-1).cpu().numpy()  # [B, 13]
        attr_probs = torch.sigmoid(attr_logits).cpu().numpy()            # [B, A]

        matrix = CLASS_ATTRIBUTE_MATRIX  # [13, A]
        bsz = class_probs.shape[0]

        # Similitud coseno o producto punto normalizado entre atributos predichos y la matriz de clases
        # comp_scores: [B, 13]
        # P_attr(c) proporcional a cuán cerca están los atributos observados del prototipo de la clase c
        comp_scores = np.zeros((bsz, len(CLASS_NAMES_13)), dtype=np.float32)
        for c_idx in range(len(CLASS_NAMES_13)):
            proto = matrix[c_idx]  # [A]
            # Probabilidad de coincidencia binaria
            match_prob = np.prod(
                attr_probs * proto + (1.0 - attr_probs) * (1.0 - proto),
                axis=1
            )
            comp_scores[:, c_idx] = match_prob

        # Normalizar scores de compatibilidad por fila
        row_sums = comp_scores.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        comp_probs = comp_scores / row_sums

        fused_probs = (1.0 - alpha_prior) * class_probs + alpha_prior * comp_probs
        # Normalizar fused_probs para garantizar suma = 1.0
        f_sums = fused_probs.sum(axis=1, keepdims=True)
        f_sums[f_sums == 0] = 1.0
        fused_probs = fused_probs / f_sums

        preds = np.argmax(fused_probs, axis=-1)
        if return_probs:
            return preds, fused_probs
        return preds
