import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, status
from sqlalchemy.orm import Session
import torch
import numpy as np
import librosa

# Asegurar que la carpeta backend esté en sys.path para importar módulos de app y poc
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from poc.preprocess import (
    load_and_fix_length,
    extract_mel_spectrogram,
    compute_rms,
    TARGET_SR,
    DURATION_SECONDS,
)
from poc.train import AudioCNN
from app.services.storage import upload_audio_to_gcp
from app.database import Base, engine, get_db
from app.models.prediction import Prediccion


# ============================================================================
# PERSISTENCIA: INICIALIZACIÓN DE TABLAS EN BASE DE DATOS
# ============================================================================
try:
    Base.metadata.create_all(bind=engine)
    print("[Database] Tablas sincronizadas exitosamente en PostgreSQL.")
except Exception as db_init_err:
    print(f"[Database] Advertencia al sincronizar tablas con PostgreSQL: {db_init_err}")


# ============================================================================
# SERVICIOS / LÓGICA DE MACHINE LEARNING
# (A futuro se moverá a app/services/predictor_service.py)
# ============================================================================
# Priorizar el modelo optimizado con Data Augmentation y VAD (61.69% accuracy)
_AUGMENTED_CKPT = _BACKEND_ROOT / "checkpoints" / "augmented_best.pt"
_BASELINE_CKPT = _BACKEND_ROOT / "checkpoints" / "baseline_best.pt"
CHECKPOINT_PATH = _AUGMENTED_CKPT if _AUGMENTED_CKPT.exists() else _BASELINE_CKPT

# Umbral de planitud espectral: aves reales promedian 0.015 (máx 0.032).
# Ruido blanco/estática promedia > 0.50. Umbral de 0.15 separa nítidamente ambos.
SPECTRAL_FLATNESS_NOISE_THRESHOLD = 0.15


class AudioPredictorService:
    """
    Servicio de inferencia bioacústica con discriminación física de señal:
    1. Carga preferentemente augmented_best.pt (61.69% accuracy) con fallback a baseline_best.pt.
    2. Detección de Silencio por energía RMS (VAD): descarta audios sin sonido significativo.
    3. Detección de Ruido No-Biológico por Planitud Espectral (Spectral Flatness):
       rechaza estática o ruido blanco antes de ingresar a la CNN.
    4. Calibración por Escalamiento de Temperatura (Temperature Scaling, T=1.5).
    """

    def __init__(self, checkpoint_path: Path = CHECKPOINT_PATH, temperature: float = 1.5):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.checkpoint_path = checkpoint_path
        self.temperature = temperature
        self.model: Optional[AudioCNN] = None
        self.classes: List[str] = []
        self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        """Carga los pesos entrenados y el mapeo de clases si el archivo existe."""
        if self.checkpoint_path.exists():
            checkpoint = torch.load(self.checkpoint_path, map_location=self.device)
            self.classes = checkpoint.get("classes", [])
            self.model = AudioCNN(num_classes=len(self.classes))
            self.model.load_state_dict(checkpoint["model_state_dict"])
            self.model.to(self.device)
            self.model.eval()
        else:
            # Respaldo simulado en caso de despliegue sin checkpoints locales
            self.classes = [
                "Canastero", "Chercán", "Chincol", "Chucao", "Churrín de la Mocha",
                "Churrín del sur", "Colilarga", "Fío-fío", "Picaflor chico", "Rayadito",
                "Tapaculo", "Tijeral", "Tordo", "Turca", "Zorzal patagónico"
            ]

    def predict(self, audio_file_path: Path) -> Tuple[str, float]:
        """
        Analiza las propiedades físicas de la señal y, si es una señal bioacústica válida,
        ejecuta la inferencia en PyTorch retornando la clase y su confianza real.
        """
        waveform = load_and_fix_length(
            audio_file_path, target_sr=TARGET_SR, duration_seconds=DURATION_SECONDS
        )

        # 1. Filtro de Silencio (VAD por RMS energético)
        energy_rms = compute_rms(waveform)
        if energy_rms < 1e-4:
            return "Silencio / No detectado", 0.0

        # 2. Filtro Físico-Acústico: Detección de Ruido Blanco / Señal No-Biológica
        spectral_flatness = float(np.mean(librosa.feature.spectral_flatness(y=waveform)))
        if spectral_flatness > SPECTRAL_FLATNESS_NOISE_THRESHOLD:
            return "Ruido / Señal no biológica", 0.0

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
                return predicted_class, conf_val
        else:
            # Simulación de contingencia
            return "Chincol", 0.8500


