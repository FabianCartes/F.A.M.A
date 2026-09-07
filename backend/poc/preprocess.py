from pathlib import Path
from typing import Union, Optional, List
import numpy as np
import librosa
import soundfile as sf
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio.transforms as T

TARGET_SR = 22050
DURATION_SECONDS = 5.0
TARGET_SAMPLES = int(TARGET_SR * DURATION_SECONDS)  # 110250


def compute_rms(waveform: np.ndarray) -> float:
    """
    Calcula la raíz cuadrática media (Root Mean Square - RMS) de una señal.
    Representa la energía acústica efectiva de la forma de onda.
    """
    if len(waveform) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64))))


def load_and_fix_length(
    audio_input: Union[str, Path, np.ndarray],
    target_sr: int = TARGET_SR,
    duration_seconds: float = DURATION_SECONDS,
    original_sr: Optional[int] = None,
) -> np.ndarray:
    """
    Carga un archivo o array de audio, lo convierte a mono, remuestrea a target_sr
    y lo recorta o rellena (zero-padding) a exactamente target_sr * duration_seconds muestras.
    """
    target_samples = int(target_sr * duration_seconds)

    if isinstance(audio_input, (str, Path)):
        y, _ = librosa.load(str(audio_input), sr=target_sr, mono=True)
    elif isinstance(audio_input, np.ndarray):
        y = audio_input.astype(np.float32)
        if y.ndim > 1:
            y = np.mean(y, axis=0)  # mono
        if original_sr is not None and original_sr != target_sr:
            y = librosa.resample(y, orig_sr=original_sr, target_sr=target_sr)
    else:
        raise TypeError(f"Tipo no soportado para audio_input: {type(audio_input)}")

    current_samples = len(y)
    if current_samples < target_samples:
        pad_width = target_samples - current_samples
        y = np.pad(y, (0, pad_width), mode="constant", constant_values=0.0)
    elif current_samples > target_samples:
        start_idx = (current_samples - target_samples) // 2
        y = y[start_idx : start_idx + target_samples]

    return y.astype(np.float32)


