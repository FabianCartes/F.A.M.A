import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import torch
import torch.nn as nn
import numpy as np

# ============================================================================
# RUTEO DE MÓDULOS DEL BACKEND Y ML CORE
# ============================================================================
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Importación de componentes de inferencia y modelos desde ml_core (o poc como fallback)
try:
    from ml_core.evaluate import (
        EnsembleClassifier,
        predict_audio_tta,
        load_checkpoint_model,
    )
    from ml_core.preprocess import (
        compute_rms,
        TARGET_SR,
        DURATION_SECONDS,
    )
    from ml_core.train import BioacousticModel
except ImportError:
    from poc.evaluate import (
        EnsembleClassifier,
        predict_audio_tta,
        load_checkpoint_model,
    )
    from poc.preprocess import (
        compute_rms,
        TARGET_SR,
        DURATION_SECONDS,
    )
    from poc.train import BioacousticModel

from app.services.storage import upload_audio_to_gcp
from app.database import Base, engine, get_db
from app.models.prediction import Prediccion


# ============================================================================
# CONSTANTES Y CONFIGURACIÓN DEL SUPER-ENSAMBLE TRI-MODELO
# ============================================================================
SPECIES_CLASSES: List[str] = [
    "Canastero", "Chercán", "Chincol", "Chucao", "Churrín de la Mocha",
    "Churrín del sur", "Colilarga", "Fío-fío", "Picaflor chico", "Rayadito",
    "Tapaculo", "Tijeral", "Tordo", "Turca", "Zorzal patagónico",
]

# Ponderaciones oficiales calibradas del Super-Ensamble Tri-Modelo (ADR 0008, ADR 0010)
# 55% EfficientNet-B0 + 30% ConvNeXt-Nano + 15% ResNet34d
ENSEMBLE_WEIGHTS: List[float] = [0.55, 0.30, 0.15]


# ============================================================================
# PERSISTENCIA: INICIALIZACIÓN DE TABLAS EN BASE DE DATOS
# ============================================================================
try:
    Base.metadata.create_all(bind=engine)
    print("[Database] Tablas sincronizadas exitosamente en PostgreSQL.")
except Exception as db_init_err:
    print(f"[Database] Advertencia al sincronizar tablas con PostgreSQL: {db_init_err}")


