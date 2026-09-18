"""
backend/training/pipelines/additive_mixing.py
Síntesis aditiva física de fallas mecánicas compuestas a partir de formas de onda unitarias aisladas.
Basado en el principio de superposición acústica lineal en presión sonora.
"""
from pathlib import Path
from typing import List, Dict, Optional
import random
import numpy as np
import pandas as pd

from training.pipelines.dataset import load_and_resample


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
) -> np.ndarray:
    """
    Suma de forma aditiva múltiples señales acústicas unitarias, aplicando ganancias aleatorias,
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
    ):
        self.target_sr = target_sr
        self.duration_seconds = duration_seconds
        self.class_to_paths: Dict[str, List[str]] = {}

        for _, row in df.iterrows():
            c = str(row.get("clase", "")).strip()
            p = str(row.get("file_path", "")).strip()
            if c and p:
                if c not in self.class_to_paths:
                    self.class_to_paths[c] = []
                self.class_to_paths[c].append(p)

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
            chosen_path = random.choice(self.class_to_paths[req])
            wave = load_and_resample(
                file_path=chosen_path,
                target_sr=self.target_sr,
                duration_seconds=self.duration_seconds,
            )
            unit_waveforms.append(wave)

        # Desplazamiento máximo de 0.1s para evitar sincronización artificial
        max_shift = int(self.target_sr * 0.10)
        return mix_additive_waveforms(unit_waveforms, max_shift_samples=max_shift)
