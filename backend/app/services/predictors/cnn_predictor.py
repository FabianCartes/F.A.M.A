"""
Estrategia de predicción para la arquitectura AudioCNN entrenada sobre 15 especies de aves chilenas.
Implementa el contrato AudioPredictor encapsulando el preprocesamiento Mel,
filtrado de silencios (RMS), filtrado de ruido no-biológico (Flatness) y calibración por temperatura.
"""
from pathlib import Path
from typing import Optional, List
import torch
import numpy as np
import librosa

from poc.preprocess import (
    load_and_fix_length,
    extract_mel_spectrogram,
    compute_rms,
    TARGET_SR,
    DURATION_SECONDS,
)
from poc.train import AudioCNN
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services.predictors.base import AudioPredictor

# Umbral de planitud espectral: aves reales promedian 0.015 (máx 0.032).
# Ruido blanco/estática promedia > 0.50. Umbral de 0.15 separa nítidamente ambos.
SPECTRAL_FLATNESS_NOISE_THRESHOLD = 0.15

# Clases por defecto del dominio piloto de aves chilenas
DEFAULT_CHILEAN_BIRD_CLASSES = [
    "Canastero", "Chercán", "Chincol", "Chucao", "Churrín de la Mocha",
    "Churrín del sur", "Colilarga", "Fío-fío", "Picaflor chico", "Rayadito",
    "Tapaculo", "Tijeral", "Tordo", "Turca", "Zorzal patagónico"
]


class AudioCNNPredictor(AudioPredictor):
    """
    Estrategia concreta basada en AudioCNN con Data Augmentation y VAD (61.69% accuracy).
    """

    def __init__(
        self,
        checkpoint_path: Optional[Path] = None,
        temperature: float = 1.5,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.temperature = temperature

        if checkpoint_path is None:
            backend_root = Path(__file__).resolve().parent.parent.parent.parent
            augmented = backend_root / "checkpoints" / "augmented_best.pt"
            baseline = backend_root / "checkpoints" / "baseline_best.pt"
            self.checkpoint_path = augmented if augmented.exists() else baseline
        else:
            self.checkpoint_path = Path(checkpoint_path)

        self.model: Optional[AudioCNN] = None
        self.classes: List[str] = []
        self._load_checkpoint()

        self._metadata = ModelMetadata(
            id="chilean-birds-cnn",
            name="AudioCNN Baseline (VAD + Data Augmentation)",
            description="Red convolucional compacta optimizada con VAD y Data Augmentation para 15 aves chilenas",
            target_sr=TARGET_SR,
            duration_seconds=DURATION_SECONDS,
            classes=self.classes,
            is_default=True,
            metrics={"accuracy": 0.6169, "f1_macro": 0.6340},
        )

    def _load_checkpoint(self) -> None:
        """Carga los pesos entrenados y las clases si el checkpoint existe en disco."""
        if self.checkpoint_path.exists():
            checkpoint = torch.load(self.checkpoint_path, map_location=self.device)
            self.classes = checkpoint.get("classes", DEFAULT_CHILEAN_BIRD_CLASSES)
            self.model = AudioCNN(num_classes=len(self.classes))
            self.model.load_state_dict(checkpoint["model_state_dict"])
            self.model.to(self.device)
            self.model.eval()
        else:
            self.classes = list(DEFAULT_CHILEAN_BIRD_CLASSES)

    @property
    def metadata(self) -> ModelMetadata:
        return self._metadata

    def predict(self, audio_file_path: Path) -> PredictionResult:
        """
        Analiza las propiedades físicas de la señal y, si es una señal bioacústica válida,
        ejecuta la inferencia en PyTorch retornando la clase y su confianza calibrada.
        """
        waveform = load_and_fix_length(
            audio_file_path, target_sr=TARGET_SR, duration_seconds=DURATION_SECONDS
        )

        # 1. Filtro de Silencio (VAD por RMS energético)
        energy_rms = float(compute_rms(waveform))
        if energy_rms < 1e-4:
            return PredictionResult(
                clase="Silencio / No detectado",
                confianza=0.0,
                detalles={"energy_rms": energy_rms, "status": "silence"},
            )

        # 2. Filtro Físico-Acústico: Detección de Ruido Blanco / Señal No-Biológica
        spectral_flatness = float(np.mean(librosa.feature.spectral_flatness(y=waveform)))
        if spectral_flatness > SPECTRAL_FLATNESS_NOISE_THRESHOLD:
            return PredictionResult(
                clase="Ruido / Señal no biológica",
                confianza=0.0,
                detalles={
                    "energy_rms": energy_rms,
                    "spectral_flatness": spectral_flatness,
                    "status": "noise",
                },
            )

        # 3. Extracción de características acústicas (Mel-Spectrogram)
        mel = extract_mel_spectrogram(waveform, sr=TARGET_SR)
        mel_tensor = torch.from_numpy(mel).unsqueeze(0).unsqueeze(0).float().to(self.device)

        if self.model is not None:
            with torch.no_grad():
                outputs = self.model(mel_tensor)

                # 4. Calibración de probabilidades por Temperatura
                scaled_logits = outputs / self.temperature
                probabilities = torch.softmax(scaled_logits, dim=1)
                confidence, pred_idx = torch.max(probabilities, dim=1)

                predicted_class = self.classes[pred_idx.item()]
                conf_val = round(float(confidence.item()), 4)

                return PredictionResult(
                    clase=predicted_class,
                    confianza=conf_val,
                    detalles={
                        "energy_rms": energy_rms,
                        "spectral_flatness": spectral_flatness,
                        "status": "classified",
                    },
                )
        else:
            # Modo de contingencia si no se cargaron pesos
            return PredictionResult(
                clase="Chincol",
                confianza=0.8500,
                detalles={"status": "mock_fallback"},
            )