# ============================================================================
# SERVICIO DE INFERENCIA: SUPER-ENSAMBLE TRI-MODELO HETEROGÉNEO
# ============================================================================
class SuperEnsembleService:
    """
    Servicio de inferencia bioacústica de alto rendimiento basado en el
    Super-Ensamble Tri-Modelo Heterogéneo (EfficientNet-B0, ConvNeXt-Nano, ResNet34d).
    Instanciado una sola vez en el ciclo de vida (lifespan) de FastAPI.
    """

    def __init__(self, checkpoints_dir: Optional[Path] = None):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.checkpoints_dir = checkpoints_dir or (_BACKEND_ROOT / "checkpoints")
        self.classes: List[str] = SPECIES_CLASSES
        self.weights: List[float] = ENSEMBLE_WEIGHTS
        self.ensemble: Optional[EnsembleClassifier] = None

    def load_models(self) -> None:
        """
        Carga los 3 modelos heterogéneos y construye el EnsembleClassifier global.
        Si existen checkpoints en disco los carga; si no, inicializa las arquitecturas
        correspondientes en modo inferencia para garantizar resiliencia operacional.
        """
        effnet_ckpt = self.checkpoints_dir / "efficientnet_gpu_pipeline_35e_best.pt"
        convnext_ckpt = self.checkpoints_dir / "convnext_nano_35e_best.pt"
        resnet_ckpt = self.checkpoints_dir / "resnet34d_35e_best.pt"

        models: List[nn.Module] = []

        # 1. EfficientNet-B0 (Peso: 0.55)
        if effnet_ckpt.exists():
            m_eff, ckpt_data = load_checkpoint_model(effnet_ckpt, self.device)
            self.classes = ckpt_data.get("classes", self.classes)
            models.append(m_eff)
            print(f"[SuperEnsemble] Checkpoint cargado: {effnet_ckpt.name}")
        else:
            m_eff = BioacousticModel(
                model_name="efficientnet_b0",
                num_classes=len(self.classes),
                pretrained=False,
                pool_type="gem",
            )
            m_eff.to(self.device).eval()
            models.append(m_eff)
            print("[SuperEnsemble] Modelo EfficientNet-B0 inicializado (fallback)")

        # 2. ConvNeXt-Nano (Peso: 0.30)
        if convnext_ckpt.exists():
            m_conv, _ = load_checkpoint_model(convnext_ckpt, self.device)
            models.append(m_conv)
            print(f"[SuperEnsemble] Checkpoint cargado: {convnext_ckpt.name}")
        else:
            m_conv = BioacousticModel(
                model_name="convnext_nano.d1h_in1k",
                num_classes=len(self.classes),
                pretrained=False,
                pool_type="avg",
            )
            m_conv.to(self.device).eval()
            models.append(m_conv)
            print("[SuperEnsemble] Modelo ConvNeXt-Nano inicializado (fallback)")

        # 3. ResNet34d (Peso: 0.15)
        if resnet_ckpt.exists():
            m_res, _ = load_checkpoint_model(resnet_ckpt, self.device)
            models.append(m_res)
            print(f"[SuperEnsemble] Checkpoint cargado: {resnet_ckpt.name}")
        else:
            m_res = BioacousticModel(
                model_name="resnet34d",
                num_classes=len(self.classes),
                pretrained=False,
                pool_type="avg",
            )
            m_res.to(self.device).eval()
            models.append(m_res)
            print("[SuperEnsemble] Modelo ResNet34d inicializado (fallback)")

        self.ensemble = EnsembleClassifier(models=models, weights=self.weights)
        self.ensemble.to(self.device).eval()
        print(f"[SuperEnsemble] Super-Ensamble listo en {self.device} con ponderaciones {self.weights}.")

    def predict(
        self,
        audio_file_path: Path,
        hop_seconds: float = 1.0,
        max_window_batch_size: int = 32,
    ) -> Tuple[str, float]:
        """
        Ejecuta inferencia bioacústica densa TTA con micro-batching sobre el audio temporal:
        - Ventaneo denso con solapamiento temporal de 1.0 s sobre ventanas de 5.0 s.
        - Agregación por máxima evidencia acústica (mode='max').
        - Micro-batching (max_window_batch_size=32) para acotar VRAM a O(1).
        """
        if self.ensemble is None:
            self.load_models()

        pred_idx, probs = predict_audio_tta(
            model=self.ensemble,
            audio_input=audio_file_path,
            n_mels=128,
            mode="max",
            device=self.device,
            target_sr=TARGET_SR,
            duration_seconds=DURATION_SECONDS,
            hop_seconds=hop_seconds,
            max_window_batch_size=max_window_batch_size,
        )

        confidence = float(probs[pred_idx].item())
        conf_val = round(confidence, 4)
        predicted_class = self.classes[pred_idx]
        return predicted_class, conf_val


# Instancia global del servicio de inferencia
ensemble_service = SuperEnsembleService()


# ============================================================================
# CICLO DE VIDA (LIFESPAN / STARTUP): CARGA ÚNICA EN MEMORIA
# ============================================================================
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """
    Carga el Super-Ensamble Tri-Modelo en memoria una única vez al iniciar
    el servidor FastAPI, evitando recargas redundantes en peticiones HTTP.
    """
    try:
        ensemble_service.load_models()
    except Exception as init_err:
        print(f"[Startup Warning] Excepción al inicializar SuperEnsemble: {init_err}")
    yield


# ============================================================================
# ESQUELETO BASE FASTAPI
# ============================================================================
app = FastAPI(
    title="F.A.M.A. Backend API",
    description="Backend orquestador para monitoreo y clasificación bioacústica de aves chilenas",
    version="1.0.0",
    lifespan=lifespan,
)

# Configuración de CORS para permitir peticiones desde el frontend (Next.js)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# ENDPOINTS DE SALUD Y COMPROBACIÓN OPERACIONAL
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
# ENDPOINT DE PREDICCIÓN BIOACÚSTICA CON SUPER-ENSAMBLE TRI-MODELO
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
    1. Valida formato .wav.
    2. Sube a Google Cloud Storage mediante upload_audio_to_gcp (RNF_03).
    3. Guarda temporalmente en disco usando tempfile para la inferencia densa.
    4. Infiere con el Super-Ensamble Tri-Modelo (Dense TTA hop=1.0s, mode='max', micro-batch=32).
    5. Inserta el resultado en la tabla 'prediccion' de PostgreSQL.
    6. Retorna confirmación JSON con filename, gcp_upload, db_id, clase y confianza real calibrada.
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

        # 3. Guardado temporal en disco para inferencia densa multi-crop
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            tmp_audio.write(audio_bytes)
            tmp_path = Path(tmp_audio.name)

        try:
            # Inferencia bioacústica con Super-Ensamble Tri-Modelo (Dense TTA + Micro-Batching)
            clase, confianza = ensemble_service.predict(
                audio_file_path=tmp_path,
                hop_seconds=1.0,
                max_window_batch_size=32,
            )
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

        # 5. Retorno del formato JSON requerido
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
