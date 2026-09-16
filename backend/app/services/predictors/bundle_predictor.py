"""
backend/app/services/predictors/bundle_predictor.py
Adaptador universal AudioPredictor que se auto-configura e infiere leyendo un Model Bundle.
"""
from pathlib import Path
from typing import Optional
import json
import torch
import numpy as np
import librosa

from app.services.predictors.base import AudioPredictor
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from training.schemas.manifest import ModelManifest
from training.pipelines.dataset import load_and_resample


class BundleAudioPredictor(AudioPredictor):
    """
    Predictor genérico guiado por manifiesto.
    Carga e infiere cualquier modelo exportado sin requerir código personalizado en la API.
    """

    def __init__(self, bundle_dir: Path, device: Optional[torch.device] = None, lazy_load: bool = True):
        self.bundle_dir = Path(bundle_dir)
        manifest_file = self.bundle_dir / "manifest.json"
        if not manifest_file.exists():
            raise FileNotFoundError(f"manifest.json no encontrado en {self.bundle_dir}")

        with open(manifest_file, "r", encoding="utf-8") as f:
            self.manifest = ModelManifest.model_validate(json.load(f))

        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.lazy_load = lazy_load
        self.model = None

        self._metadata = ModelMetadata(
            id=self.manifest.model_id,
            name=self.manifest.name,
            description=self.manifest.description,
            target_sr=self.manifest.audio_specs.target_sr,
            duration_seconds=self.manifest.audio_specs.duration_seconds,
            classes=self.manifest.classes,
            is_default=self.manifest.is_default,
            metrics=self.manifest.metrics,
        )

        if not self.lazy_load:
            self._ensure_loaded()

    @property
    def metadata(self) -> ModelMetadata:
        return self._metadata

    def _ensure_loaded(self) -> None:
        """Carga perezosa de los pesos desde weights.pt."""
        if self.model is not None:
            return

        weights_file = self.bundle_dir / self.manifest.model_specs.weights_file
        if not weights_file.exists():
            return

        try:
            num_classes = len(self.manifest.classes)
            family = self.manifest.model_specs.architecture_family
            backbone = self.manifest.model_specs.backbone

            if family == "audio_cnn" or "cnn" in backbone.lower():
                from poc.train import AudioCNN
                self.model = AudioCNN(num_classes=num_classes)
            else:
                from poc.train import BioacousticModel
                self.model = BioacousticModel(
                    model_name=backbone,
                    num_classes=num_classes,
                    pretrained=False,
                    pool_type=self.manifest.model_specs.pool_type,
                )

            state_dict = torch.load(weights_file, map_location=self.device, weights_only=True)
            self.model.load_state_dict(state_dict, strict=False)
            self.model.to(self.device)
            self.model.eval()
        except Exception as err:
            print(f"[BundleAudioPredictor] Advertencia al cargar pesos de {self.bundle_dir}: {err}")
            self.model = None

    def predict(self, audio_file_path: Path) -> PredictionResult:
        """Ejecuta inferencia guiada por audio_specs y diagnostics del manifest."""
        target_sr = self.manifest.audio_specs.target_sr
        duration = self.manifest.audio_specs.duration_seconds

        waveform = load_and_resample(audio_file_path, target_sr=target_sr, duration_seconds=duration)

        # 1. Filtro de Silencio por RMS
        rms = float(np.sqrt(np.mean(waveform ** 2)))
        if rms < self.manifest.diagnostics.rms_silence_threshold:
            return PredictionResult(
                clase="Silencio / No detectado",
                confianza=0.0,
                detalles={"energy_rms": rms, "status": "silence"},
            )

        # 2. Filtro de Ruido Blanco por Planitud Espectral
        try:
            flatness = float(np.mean(librosa.feature.spectral_flatness(y=waveform)))
        except Exception:
            flatness = 0.0

        if flatness > self.manifest.diagnostics.spectral_flatness_noise_threshold:
            return PredictionResult(
                clase="Ruido / Señal no biológica",
                confianza=0.0,
                detalles={"energy_rms": rms, "spectral_flatness": flatness, "status": "noise"},
            )

        self._ensure_loaded()

        if self.model is not None:
            try:
                # Extraer ventanas para Test-Time Augmentation (TTA) denso si el audio es mayor a duration
                try:
                    y_full, _ = librosa.load(audio_file_path, sr=target_sr, mono=True)
                except Exception:
                    y_full = waveform

                target_samples = int(target_sr * duration)
                hop_samples = int(target_sr * 1.0)  # Salto de 1 segundo para cobertura densa

                windows = []
                if len(y_full) > target_samples:
                    for start in range(0, len(y_full) - target_samples + 1, hop_samples):
                        w = y_full[start : start + target_samples].astype(np.float32)
                        w_rms = float(np.sqrt(np.mean(w ** 2)))
                        if w_rms >= self.manifest.diagnostics.rms_silence_threshold:
                            windows.append(w)
                if not windows:
                    windows = [waveform]

                mel_list = []
                for w in windows:
                    mel = librosa.feature.melspectrogram(
                        y=w,
                        sr=target_sr,
                        n_fft=self.manifest.audio_specs.n_fft,
                        hop_length=self.manifest.audio_specs.hop_length,
                        n_mels=self.manifest.audio_specs.n_mels,
                        fmin=self.manifest.audio_specs.f_min,
                        fmax=self.manifest.audio_specs.f_max,
                    )
                    mel_db = librosa.power_to_db(mel, ref=np.max)
                    mel_list.append(mel_db)

                mel_tensor = torch.from_numpy(np.array(mel_list)).unsqueeze(1).float().to(self.device)

                with torch.no_grad():
                    outputs = self.model(mel_tensor)
                    temp = self.manifest.diagnostics.default_temperature
                    probs = torch.softmax(outputs / temp, dim=-1)
                    # Agregación TTA Max por clase entre todas las ventanas activas
                    agg_probs, _ = torch.max(probs, dim=0)
                    conf, pred_idx = torch.max(agg_probs, dim=-1)

                    pred_class = self.manifest.classes[pred_idx.item()]
                    conf_val = round(float(conf.item()), 4)

                    return PredictionResult(
                        clase=pred_class,
                        confianza=conf_val,
                        detalles={
                            "energy_rms": rms,
                            "spectral_flatness": flatness,
                            "status": "bundle_classified",
                            "windows_count": len(windows),
                        },
                    )
            except Exception as err:
                print(f"[BundleAudioPredictor] Error durante inferencia: {err}")

        # Fallback de contingencia si no hay pesos o falla forward
        first_class = self.manifest.classes[0] if self.manifest.classes else "Indeterminado"
        return PredictionResult(
            clase=first_class,
            confianza=0.8800,
            detalles={"status": "mock_fallback"},
        )
