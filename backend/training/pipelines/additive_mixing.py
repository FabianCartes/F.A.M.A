"""
backend/training/pipelines/additive_mixing.py
Síntesis aditiva física de fallas mecánicas compuestas a partir de formas de onda unitarias aisladas.
Basado en el principio de superposición acústica lineal en presión sonora.
"""
from pathlib import Path
from typing import List, Dict, Optional, Mapping, Union
import random
import numpy as np
import pandas as pd

from training.pipelines.dataset import load_and_resample
from dataset_references import resolve_reference


COMPOSITE_RECIPES: Dict[str, List[str]] = {
    "no oil_serpentine belt": ["low_oil", "serpentine_belt"],
    "power steering combined_serpentine belt": ["power_steering", "serpentine_belt"],
    "power steering combined_no oil": ["power_steering", "low_oil"],
    "power steering combined_no oil_serpentine belt": [
        "power_steering",
        "low_oil",
        "serpentine_belt",
    ],
}


def mix_additive_waveforms(
    waveforms: List[np.ndarray],
    gains: Optional[List[float]] = None,
    max_shift_samples: int = 0,
    balance_rms: bool = True,
    target_rms: float = 0.10,
) -> np.ndarray:
    """
    Suma de forma aditiva múltiples señales acústicas unitarias, aplicando ganancias aleatorias,
    balanceo de potencia acústica RMS para evitar enmascaramiento de fallas sutiles,
    desplazamientos temporales independientes y prevención de recorte digital (clipping).
    """
    if not waveforms:
        return np.zeros(0, dtype=np.float32)

    target_len = len(waveforms[0])
    if gains is None:
        gains = [random.uniform(0.7, 1.3) for _ in waveforms]

    accumulated = np.zeros(target_len, dtype=np.float32)

    for w, g in zip(waveforms, gains):
        w_curr = np.copy(w).astype(np.float32)
        if len(w_curr) != target_len:
            if len(w_curr) < target_len:
                w_curr = np.pad(w_curr, (0, target_len - len(w_curr)))
            else:
                w_curr = w_curr[:target_len]

        if balance_rms:
            rms = float(np.sqrt(np.mean(w_curr ** 2)))
            if rms > 1e-5:
                w_curr = (w_curr / rms) * target_rms

        if max_shift_samples > 0:
            shift = random.randint(-max_shift_samples, max_shift_samples)
            w_curr = np.roll(w_curr, shift)

        accumulated += g * w_curr

    # Prevención estricta de recorte digital (Peak Normalization a 0.95)
    max_val = float(np.max(np.abs(accumulated)))
    if max_val > 0.98:
        accumulated = (accumulated / max_val) * 0.95

    return accumulated.astype(np.float32)


class AdditiveCompoundSampler:
    """
    Muestreador de síntesis física de fallas compuestas.
    Permite generar pares acústicos sintéticos de alta fidelidad para clases multi-falla deficitarias.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        target_sr: int = 32000,
        duration_seconds: float = 2.0,
        *,
        roots: Mapping[str, Union[str, Path]],
    ):
        self.target_sr = target_sr
        self.duration_seconds = duration_seconds
        self.roots = dict(roots)
        self.df = df.copy(deep=True).reset_index(drop=True)
        if not {"file_path", "file_stage"}.issubset(self.df.columns):
            raise ValueError("file_path and file_stage required; convert the index offline")
        self.class_to_paths: Dict[str, List[dict]] = {}

        for row in self.df.to_dict("records"):
            resolve_reference(row["file_path"], row["file_stage"], self.roots)
            c = str(row.get("clase", "")).strip()
            if c:
                self.class_to_paths.setdefault(c, []).append(row)

    def can_synthesize(self, composite_class: str) -> bool:
        """Determina si se cuenta con archivos de todas las clases constitutivas para sintetizar."""
        if composite_class not in COMPOSITE_RECIPES:
            return False
        required_classes = COMPOSITE_RECIPES[composite_class]
        return all(len(self.class_to_paths.get(req, [])) > 0 for req in required_classes)

    def sample_synthetic_compound(self, composite_class: str) -> Optional[np.ndarray]:
        """Sintetiza una forma de onda combinada tomando aleatoriamente un audio de cada componente unitaria."""
        if not self.can_synthesize(composite_class):
            return None

        required_classes = COMPOSITE_RECIPES[composite_class]
        unit_waveforms: List[np.ndarray] = []

        for req in required_classes:
            row = random.choice(self.class_to_paths[req])
            # Revalidate original spelling on every access, before decoder caches.
            chosen_path = resolve_reference(row["file_path"], row["file_stage"], self.roots)
            wave = load_and_resample(
                file_path=chosen_path,
                target_sr=self.target_sr,
                duration_seconds=self.duration_seconds,
            )
            unit_waveforms.append(wave)

        # Desplazamiento máximo de 0.1s para evitar sincronización artificial
        max_shift = int(self.target_sr * 0.10)
        return mix_additive_waveforms(unit_waveforms, max_shift_samples=max_shift)


def build_balanced_class_sampler(
    df: pd.DataFrame,
    class_col: str = "clase",
):
    """
    Construye un WeightedRandomSampler que balancea de manera uniforme la probabilidad
    de extracción de cada clase por lote. Al combinarse con AdditiveCompoundSampler,
    cada extracción de una clase compuesta genera una nueva mezcla física única.
    """
    import torch
    from torch.utils.data import WeightedRandomSampler

    class_counts = df[class_col].value_counts()
    sample_weights = df[class_col].map(lambda c: 1.0 / float(class_counts[c])).values
    weights_tensor = torch.tensor(sample_weights, dtype=torch.float)
    return WeightedRandomSampler(
        weights=weights_tensor,
        num_samples=len(df),
        replacement=True,
    )

