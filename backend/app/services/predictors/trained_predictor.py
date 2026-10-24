"""
Estrategia de predicción para modelos bioacústicos entrenados dinámicamente.
Carga checkpoints reales (.pt) generados durante el ciclo de entrenamiento (RF_04 / CU_INV_05).
Garantiza inferencia real en PyTorch, telemetría ODD y fail-fast si faltan pesos.
"""
from pathlib import Path
from typing import Optional, List, Dict, Any
from io import BytesIO
from threading import RLock
import hashlib
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

from poc.preprocess import GPUAudioFrontEnd, validate_gpu_audio_frontend_contract, extract_active_windows
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.schemas.training import AudioConfigSchema
from training.pipelines.dataset import load_and_resample
from app.services.predictors.base import (
    AudioPredictor,
    ModelWeightsError,
    DEFAULT_CHILEAN_BIRD_CLASSES,
    SPECTRAL_FLATNESS_NOISE_THRESHOLD,
)


def _checkpoint_architecture(checkpoint: dict):
    if "architecture" in checkpoint or "model_type" in checkpoint:
        return checkpoint.get("architecture", checkpoint.get("model_type"))
    state = checkpoint.get("model_state_dict")
    classes = checkpoint.get("classes", DEFAULT_CHILEAN_BIRD_CLASSES)
    if isinstance(state, dict) and isinstance(classes, (list, tuple)) and classes:
        # The two original CNN files predate architecture metadata. Recognize
        # their complete tensor layout without allocating a second set of weights.
        with torch.device("meta"):
            expected = AudioCNN(num_classes=len(classes)).state_dict()
        if (set(state) == set(expected) and all(
                isinstance(state[key], torch.Tensor) and state[key].shape == value.shape
                for key, value in expected.items())):
            return "AudioCNN"
    return "EfficientNet-B0"
