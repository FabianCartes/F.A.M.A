"""
backend/training/pipelines/dataset.py
Dataset de PyTorch desacoplado de constantes globales, parametrizado mediante AudioConfig.
"""
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Union
import random
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset
import librosa

from training.schemas.config import AudioConfig, AugmentationConfig


def load_and_resample(file_path: Union[str, Path], target_sr: int, duration_seconds: float) -> np.ndarray:
    """Carga y ajusta el largo del audio a la tasa de muestreo y duración solicitada."""
    target_samples = int(target_sr * duration_seconds)
    try:
        y, sr = librosa.load(file_path, sr=target_sr, mono=True)
    except Exception:
        return np.zeros(target_samples, dtype=np.float32)

    if len(y) < target_samples:
        padding = target_samples - len(y)
        y = np.pad(y, (0, padding), mode="constant")
    elif len(y) > target_samples:
        y = y[:target_samples]

    return y.astype(np.float32)


class GenericAudioDataset(Dataset):
    """
    Dataset bioacústico parametrizable.
    Soporta frecuencias arbitrarias (22.05kHz, 32kHz), duraciones personalizadas,
    clasificación single-label o multi-label y evaluación determinista.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        audio_config: AudioConfig,
        label_to_idx: Dict[str, int],
        augmentation_config: Optional[AugmentationConfig] = None,
        is_train: bool = False,
        multilabel: bool = False,
        return_raw_waveform: bool = True,
    ):
        self.df = df.reset_index(drop=True)
        self.audio_config = audio_config
        self.label_to_idx = label_to_idx
        self.aug_config = augmentation_config or AugmentationConfig()
        self.is_train = is_train
        self.multilabel = multilabel
        self.return_raw_waveform = return_raw_waveform
        self.num_classes = len(label_to_idx)

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        row = self.df.iloc[idx]
        file_path = row.get("file_path", "")

        waveform = load_and_resample(
            file_path=file_path,
            target_sr=self.audio_config.target_sr,
            duration_seconds=self.audio_config.duration_seconds,
        )

        # Transformaciones estocásticas SOLO en entrenamiento
        if self.is_train:
            if random.random() < self.aug_config.gain_prob:
                gain = random.uniform(*self.aug_config.gain_range)
                waveform = (waveform * gain).astype(np.float32)

            if random.random() < self.aug_config.noise_prob:
                noise_factor = random.uniform(*self.aug_config.noise_factor_range)
                noise = np.random.randn(*waveform.shape).astype(np.float32) * noise_factor
                waveform = waveform + noise

        waveform_tensor = torch.from_numpy(waveform).float()

        # Generar etiquetas
        if self.multilabel:
            label_vec = torch.zeros(self.num_classes, dtype=torch.float32)
            labels = row.get("labels", [])
            if isinstance(labels, str):
                labels = [s.strip().strip("'\"") for s in labels.strip("[]").split(",") if s.strip()]
            if not labels:
                labels = [str(row.get("clase", ""))]

            for lbl in labels:
                if lbl in self.label_to_idx:
                    label_vec[self.label_to_idx[lbl]] = 1.0
            return waveform_tensor, label_vec
        else:
            clase = str(row.get("clase", ""))
            label_idx = self.label_to_idx.get(clase, 0)
            return waveform_tensor, torch.tensor(label_idx, dtype=torch.long)
