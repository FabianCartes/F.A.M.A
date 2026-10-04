"""
Estrategia de predicción para modelos bioacústicos entrenados dinámicamente.
Carga checkpoints reales (.pt) generados durante el ciclo de entrenamiento (RF_04 / CU_INV_05).
Garantiza inferencia real en PyTorch, telemetría ODD y fail-fast si faltan pesos.
"""
from pathlib import Path
from typing import Optional, List, Dict, Any
import time
import torch
import torch.nn as nn
import numpy as np
import librosa

try:
    from ml_core.preprocess import (
        load_and_fix_length,
        extract_mel_spectrogram,
        compute_rms,
        TARGET_SR,
        DURATION_SECONDS,
    )
    from ml_core.train import BioacousticModel, AudioCNN
except ImportError:
    from poc.preprocess import (
        load_and_fix_length,
        extract_mel_spectrogram,
        compute_rms,
        TARGET_SR,
        DURATION_SECONDS,
    )
    from poc.train import BioacousticModel, AudioCNN

from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services.predictors.base import (
    AudioPredictor,
    ModelWeightsError,
    DEFAULT_CHILEAN_BIRD_CLASSES,
    SPECTRAL_FLATNESS_NOISE_THRESHOLD,
)


class TrainedModelPredictor(AudioPredictor):
    """
    Predictor de inferencia real basado en checkpoints binarios generados por el pipeline de entrenamiento.
    """

    def __init__(
        self,
        checkpoint_path: Path,
        model_id: Optional[str] = None,
        name: Optional[str] = None,
        is_default: bool = False,
        lazy_load: bool = False,
        dataset_name: Optional[str] = None,
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.is_default = is_default
        self._model_id = model_id or self.checkpoint_path.stem
        self.custom_name = name
        self.classes: List[str] = list(DEFAULT_CHILEAN_BIRD_CLASSES)
        self.architecture_name: str = "BioacousticModel"
        self.best_val_acc: Optional[float] = None
        self.model: Optional[nn.Module] = None

        if not self.checkpoint_path.exists():
            raise ModelWeightsError(
                f"Archivo de pesos de checkpoint no encontrado: {self.checkpoint_path}"
            )

        if not lazy_load:
            self._load_model()
        else:
            self._load_metadata()

        self._metadata = ModelMetadata(
            id=self._model_id,
            dataset_name=dataset_name,
            name=self.custom_name or f"Modelo Entrenado: {self.architecture_name} ({self.checkpoint_path.name})",
            description=f"Inferencia bioacústica con pesos reales entrenados ({self.architecture_name})",
            target_sr=TARGET_SR,
            duration_seconds=DURATION_SECONDS,
            classes=self.classes,
            is_default=self.is_default,
            metrics={"accuracy": round(self.best_val_acc / 100.0 if self.best_val_acc and self.best_val_acc > 1 else (self.best_val_acc or 0.0), 4)},
        )

    def _load_metadata(self) -> None:
        """
        Carga únicamente la metadata del checkpoint sin instanciar el modelo
        ni alocar pesos en memoria/GPU (Lazy Loading real).
        """
        if not self.checkpoint_path.exists():
            raise ModelWeightsError(
                f"Archivo de checkpoint inexistente: {self.checkpoint_path}"
            )

        try:
            checkpoint = torch.load(self.checkpoint_path, map_location="cpu")
        except Exception as err:
            raise ModelWeightsError(
                f"Error al deserializar checkpoint {self.checkpoint_path}: {err}"
            ) from err

        if not isinstance(checkpoint, dict):
            raise ModelWeightsError(
                f"El checkpoint {self.checkpoint_path} no tiene un formato válido (se esperaba un diccionario)."
            )

        self.architecture_name = checkpoint.get("architecture", "EfficientNet-B0")
        self.classes = checkpoint.get("classes", list(DEFAULT_CHILEAN_BIRD_CLASSES))
        self.best_val_acc = checkpoint.get("best_val_acc")
        self.model = None

    def _load_model(self) -> None:
        """Carga y valida los pesos binarios en memoria."""
        if not self.checkpoint_path.exists():
            raise ModelWeightsError(
                f"Archivo de checkpoint inexistente: {self.checkpoint_path}"
            )

        try:
            checkpoint = torch.load(self.checkpoint_path, map_location=self.device)
        except Exception as err:
            raise ModelWeightsError(
                f"Error al deserializar checkpoint {self.checkpoint_path}: {err}"
            ) from err

        if not isinstance(checkpoint, dict):
            raise ModelWeightsError(
                f"El checkpoint {self.checkpoint_path} no tiene un formato válido (se esperaba un diccionario)."
            )

        state_dict = checkpoint.get("state_dict") or checkpoint.get("model_state_dict")
        if state_dict is None:
            # Verificar si el diccionario en sí contiene tensores
            if any(isinstance(v, torch.Tensor) for v in checkpoint.values()):
                state_dict = checkpoint
            else:
                raise ModelWeightsError(
                    f"No se encontró state_dict en el checkpoint {self.checkpoint_path}"
                )

        self.architecture_name = checkpoint.get("architecture", "EfficientNet-B0")
        self.classes = checkpoint.get("classes", list(DEFAULT_CHILEAN_BIRD_CLASSES))
        self.best_val_acc = checkpoint.get("best_val_acc")

        arch_lower = self.architecture_name.lower().replace("-", "_")
        num_classes = len(self.classes)

        if "audiocnn" in arch_lower or "audio_cnn" in arch_lower:
            model = AudioCNN(num_classes=num_classes)
        elif "panns" in arch_lower:
            try:
                from training.models.panns_cnn14 import PannsCNN14
                model = PannsCNN14(in_chans=1, num_classes=num_classes)
            except ImportError:
                model = BioacousticModel(model_name="panns_cnn14", num_classes=num_classes, in_chans=1, pretrained=False)
        else:
            if "resnet" in arch_lower:
                target_arch = "resnet34d"
            elif "convnext" in arch_lower:
                target_arch = "convnext_nano"
            elif "efficient" in arch_lower:
                target_arch = "efficientnet_b0"
            else:
                target_arch = arch_lower

            model = BioacousticModel(
                model_name=target_arch,
                num_classes=num_classes,
                in_chans=1,
                pretrained=False,
            )

        try:
            model.load_state_dict(state_dict)
        except Exception as load_err:
            raise ModelWeightsError(
                f"Incompatibilidad de arquitectura o pesos en {self.checkpoint_path}: {load_err}"
            ) from load_err

        model.to(self.device)
        model.eval()
        self.model = model

    @property
    def has_weights(self) -> bool:
        return self.checkpoint_path.exists() and self.checkpoint_path.stat().st_size > 10000

    @property
    def metadata(self) -> ModelMetadata:
        self._metadata.is_default = self.is_default
        self._metadata.has_weights = self.has_weights
        return self._metadata

    @property
    def model_id(self) -> str:
        return self._model_id

    def predict(self, audio_file_path: Path) -> PredictionResult:
        """
        Ejecuta la inferencia real de extremo a extremo sin mocks.
        Aplica VAD de silencio y filtro de ruido biológico.
        """
        if not audio_file_path.exists():
            raise FileNotFoundError(f"Archivo de audio no encontrado: {audio_file_path}")

        if self.model is None:
            self._load_model()

        waveform = load_and_fix_length(
            audio_file_path, target_sr=TARGET_SR, duration_seconds=DURATION_SECONDS
        )

        # 1. Filtro de Silencio (RMS)
        energy_rms = float(compute_rms(waveform))
        if energy_rms < 1e-4:
            return PredictionResult(
                clase="Silencio / No detectado",
                confianza=0.0,
                detalles={
                    "energy_rms": energy_rms,
                    "status": "silence",
                    "checkpoint_name": self.checkpoint_path.name,
                    "device": str(self.device),
                    "is_mock": False,
                },
            )

        # 2. Filtro Físico-Acústico: Flatness para Ruido Blanco / No-Biológico
        non_silent = waveform[np.abs(waveform) > 1e-4]
        signal_for_flatness = non_silent if len(non_silent) > 512 else waveform
        spectral_flatness = float(np.mean(librosa.feature.spectral_flatness(y=signal_for_flatness)))
        if spectral_flatness > SPECTRAL_FLATNESS_NOISE_THRESHOLD:
            return PredictionResult(
                clase="Ruido / Señal no biológica",
                confianza=0.0,
                detalles={
                    "energy_rms": energy_rms,
                    "spectral_flatness": spectral_flatness,
                    "status": "noise",
                    "checkpoint_name": self.checkpoint_path.name,
                    "device": str(self.device),
                    "is_mock": False,
                },
            )

        # 3. Extracción de Mel-Spectrogram y pasada PyTorch
        mel = extract_mel_spectrogram(waveform, sr=TARGET_SR)
        mel_tensor = torch.from_numpy(mel).unsqueeze(0).unsqueeze(0).float().to(self.device)

        t_start = time.perf_counter()
        with torch.no_grad():
            outputs = self.model(mel_tensor)
            probabilities = torch.softmax(outputs, dim=1)
            confidence, pred_idx = torch.max(probabilities, dim=1)
        latency_ms = round((time.perf_counter() - t_start) * 1000.0, 2)

        predicted_class = self.classes[pred_idx.item()]
        conf_val = round(float(confidence.item()), 4)

        return PredictionResult(
            clase=predicted_class,
            confianza=conf_val,
            detalles={
                "energy_rms": energy_rms,
                "spectral_flatness": spectral_flatness,
                "checkpoint_name": self.checkpoint_path.name,
                "device": str(self.device),
                "latency_ms": latency_ms,
                "status": "classified",
                "is_mock": False,
            },
        )