def _standard_frontend_contract(checkpoint):
    if "job_id" not in checkpoint:
        return None
    try:
        return validate_gpu_audio_frontend_contract(checkpoint.get("preprocessing_contract"))
    except ValueError as err:
        raise ModelWeightsError(
            "El checkpoint estándar tiene un contrato de preprocessing GPU inválido o no soportado."
        ) from err



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
        expected_checkpoint_sha256: Optional[str] = None,
    ):
        self.checkpoint_path = Path(checkpoint_path)
        if expected_checkpoint_sha256 is not None and (
            not isinstance(expected_checkpoint_sha256, str)
            or len(expected_checkpoint_sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in expected_checkpoint_sha256)
        ):
            raise ModelWeightsError("El hash SHA-256 esperado del checkpoint registrado no es válido.")
        self.expected_checkpoint_sha256 = (
            expected_checkpoint_sha256.lower() if expected_checkpoint_sha256 is not None else None
        )
        self._load_lock = RLock()
        self._loaded_checkpoint_sha256: Optional[str] = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.is_default = is_default
        self._model_id = model_id or self.checkpoint_path.stem
        self.custom_name = name
        self.classes: List[str] = list(DEFAULT_CHILEAN_BIRD_CLASSES)
        self.architecture_name: str = "BioacousticModel"
        self.best_val_acc: Optional[float] = None
        self.model: Optional[nn.Module] = None
        self.frontend: Optional[GPUAudioFrontEnd] = None
        self.preprocessing_contract: Optional[Dict[str, Any]] = None
        self.audio_config: Optional[dict] = None
        self.legacy_n_mels = 64
        self.window_selection = "max_rms"

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
            target_sr=(self.preprocessing_contract["sample_rate"]
                       if self.preprocessing_contract else (self.audio_config or {}).get("target_sr", TARGET_SR)),
            duration_seconds=(self.preprocessing_contract["duration_seconds"]
                              if self.preprocessing_contract else (self.audio_config or {}).get("duration_seconds", DURATION_SECONDS)),
            classes=self.classes,
            is_default=self.is_default,
            metrics={"accuracy": round(self.best_val_acc / 100.0 if self.best_val_acc and self.best_val_acc > 1 else (self.best_val_acc or 0.0), 4)},
            loaded_checkpoint_sha256=self._loaded_checkpoint_sha256,
        )

    def _read_checkpoint_snapshot(self) -> tuple[bytes, str]:
        try:
            snapshot = self.checkpoint_path.read_bytes()
        except Exception as err:
            raise ModelWeightsError(
                f"No se pudo leer el checkpoint para inferencia: {err}"
            ) from err
        digest = hashlib.sha256(snapshot).hexdigest()
        if self.expected_checkpoint_sha256 is not None and digest != self.expected_checkpoint_sha256:
            raise ModelWeightsError(
                "El checkpoint disponible no coincide con el hash SHA-256 registrado para este modelo."
            )
        return snapshot, digest

    def _deserialize_checkpoint(self, snapshot: bytes, map_location):
        try:
            checkpoint = torch.load(BytesIO(snapshot), map_location=map_location)
        except Exception as err:
            raise ModelWeightsError(
                f"Error al deserializar checkpoint {self.checkpoint_path}: {err}"
            ) from err
        if not isinstance(checkpoint, dict):
            raise ModelWeightsError(
                f"El checkpoint {self.checkpoint_path} no tiene un formato válido (se esperaba un diccionario)."
            )
        return checkpoint

    def _load_metadata(self) -> None:
        """
        Carga únicamente la metadata del checkpoint sin instanciar el modelo
        ni alocar pesos en memoria/GPU (Lazy Loading real).
        """
        if not self.checkpoint_path.exists():
            raise ModelWeightsError(
                f"Archivo de checkpoint inexistente: {self.checkpoint_path}"
            )

        snapshot, _ = self._read_checkpoint_snapshot()
        checkpoint = self._deserialize_checkpoint(snapshot, map_location="cpu")
        contract = _standard_frontend_contract(checkpoint)
        architecture_name = _checkpoint_architecture(checkpoint)
        classes = checkpoint.get("classes", list(DEFAULT_CHILEAN_BIRD_CLASSES))
        best_val_acc = checkpoint.get("best_val_acc", checkpoint.get("val_acc"))

        if contract is None:
            self._configure_audio(checkpoint)
        self.preprocessing_contract = contract
        self.architecture_name = architecture_name
        self.classes = classes
        self.best_val_acc = best_val_acc


    def _configure_audio(self, checkpoint: dict) -> None:
        configuration = checkpoint.get("audio_config")
        self.window_selection = "max_rms"
        if "preprocessing" in checkpoint:
            profile = checkpoint["preprocessing"]
            if (not isinstance(profile, dict) or type(profile.get("version")) is not int
                    or profile.get("version") != 1 or profile.get("frontend") != "gpu_mel_zscore"
                    or profile.get("window_selection") not in ("max_rms", "active_max_rms")
                    or configuration is None):
                raise ModelWeightsError("Perfil de preprocesamiento del checkpoint no soportado")
            self.window_selection = profile["window_selection"]
        if configuration is None:
            self.audio_config = None
            try:
                self.legacy_n_mels = AudioConfigSchema.model_validate(
                    {"n_mels": checkpoint.get("n_mels", 64)}, strict=True
                ).n_mels
            except (ValueError, TypeError) as error:
                raise ModelWeightsError("Checkpoint con n_mels legacy inválido") from error
            return
        try:
            if (not isinstance(configuration, dict)
                    or not set(AudioConfigSchema.model_fields).issubset(configuration)):
                raise ValueError("Incomplete audio configuration")
            self.audio_config = AudioConfigSchema.model_validate(configuration, strict=True).model_dump()
        except (ValueError, TypeError) as error:
            raise ModelWeightsError("Checkpoint con configuración acústica inválida o incompleta") from error

    def _load_model(self) -> None:
        """Carga y valida los pesos binarios en memoria desde una instantánea única."""
        with self._load_lock:
            if self.model is not None:
                return
            if not self.checkpoint_path.exists():
                raise ModelWeightsError(
                    f"Archivo de checkpoint inexistente: {self.checkpoint_path}"
                )

            snapshot, loaded_hash = self._read_checkpoint_snapshot()
            checkpoint = self._deserialize_checkpoint(snapshot, map_location=self.device)
            contract = _standard_frontend_contract(checkpoint)
            state_dict = checkpoint.get("state_dict") or checkpoint.get("model_state_dict")
            if state_dict is None:
                # Verificar si el diccionario en sí contiene tensores.
                if any(isinstance(value, torch.Tensor) for value in checkpoint.values()):
                    state_dict = checkpoint
                else:
                    raise ModelWeightsError(
                        f"No se encontró state_dict en el checkpoint {self.checkpoint_path}"
                    )


            architecture_name = _checkpoint_architecture(checkpoint)
            classes = checkpoint.get("classes", list(DEFAULT_CHILEAN_BIRD_CLASSES))
            best_val_acc = checkpoint.get("best_val_acc", checkpoint.get("val_acc"))
            arch_lower = architecture_name.lower().replace("-", "_")
            num_classes = len(classes)
            legacy_poc = "model_type" in checkpoint and "architecture" not in checkpoint
            pool_type = checkpoint.get("pool_type", "avg" if legacy_poc else "gem")
            if pool_type is None:
                pool_type = "avg"
            if not isinstance(pool_type, str) or pool_type.lower() not in {"avg", "gem"}:
                raise ModelWeightsError("Contrato de pooling del checkpoint no soportado")
            pool_type = pool_type.lower()

            try:
                if arch_lower == "cnn" or "audiocnn" in arch_lower or "audio_cnn" in arch_lower:
                    model = AudioCNN(num_classes=num_classes)
                elif "panns" in arch_lower:
                    try:
                        from training.models.panns_cnn14 import PannsCNN14
                        model = PannsCNN14(in_chans=1, num_classes=num_classes)
                    except ImportError:
                        model = BioacousticModel(
                            model_name="panns_cnn14", num_classes=num_classes,
                            in_chans=1, pretrained=False,
                            pool_type=pool_type,
                        )
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
                        pool_type=pool_type,
                    )

                model.load_state_dict(state_dict)
                model.to(self.device)
                model.eval()
                frontend = None
                if contract is not None:
                    frontend = GPUAudioFrontEnd(
                        sample_rate=contract["sample_rate"], **contract["parameters"]
                    ).to(self.device)
                    frontend.eval()
            except Exception as err:
                if isinstance(err, ModelWeightsError):
                    raise
                raise ModelWeightsError(
                    f"Incompatibilidad de arquitectura o pesos en {self.checkpoint_path}: {err}"
                ) from err

            # Publish identity and metadata only after every load step succeeds.
            if contract is None:
                self._configure_audio(checkpoint)
            self.preprocessing_contract = contract
            self.architecture_name = architecture_name
            self.classes = classes
            self.best_val_acc = best_val_acc
            self.frontend = frontend
            self._loaded_checkpoint_sha256 = loaded_hash
            if hasattr(self, "_metadata"):
                self._metadata.name = self.custom_name or f"Modelo Entrenado: {architecture_name} ({self.checkpoint_path.name})"
                self._metadata.description = f"Inferencia bioacústica con pesos reales entrenados ({architecture_name})"
                self._metadata.target_sr = contract["sample_rate"] if contract else (self.audio_config or {}).get("target_sr", TARGET_SR)
                self._metadata.duration_seconds = contract["duration_seconds"] if contract else (self.audio_config or {}).get("duration_seconds", DURATION_SECONDS)
                self._metadata.classes = classes
                self._metadata.metrics = {
                    "accuracy": round(best_val_acc / 100.0 if best_val_acc and best_val_acc > 1 else (best_val_acc or 0.0), 4)
                }
                self._metadata.loaded_checkpoint_sha256 = loaded_hash
            self.model = model

    @property
    def has_weights(self) -> bool:
        return self.checkpoint_path.exists() and self.checkpoint_path.stat().st_size > 10000

    def _checkpoint_sha256(self) -> Optional[str]:
        """Hash the registered checkpoint file bytes without loading its tensor state."""
        try:
            digest = hashlib.sha256()
            with self.checkpoint_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except Exception:
            # Catalogue metadata is best-effort; never expose filesystem details.
            return None

    @property
    def metadata(self) -> ModelMetadata:
        with self._load_lock:
            self._metadata.is_default = self.is_default
            self._metadata.has_weights = self.has_weights
            self._metadata.checkpoint_sha256 = self._checkpoint_sha256()
            self._metadata.loaded_checkpoint_sha256 = self._loaded_checkpoint_sha256
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

        contract = self.preprocessing_contract
        loaded_checkpoint_sha256 = self._loaded_checkpoint_sha256
        if contract is not None:
            waveform = load_and_fix_length(
                audio_file_path, target_sr=contract["sample_rate"],
                duration_seconds=contract["duration_seconds"],
            )
        elif self.audio_config:
            if self.window_selection == "active_max_rms":
                windows = extract_active_windows(
                    audio_file_path, target_sr=self.audio_config["target_sr"],
                    duration_seconds=self.audio_config["duration_seconds"],
                    hop_seconds=2.5, top_db=25.0,
                )
                waveform = max(windows, key=compute_rms)
            else:
                waveform = load_and_resample(
                    audio_file_path, target_sr=self.audio_config["target_sr"],
                    duration_seconds=self.audio_config["duration_seconds"], strict=True,
                )
        else:
            # Historical checkpoints retain their explicitly legacy preprocessing.
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
                    "loaded_checkpoint_sha256": loaded_checkpoint_sha256,
                    "preprocessing_mode": "gpu_mel_zscore" if contract or self.audio_config else "legacy_librosa",
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
                    "loaded_checkpoint_sha256": loaded_checkpoint_sha256,
                    "preprocessing_mode": "gpu_mel_zscore" if contract or self.audio_config else "legacy_librosa",
                },
            )

        # 3. Extracción de Mel-Spectrogram y pasada PyTorch
        if self.frontend is not None:
            audio_tensor = torch.from_numpy(waveform).unsqueeze(0).float().to(self.device)
            mel_tensor = self.frontend(audio_tensor)
        elif self.audio_config:
            config = self.audio_config
            frontend = GPUAudioFrontEnd(
                sample_rate=config["target_sr"], n_mels=config["n_mels"],
                n_fft=config["n_fft"], hop_length=config["hop_length"],
                f_min=config["f_min"], f_max=config["f_max"],
            ).to(self.device)
            mel_tensor = frontend(torch.from_numpy(waveform).to(self.device))
        else:
            mel = extract_mel_spectrogram(waveform, sr=TARGET_SR, n_mels=self.legacy_n_mels)
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
                "mel_bands": int(mel_tensor.shape[-2]),
                "status": "classified",
                "is_mock": False,
                "loaded_checkpoint_sha256": loaded_checkpoint_sha256,
                "preprocessing_mode": "gpu_mel_zscore" if contract or self.audio_config else "legacy_librosa",
            },
        )


# Stable references keep provenance hashes bound to the production implementation,
# even when tests inject a metadata-only adapter at the class seam.
PREDICT_IMPLEMENTATION = TrainedModelPredictor.predict
MODEL_LOADER_IMPLEMENTATION = TrainedModelPredictor._load_model
LENGTH_IMPLEMENTATION = load_and_fix_length
RMS_IMPLEMENTATION = compute_rms
MEL_IMPLEMENTATION = extract_mel_spectrogram