def extract_active_windows(
    audio_input: Union[str, Path, np.ndarray],
    target_sr: int = TARGET_SR,
    duration_seconds: float = DURATION_SECONDS,
    hop_seconds: float = 2.5,
    top_db: float = 25.0,
    min_energy: float = 1e-4,
    original_sr: Optional[int] = None,
) -> List[np.ndarray]:
    """
    Segmenta un audio largo en ventanas solapadas de longitud duration_seconds.
    Aplica detección de actividad vocal (VAD) basada en RMS energético relativo
    para descartar segmentos con silencio de fondo o ruido irrelevante.

    Parámetros:
    - audio_input: Ruta al archivo o array de audio.
    - target_sr: Frecuencia de muestreo estándar (22.050 Hz).
    - duration_seconds: Longitud de cada ventana (5.0 segundos = 110.250 muestras).
    - hop_seconds: Desplazamiento temporal (2.5 segundos = 50% solapamiento).
    - top_db: Umbral en decibelios bajo el cual una ventana se considera silencio
              en comparación con la ventana más energética de la grabación.
    - min_energy: Umbral absoluto de RMS mínimo para evitar considerar ruido
                  numérico como señal válida.
    """
    if hop_seconds <= 0:
        raise ValueError(f"hop_seconds debe ser mayor a 0, recibido: {hop_seconds}")

    target_samples = int(target_sr * duration_seconds)
    hop_samples = int(target_sr * hop_seconds)

    if isinstance(audio_input, (str, Path)):
        y, _ = librosa.load(str(audio_input), sr=target_sr, mono=True)
    elif isinstance(audio_input, np.ndarray):
        y = audio_input.astype(np.float32)
        if y.ndim > 1:
            y = np.mean(y, axis=0)
        if original_sr is not None and original_sr != target_sr:
            y = librosa.resample(y, orig_sr=original_sr, target_sr=target_sr)
    else:
        raise TypeError(f"Tipo no soportado para audio_input: {type(audio_input)}")

    current_samples = len(y)

    # Si el audio es más corto que la ventana objetivo, se rellena con ceros
    if current_samples < target_samples:
        pad_width = target_samples - current_samples
        padded = np.pad(y, (0, pad_width), mode="constant", constant_values=0.0).astype(np.float32)
        return [padded]

    # Generar ventanas candidatas
    candidates: List[np.ndarray] = []
    rms_values: List[float] = []

    start = 0
    while start + target_samples <= current_samples:
        window = y[start : start + target_samples].astype(np.float32)
        candidates.append(window)
        rms_values.append(compute_rms(window))
        start += hop_samples

    # Si sobró un fragmento significativo al final no cubierto
    if current_samples - (start - hop_samples + target_samples) > (target_samples // 4):
        tail_window = y[-target_samples:].astype(np.float32)
        candidates.append(tail_window)
        rms_values.append(compute_rms(tail_window))

    if not candidates:
        return [load_and_fix_length(y, target_sr, duration_seconds)]

    max_rms = max(rms_values)

    # Salvaguarda: si todo el archivo tiene energía casi nula
    if max_rms < min_energy:
        best_idx = int(np.argmax(rms_values))
        return [candidates[best_idx]]

    # Filtrar por VAD relativo (top_db respecto al pico)
    active_windows: List[np.ndarray] = []
    # threshold_rms = max_rms * 10^(-top_db / 20)
    threshold_rms = max_rms * (10.0 ** (-top_db / 20.0))
    threshold_rms = max(threshold_rms, min_energy)

    for w, rms in zip(candidates, rms_values):
        if rms >= threshold_rms:
            active_windows.append(w)

    # Salvaguarda: Si el filtro descartó todas las ventanas, conservar la de mayor energía
    if not active_windows:
        best_idx = int(np.argmax(rms_values))
        active_windows.append(candidates[best_idx])

    return active_windows


def extract_mel_spectrogram(
    waveform: np.ndarray,
    sr: int = TARGET_SR,
    n_mels: int = 64,
    n_fft: int = 1024,
    hop_length: int = 512,
    fmin: float = 50.0,
    fmax: Optional[float] = None,
) -> np.ndarray:
    """
    Extrae el espectrograma Mel en decibelios (dB) para una señal de audio 1D.
    Retorna un array float32 de forma (n_mels, time_steps).
    """
    if waveform.ndim != 1:
        raise ValueError(f"waveform debe ser 1D, recibido: {waveform.shape}")

    mel = librosa.feature.melspectrogram(
        y=waveform,
        sr=sr,
        n_fft=n_fft,
        hop_length=hop_length,
        n_mels=n_mels,
        fmin=fmin,
        fmax=fmax,
        power=2.0,
    )
    mel_db = librosa.power_to_db(mel, ref=np.max)
    return mel_db.astype(np.float32)


class GPUAudioFrontEnd(nn.Module):
    """
    Extractor de espectrogramas Mel acelerado en GPU/CPU con torchaudio.
    Calcula STFT, banco de filtros Mel, conversión a dB y normalización z-score en un solo paso hacia adelante.
    """

    def __init__(
        self,
        sample_rate: int = TARGET_SR,
        n_fft: int = 1024,
        hop_length: int = 512,
        n_mels: int = 128,
        f_min: float = 800.0,
        f_max: Optional[float] = 10000.0,
        top_db: float = 80.0,
        normalize: bool = True,
    ):
        super().__init__()
        self.normalize = normalize
        self.mel_spectrogram = T.MelSpectrogram(
            sample_rate=sample_rate,
            n_fft=n_fft,
            hop_length=hop_length,
            n_mels=n_mels,
            f_min=f_min,
            f_max=f_max,
            power=2.0,
        )
        self.amplitude_to_db = T.AmplitudeToDB(top_db=top_db)

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        """
        Calcula el espectrograma Mel en dB y añade dimensión de canal.
        Formas aceptadas: [B, T], [B, 1, T] o [T].
        Retorna: [B, 1, n_mels, time_steps].
        """
        if waveform.ndim == 1:
            waveform = waveform.unsqueeze(0)
        elif waveform.ndim == 3 and waveform.shape[1] == 1:
            waveform = waveform.squeeze(1)

        mel = self.mel_spectrogram(waveform)
        mel_db = self.amplitude_to_db(mel)

        if self.normalize:
            mean = mel_db.mean(dim=(-2, -1), keepdim=True)
            std = mel_db.std(dim=(-2, -1), keepdim=True)
            mel_db = (mel_db - mean) / (std + 1e-6)

        return mel_db.unsqueeze(1)


class GPUSpecAugment(nn.Module):
    """
    Data Augmentation en GPU para tensores de espectrogramas Mel [B, 1, F, T].
    Aplica:
    1. Desplazamiento tonal espectral (Spectral Pitch Shift) con zero-padding en los extremos.
    2. Enmascaramiento estocástico de frecuencia y tiempo (Frequency & Time Masking)
       utilizando transformaciones nativas de torchaudio con máscaras iid por muestra.
    Opera exclusivamente cuando model.training=True; en evaluación es un no-op determinista.
    """

    def __init__(
        self,
        freq_mask_param: int = 8,
        time_mask_param: int = 16,
        prob: float = 0.5,
        pitch_shift_max_bins: int = 2,
        pitch_shift_prob: float = 0.3,
    ):
        super().__init__()
        self.freq_mask = T.FrequencyMasking(freq_mask_param=freq_mask_param, iid_masks=True)
        self.time_mask = T.TimeMasking(time_mask_param=time_mask_param, iid_masks=True)
        self.prob = prob
        self.pitch_shift_max_bins = int(pitch_shift_max_bins)
        self.pitch_shift_prob = float(pitch_shift_prob)

    def _apply_pitch_shift(self, x: torch.Tensor) -> torch.Tensor:
        """
        Aplica traslación discreta a lo largo del eje Mel (dim=-2) con zero-padding en los extremos.
        Muestrea desplazamientos discretos no nulos uniformemente en [-max_bins, ..., max_bins] excluyendo el 0.
        """
        if self.pitch_shift_max_bins <= 0 or self.pitch_shift_prob <= 0.0:
            return x

        B = x.shape[0]
        shifts = [s for s in range(-self.pitch_shift_max_bins, self.pitch_shift_max_bins + 1) if s != 0]
        if not shifts:
            return x

        shifted_samples = []
        for i in range(B):
            if torch.rand(1).item() < self.pitch_shift_prob:
                s_idx = torch.randint(0, len(shifts), (1,)).item()
                shift = shifts[s_idx]
                sample = x[i : i + 1]
                if shift > 0:
                    zeros = torch.zeros(*sample.shape[:-2], shift, sample.shape[-1], device=x.device, dtype=x.dtype)
                    shifted_sample = torch.cat([zeros, sample[..., :-shift, :]], dim=-2)
                else:
                    abs_s = abs(shift)
                    zeros = torch.zeros(*sample.shape[:-2], abs_s, sample.shape[-1], device=x.device, dtype=x.dtype)
                    shifted_sample = torch.cat([sample[..., abs_s:, :], zeros], dim=-2)
                shifted_samples.append(shifted_sample)
            else:
                shifted_samples.append(x[i : i + 1])

        return torch.cat(shifted_samples, dim=0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if not self.training:
            return x

        # 1. Pitch Shift Espectral
        if self.pitch_shift_max_bins > 0 and self.pitch_shift_prob > 0.0:
            x = self._apply_pitch_shift(x)

        # 2. SpecAugment Masking
        if self.prob > 0.0 and torch.rand(1).item() < self.prob:
            x = self.freq_mask(x)
            x = self.time_mask(x)

        return x

class GeM(nn.Module):
    """
    Generalized Mean Pooling (GeM) para señales bioacústicas.
    Generaliza Average Pooling (p=1) y Max Pooling (p->inf), permitiendo enfatizar
    picos de activación diagnósticos de cantos sin diluirlos en el fondo acústico.
    Cuenta con doble clamping para garantizar estabilidad numérica frente a
    activaciones negativas provenientes de no-linealidades como SiLU/Swish.
    """

    def __init__(self, p: float = 3.0, eps: float = 1e-6, p_trainable: bool = True, flatten: bool = True):
        super().__init__()
        self.eps = eps
        self.flatten = flatten
        if p_trainable:
            self.p = nn.Parameter(torch.ones(1) * float(p))
        else:
            self.register_buffer("p", torch.tensor([float(p)]))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.clamp(min=self.eps)
        p_eff = self.p.clamp(min=1.0, max=10.0)
        x = x.pow(p_eff)
        x = F.adaptive_avg_pool2d(x, (1, 1))
        x = x.clamp(min=self.eps).pow(1.0 / p_eff)
        if self.flatten:
            x = x.flatten(1)
        return x

