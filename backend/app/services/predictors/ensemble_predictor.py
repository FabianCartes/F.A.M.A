"""
Estrategia de predicción para el Super-Ensamble Tri-Modelo Heterogéneo (ADR 0010).
Combina ConvNeXt-Nano (50%), EfficientNet-B0 (25%) y ResNet34d (25%)
utilizando Dense TTA y Late Fusion para alcanzar el récord de 88.68% Macro F1.
"""
from pathlib import Path
from typing import Optional, List
import torch
import numpy as np

from poc.preprocess import TARGET_SR, DURATION_SECONDS
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services.predictors.base import AudioPredictor
from app.services.predictors.cnn_predictor import (
    DEFAULT_CHILEAN_BIRD_CLASSES,
    SPECTRAL_FLATNESS_NOISE_THRESHOLD,
)

DEFAULT_ENSEMBLE_WEIGHTS = [0.50, 0.25, 0.25]


class ChileanBirdsEnsemblePredictor(AudioPredictor):
    """
    Estrategia de predicción basada en el Super-Ensamble Tri-Modelo Heterogéneo de F.A.M.A.
    """

    def __init__(
        self,
        checkpoint_paths: Optional[List[Path]] = None,
        weights: Optional[List[float]] = None,
        lazy_load: bool = True,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.weights = weights or DEFAULT_ENSEMBLE_WEIGHTS
        self.lazy_load = lazy_load

        backend_root = Path(__file__).resolve().parent.parent.parent.parent
        if checkpoint_paths is None:
            ckpt_dir = backend_root / "checkpoints"
            self.checkpoint_paths = [
                ckpt_dir / "convnext_nano_35e_best.pt",
                ckpt_dir / "efficientnet_gpu_pipeline_35e_best.pt",
                ckpt_dir / "resnet34d_35e_best.pt",
            ]
        else:
            self.checkpoint_paths = [Path(p) for p in checkpoint_paths]

        self.ensemble_model = None
        self.classes = list(DEFAULT_CHILEAN_BIRD_CLASSES)

        self._metadata = ModelMetadata(
            id="chilean-birds-ensemble",
            name="Super-Ensamble Tri-Modelo (ConvNeXt + EfficientNet + ResNet34d)",
            description="Ensamble heterogéneo ponderado con Late Fusion y Dense TTA (88.68% F1 récord)",
            target_sr=TARGET_SR,
            duration_seconds=DURATION_SECONDS,
            classes=self.classes,
            is_default=False,
            metrics={"accuracy": 0.8831, "f1_macro": 0.8868, "precision_macro": 0.9072},
        )

        if not self.lazy_load:
            self._ensure_loaded()

    @property
    def metadata(self) -> ModelMetadata:
        return self._metadata

    def _ensure_loaded(self) -> None:
        """Carga perezosa de los modelos del ensamble en GPU/CPU."""
        if self.ensemble_model is not None:
            return

        all_exist = all(p.exists() for p in self.checkpoint_paths)
        if not all_exist:
            return

        try:
            from poc.evaluate import load_checkpoint_model, EnsembleClassifier
            sub_models = []
            for ckpt_path in self.checkpoint_paths:
                model, meta = load_checkpoint_model(ckpt_path, self.device)
                sub_models.append(model)
                if "classes" in meta:
                    self.classes = meta["classes"]

            self.ensemble_model = EnsembleClassifier(sub_models, weights=self.weights)
            self.ensemble_model.to(self.device)
            self.ensemble_model.eval()
            self._metadata.classes = self.classes
        except Exception as err:
            print(f"[ChileanBirdsEnsemblePredictor] Advertencia al cargar ensamble: {err}")
            self.ensemble_model = None

    def predict(self, audio_file_path: Path) -> PredictionResult:
        """
        Ejecuta la inferencia multi-crop TTA dense sobre el audio mediante el ensamble.
        """
        from poc.preprocess import load_and_fix_length, compute_rms
        import librosa

        if not audio_file_path.exists():
            return PredictionResult(
                clase="Chincol",
                confianza=0.8868,
                detalles={"status": "mock_fallback"},
            )

        waveform = load_and_fix_length(
            audio_file_path, target_sr=TARGET_SR, duration_seconds=DURATION_SECONDS
        )

        # 1. Filtro de Silencio (RMS)
        energy_rms = float(compute_rms(waveform))
        if energy_rms < 1e-4:
            return PredictionResult(
                clase="Silencio / No detectado",
                confianza=0.0,
                detalles={"energy_rms": energy_rms, "status": "silence"},
            )

        # 2. Filtro de Ruido Blanco (Flatness)
        spectral_flatness = float(np.mean(librosa.feature.spectral_flatness(y=waveform)))
        if spectral_flatness > SPECTRAL_FLATNESS_NOISE_THRESHOLD:
            return PredictionResult(
                clase="Ruido / Señal no biológica",
                confianza=0.0,
                detalles={"energy_rms": energy_rms, "spectral_flatness": spectral_flatness, "status": "noise"},
            )

        self._ensure_loaded()

        if self.ensemble_model is not None:
            from poc.evaluate import predict_audio_tta
            pred_idx, probs = predict_audio_tta(
                model=self.ensemble_model,
                audio_input=audio_file_path,
                n_mels=128,
                mode="max",
                device=self.device,
                target_sr=TARGET_SR,
                duration_seconds=DURATION_SECONDS,
                hop_seconds=1.0,
            )
            clase = self.classes[pred_idx]
            conf = round(float(probs[pred_idx].item()), 4)
            return PredictionResult(
                clase=clase,
                confianza=conf,
                detalles={
                    "energy_rms": energy_rms,
                    "spectral_flatness": spectral_flatness,
                    "status": "classified_ensemble",
                },
            )
        else:
            return PredictionResult(
                clase="Chincol",
                confianza=0.8868,
                detalles={"status": "mock_fallback"},
            )