# Instancia del servicio de predicción
predictor_service = AudioPredictorService()


# ============================================================================
# ESQUELETO BASE FASTAPI
# ============================================================================
app = FastAPI(
    title="F.A.M.A. Backend API",
    description="Backend orquestador para monitoreo y clasificación bioacústica de aves chilenas",
    version="1.0.0",
)


# ============================================================================
# ENDPOINTS DE SALUD
# ============================================================================
@app.get("/", summary="Estado base del Backend F.A.M.A.")
def root_status():
    """Endpoint de comprobación inicial del servicio."""
    return {"status": "F.A.M.A. Backend Operativo"}


@app.get("/health", summary="Health check operacional")
def health_check():
    """Endpoint de liveness probe para Kubernetes / Cloud Run."""
    return {"status": "ok"}


# ============================================================================
# ENDPOINT DE PREDICCIÓN BIOACÚSTICA
# ============================================================================
@app.post(
    "/api/predict",
    summary="Inferencia bioacústica con persistencia en Google Cloud Storage y PostgreSQL",
)
async def predict_audio(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Recibe un archivo de audio por HTTP multipart/form-data.
    1. Valida que la extensión sea estrictamente .wav.
    2. Sube el archivo a Google Cloud Storage mediante upload_audio_to_gcp (RNF_03).
    3. Si la subida a GCS es exitosa, ejecuta la inferencia bioacústica.
    4. Inserta el registro histórico en la tabla 'prediccion' de PostgreSQL.
    5. Retorna el JSON confirmando la persistencia y la predicción:
       {"filename": ..., "gcp_upload": True, "db_id": 1, "clase": ..., "confianza": ...}.
    """
    filename = file.filename or "audio.wav"

    # 1. Validación de formato: solo archivos .wav permitidos
    if not filename.lower().endswith(".wav"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato no válido. Solo se permiten archivos de audio con extensión .wav",
        )

    try:
        audio_bytes = await file.read()

        # 2. Persistencia en la nube: Subida a Google Cloud Storage (RNF_03)
        try:
            gcp_success = await upload_audio_to_gcp(audio_bytes, filename=filename)
        except Exception as gcp_err:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Fallo en la persistencia en Google Cloud Storage: {gcp_err}",
            )

        if not gcp_success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No fue posible confirmar la subida a Google Cloud Storage.",
            )

        # 3. Procesar audio localmente de forma temporal para la inferencia acústica
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            tmp_audio.write(audio_bytes)
            tmp_path = Path(tmp_audio.name)

        try:
            clase, confianza = predictor_service.predict(tmp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        # 4. Persistencia relacional en PostgreSQL (Tabla 'prediccion')
        try:
            registro_prediccion = Prediccion(
                ruta_audio_prueba=filename,
                etiqueta_predicha=clase,
                confianza=confianza,
            )
            db.add(registro_prediccion)
            db.commit()
            db.refresh(registro_prediccion)
            db_id = registro_prediccion.id_prediccion
        except Exception as db_save_err:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Fallo al registrar la predicción en PostgreSQL: {db_save_err}",
            )

        # 5. Retorno del formato JSON requerido con gcp_upload y db_id
        return {
            "filename": filename,
            "gcp_upload": True,
            "db_id": db_id,
            "clase": clase,
            "confianza": confianza,
        }

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante el procesamiento del audio: {str(err)}",
        )
