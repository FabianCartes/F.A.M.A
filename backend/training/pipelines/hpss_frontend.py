"""
backend/training/pipelines/hpss_frontend.py
Frontend acústico bioacústico/mecánico con separación de fuentes armónico-percusiva (HPSS) en 3 canales.
Descolisiona señales tonales (correas, dirección) de transitorios de impacto (falta de aceite, bielas, bujías).
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio.transforms as T


class HPSSAudioFrontEnd(nn.Module):
    """
    Transforma formas de onda crudas [B, T] en tensores Mel de 3 canales [B, 3, n_mels, time_frames]:
      - Canal 0: Espectrograma Mel original (potencia total)
      - Canal 1: Espectrograma Mel de la componente armónica (tonal continuo)
      - Canal 2: Espectrograma Mel de la componente percusiva (transitorios de impacto)
    """

    def __init__(
        self,
        sample_rate: int = 32000,
        n_fft: int = 2048,
        hop_length: int = 256,
        n_mels: int = 128,
        f_min: float = 20.0,
        f_max: float = 8000.0,
        kernel_size: int = 15,
        power: float = 2.0,
        eps: float = 1e-6,
    ):
        super().__init__()
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.n_mels = n_mels
        self.f_min = f_min
        self.f_max = f_max
        self.kernel_size = kernel_size if kernel_size % 2 == 1 else kernel_size + 1
        self.power = power
        self.eps = eps

        # Extractor de magnitud STFT
        self.spectrogram = T.Spectrogram(
            n_fft=n_fft,
            win_length=n_fft,
            hop_length=hop_length,
            power=1.0,  # magnitud lineal para filtrado de máscara
            center=True,
            pad_mode="reflect",
        )

        # Banco de filtros Mel
        self.mel_scale = T.MelScale(
            n_mels=n_mels,
            sample_rate=sample_rate,
            f_min=f_min,
            f_max=f_max,
            n_stft=n_fft // 2 + 1,
            norm="slaney",
            mel_scale="slaney",
        )

    def _median_filter_time(self, x: torch.Tensor, k: int) -> torch.Tensor:
        """Filtro de mediana a lo largo del eje temporal (para extraer líneas armónicas horizontales)."""
        pad = k // 2
        # x: [B, F, T]
        x_pad = F.pad(x, (pad, pad), mode="reflect")
        return x_pad.unfold(dimension=2, size=k, step=1).median(dim=-1).values

    def _median_filter_freq(self, x: torch.Tensor, k: int) -> torch.Tensor:
        """Filtro de mediana a lo largo del eje frecuencial (para extraer líneas percusivas verticales)."""
        pad = k // 2
        # x: [B, F, T] -> pad en F
        x_pad = F.pad(x.unsqueeze(1), (0, 0, pad, pad), mode="reflect").squeeze(1)
        return x_pad.unfold(dimension=1, size=k, step=1).median(dim=-1).values

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Entrada:
            x: Tensor de audio [B, T] o [T] o [B, 1, T]
        Salida:
            [B, 3, n_mels, time_frames]
        """
        if x.ndim == 1:
            x = x.unsqueeze(0)
        elif x.ndim == 3 and x.shape[1] == 1:
            x = x.squeeze(1)

        # 1. Calcular espectrograma de magnitud lineal
        spec_mag = self.spectrogram(x)  # [B, F, T]

        # 2. Filtrado armónico y percusivo
        h_filter = self._median_filter_time(spec_mag, self.kernel_size)
        p_filter = self._median_filter_freq(spec_mag, self.kernel_size)

        # 3. Máscaras blandas (Wiener-style soft masking)
        h_power = h_filter.pow(self.power)
        p_power = p_filter.pow(self.power)
        total_power = h_power + p_power + self.eps

        mask_h = h_power / total_power
        mask_p = p_power / total_power

        # Componentes separadas
        spec_harm = spec_mag * mask_h
        spec_perc = spec_mag * mask_p

        # 4. Proyección a escala Mel
        mel_raw = self.mel_scale(spec_mag)
        mel_harm = self.mel_scale(spec_harm)
        mel_perc = self.mel_scale(spec_perc)

        # 5. Compresión logarítmica dB-like estable
        log_mel_raw = torch.log(torch.clamp(mel_raw, min=self.eps) + 1.0)
        log_mel_harm = torch.log(torch.clamp(mel_harm, min=self.eps) + 1.0)
        log_mel_perc = torch.log(torch.clamp(mel_perc, min=self.eps) + 1.0)

        # 6. Concatenación en 3 canales: [B, 3, n_mels, time_frames]
        out_3ch = torch.stack([log_mel_raw, log_mel_harm, log_mel_perc], dim=1)
        return out_3ch
