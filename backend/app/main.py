import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Form, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
from app.services.ingestion import (
    ingestion_service, IngestionValidationError, IngestionConfigurationError,
    IngestionPayloadTooLarge, IngestionAudioError, IngestionDatasetUnavailable,
)
from app.services.training import training_service
from app.services.dashboard import dashboard_service
from app.services.feedback import feedback_service
from app.services.feedback_sync_worker import FeedbackSyncWorker
from app.services.feedback_sync import FeedbackSyncQueue
from app.database import get_db
from app.models import Prediccion, ConjuntoDatos, Audio, Modelo, MetricaEntrenamiento, Retroalimentacion, Usuario
from app.routes.auth import router as auth_router
from app.routes.auth import WebAuthRoute
from app.routes.access import router as access_router, catalogue_router
from app.routes.users import router as users_router
from app.routes.security import router as security_router
from app.services.web_sessions import current_web_user
from app.services.access import resource_access, ResourceAccess
from app.services.registry import get_model_registry, ModelRegistry, ModelNotFoundError
from app.schemas.model_info import ModelListResponse
from app.schemas.prediction import PredictionResponse
from app.schemas.feedback import FeedbackCreateRequest, ApproveFeedbackResponse, FeedbackSyncState
from app.services.predictors.base import ModelWeightsError
from app.services.predictors.cnn_predictor import AudioCNNPredictor
from training.pipelines.dataset import MalformedAudioError

# Alias de compatibilidad retroactiva para scripts o tests previos
AudioPredictorService = AudioCNNPredictor


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
        from training.paths import get_checkpoints_dir
        self.checkpoints_dir = Path(checkpoints_dir) if checkpoints_dir is not None else get_checkpoints_dir()
        self.classes: List[str] = SPECIES_CLASSES
        self.weights: List[float] = ENSEMBLE_WEIGHTS
        self.ensemble: Optional[EnsembleClassifier] = None
        self.fallback_model: Optional[nn.Module] = None
        self.is_fallback: bool = False
        self.active_models_info: List[dict] = []

    def _find_checkpoint(
        self,
        filename: str,
        extra_dirs: Optional[List[Path]] = None,
    ) -> Optional[Path]:
        """
        Busca un archivo de checkpoint en múltiples rutas candidatas:
        1. extra_dirs (si se provee para pruebas o configuración explícita).
        2. self.checkpoints_dir (backend/checkpoints).
        3. Raíz del repositorio / checkpoints (_BACKEND_ROOT.parent / "checkpoints").
        """
        candidates: List[Path] = []
        if extra_dirs:
            candidates.extend(extra_dirs)
        if self.checkpoints_dir:
            candidates.append(self.checkpoints_dir)
        from app.runtime import runtime_root
        if runtime_root() is None:
            candidates.append(_BACKEND_ROOT.parent / "checkpoints")

        for d in candidates:
            target = d / filename
            if target.exists():
                return target
        return None

    def _checkpoint_available(self, route: str) -> Optional[bool]:
        """Metadata-only presence in configured roots; remote/untrusted paths unknown."""
        if not isinstance(route, str) or "://" in route:
            return None
        path = Path(route)
        from app.runtime import runtime_root
        roots = [self.checkpoints_dir]
        if runtime_root() is None:
            roots.append(_BACKEND_ROOT.parent / "checkpoints")
        if not path.is_absolute() and path.parts and path.parts[0] == "models":
            path = Path(*path.parts[1:])
        if path.suffix.lower() != ".pt" or ".." in path.parts:
            return None
        candidates = [path] if path.is_absolute() else [root / path for root in roots]
        checked = False
        unknown = False
        for candidate in candidates:
            try:
                if not any(candidate.absolute().is_relative_to(root.absolute()) for root in roots):
                    continue
                if not any(candidate.resolve().is_relative_to(root.resolve()) for root in roots):
                    continue
                checked = True
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return True
            except (OSError, RuntimeError):
                unknown = True
        return None if unknown or not checked else False

    def load_models(self) -> None:
        """
        Carga los 3 modelos heterogéneos si los checkpoints .pt existen en disco.
        Si no existen (por estar en .gitignore), conmuta automáticamente al checkpoint
        entrenado disponible (augmented_best.pt) para garantizar predicciones reales
        con alta confianza en lugar de números aleatorios.
        """
        effnet_ckpt = self._find_checkpoint("efficientnet_gpu_pipeline_35e_best.pt")
        convnext_ckpt = self._find_checkpoint("convnext_nano_35e_best.pt")
        resnet_ckpt = self._find_checkpoint("resnet34d_35e_best.pt")
        augmented_ckpt = self._find_checkpoint("augmented_best.pt")

        self.active_models_info = []

        # Caso 1: Al menos uno o todos los checkpoints del Super-Ensamble existen
        if effnet_ckpt or convnext_ckpt or resnet_ckpt:
            models: List[nn.Module] = []
            active_weights: List[float] = []

            if effnet_ckpt:
                m_eff, ckpt_data = load_checkpoint_model(effnet_ckpt, self.device)
                self.classes = ckpt_data.get("classes", self.classes)
                models.append(m_eff)
                active_weights.append(0.55)
                self.active_models_info.append({
                    "name": "EfficientNet-B0",
                    "weight": 0.55,
                    "checkpoint": effnet_ckpt.name,
                })
                print(f"[SuperEnsemble] Checkpoint cargado: {effnet_ckpt.name}")

            if convnext_ckpt:
                m_conv, _ = load_checkpoint_model(convnext_ckpt, self.device)
                models.append(m_conv)
                active_weights.append(0.30)
                self.active_models_info.append({
                    "name": "ConvNeXt-Nano",
                    "weight": 0.30,
                    "checkpoint": convnext_ckpt.name,
                })
                print(f"[SuperEnsemble] Checkpoint cargado: {convnext_ckpt.name}")

            if resnet_ckpt:
                m_res, _ = load_checkpoint_model(resnet_ckpt, self.device)
                models.append(m_res)
                active_weights.append(0.15)
                self.active_models_info.append({
                    "name": "ResNet34d",
                    "weight": 0.15,
                    "checkpoint": resnet_ckpt.name,
                })
                print(f"[SuperEnsemble] Checkpoint cargado: {resnet_ckpt.name}")

            self.ensemble = EnsembleClassifier(models=models, weights=active_weights)
            self.ensemble.to(self.device).eval()
            self.is_fallback = False
            print(f"[SuperEnsemble] Super-Ensamble listo en {self.device} con {len(models)} modelo(s).")

        # Caso 2: Checkpoint entrenado disponible en disco (augmented_best.pt)
        elif augmented_ckpt:
            from poc.train import AudioCNN
            ckpt = torch.load(augmented_ckpt, map_location=self.device)
            self.classes = ckpt.get("classes", self.classes)
            self.fallback_model = AudioCNN(num_classes=len(self.classes))
            self.fallback_model.load_state_dict(ckpt["model_state_dict"])
            self.fallback_model.to(self.device).eval()
            self.is_fallback = True
            self.active_models_info = [{
                "name": "AudioCNN (Baseline)",
                "weight": 1.0,
                "checkpoint": augmented_ckpt.name,
            }]
            print(
                f"[SuperEnsemble] AVISO: Los archivos .pt del tri-modelo no están en disco. "
                f"Conmutando a checkpoint entrenado de respaldo '{augmented_ckpt.name}' para predicciones con pesos reales."
            )
        else:
            self.is_fallback = True
            print("[SuperEnsemble] AVISO: No se encontraron checkpoints entrenados.")

    def get_status(self, dataset_name: Optional[str] = None, db: Optional[Session] = None, access=None) -> dict:
        """
        Observa el servicio bioacústico legacy sin cargar, activar ni inferir.
        Registro, presencia de archivo y carga en memoria son hechos separados.
        is_ready conserva compatibilidad como alias de carga, no prueba de inferencia.
        """
        # Determinar dataset objetivo
        available_datasets = (training_service.get_available_datasets(db=db) if access is None
                              else training_service.get_available_datasets(db=db, access=access))
        available_domains = [d["id"] for d in available_datasets]
        target_ds = dataset_name or "AvesChilenas"
        domain_supported = target_ds == "AvesChilenas"
        normalize_arch = lambda name: name.lower().replace("-", "").replace("_", "")
        loaded = {}
        if target_ds == "AvesChilenas" and self.ensemble is not None and not self.is_fallback:
            for index, info in enumerate(self.active_models_info):
                if index < len(self.ensemble.models):
                    loaded[normalize_arch(info["name"])] = {
                        **info, "weight": self.ensemble.weights[index],
                    }

        # Obtener clases del dataset objetivo
        target_ds_info = next((d for d in available_datasets if d["id"] == target_ds), None)
        if domain_supported and (loaded or (self.is_fallback and self.fallback_model is not None)):
            classes, classes_source = self.classes, "service_loaded_metadata_unverified"
        elif target_ds_info and target_ds_info.get("classes"):
            classes, classes_source = target_ds_info["classes"], "dataset_listing_unverified"
        else:
            classes = self.classes if domain_supported else []
            classes_source = "configured_or_cached_reference" if domain_supported else None

        triad_config = [
            {"name": "EfficientNet-B0", "filename": "efficientnet_gpu_pipeline_35e_best.pt"},
            {"name": "ConvNeXt-Nano", "filename": "convnext_nano_35e_best.pt"},
            {"name": "ResNet-34d", "filename": "resnet34d_35e_best.pt"},
        ]
        if not domain_supported:
            triad_config = []

        triad_status = []
        for item in triad_config:
            arch = item["name"]
            weight = None
            is_ready = False
            accuracy = None
            loss = None
            checkpoint_name = None
            recorded_checkpoint = None
            loaded_checkpoint = None
            updated_at = None
            is_registered = None
            weights_available = self._checkpoint_available(item["filename"])
            weights_source = "configured_candidate"

            # 1. Buscar en PostgreSQL si hay registro para este dataset
            if db is not None:
                try:
                    model_rec = db.query(Modelo).join(
                        ConjuntoDatos, Modelo.id_conjunto_datos == ConjuntoDatos.id_conjunto_datos
                    ).filter(
                        Modelo.arquitectura == arch, ConjuntoDatos.nombre == target_ds
                    ).order_by(Modelo.precision.desc(), Modelo.id_modelo.desc()).first()

                    if model_rec:
                        checkpoint_name = Path(model_rec.ruta_binario_gcp).name
                        recorded_checkpoint = checkpoint_name
                        weights_available = self._checkpoint_available(model_rec.ruta_binario_gcp)
                        weights_source = "registered_reference"
                        updated_at = model_rec.fecha_entrenamiento.isoformat() if model_rec.fecha_entrenamiento else None
                        accuracy = model_rec.precision
                        loss = model_rec.perdida
                        is_registered = True
                    else:
                        is_registered = False
                except Exception:
                    db.rollback()

            # Loaded state comes from observed in-memory models, never DB presence.
            active_match = loaded.get(normalize_arch(arch))
            if active_match:
                is_ready = True
                checkpoint_name = active_match["checkpoint"]
                loaded_checkpoint = checkpoint_name
                weight = active_match["weight"]
                weights_available = self._checkpoint_available(active_match["checkpoint"])
                weights_source = "loaded_checkpoint_file"

            triad_status.append({
                "name": arch,
                "weight": weight,
                "is_ready": is_ready,
                "is_registered": is_registered,
                "is_loaded": is_ready,
                "weights_available": weights_available,
                "weights_source": weights_source,
                "accuracy": accuracy,
                "loss": loss,
                "checkpoint": checkpoint_name,
                "recorded_checkpoint": recorded_checkpoint,
                "loaded_checkpoint": loaded_checkpoint,
                "metrics_source": "database_record" if is_registered is True else None,
                "updated_at": updated_at,
            })

        ensemble_ready = bool(triad_status) and all(m["is_ready"] for m in triad_status)
        ready_count = sum(1 for m in triad_status if m["is_ready"])

        if ensemble_ready:
            active_mode = "ensemble"
            model_name = "Super-Ensamble Tri-Modelo"
        elif ready_count > 1:
            active_mode = "partial_ensemble"
            model_name = f"Ensamble parcial ({ready_count} modelos cargados)"
        elif ready_count > 0:
            active_mode = "individual"
            ready_first = next(m for m in triad_status if m["is_ready"])
            model_name = f"{ready_first['name']} (Modo Individual)"
        elif domain_supported and self.is_fallback and self.fallback_model is not None:
            active_mode = "fallback"
            model_name = "AudioCNN (Fallback)"
        else:
            active_mode = "unavailable"
            model_name = None

        missing_models = [m["name"] for m in triad_status if not m["is_ready"]]
        active_models = [
            {"name": m["name"], "weight": m["weight"], "checkpoint": m["checkpoint"]}
            for m in triad_status if m["is_loaded"]
        ]
        if active_mode == "fallback":
            active_models = list(self.active_models_info)

        return {
            "state_scope": "legacy_bioacoustic_service",
            "domain_supported": domain_supported,
            "selected_domain": target_ds,
            "available_domains": available_domains,
            "ensemble_ready": ensemble_ready,
            "active_mode": active_mode,
            "missing_models": missing_models,
            "triad_status": triad_status,
            "is_fallback": bool(domain_supported and self.is_fallback and self.fallback_model is not None),
            "model_name": model_name,
            "device": str(self.device),
            "active_models": active_models,
            "total_classes": len(classes),
            "classes": classes,
            "classes_source": classes_source,
        }

    def predict(
        self,
        audio_file_path: Path,
        hop_seconds: float = 1.0,
        max_window_batch_size: int = 32,
    ) -> Tuple[str, float]:
        """
        Ejecuta inferencia bioacústica densa TTA con micro-batching sobre el audio temporal.
        """
        if self.ensemble is None and self.fallback_model is None:
            self.load_models()

        if self.is_fallback and self.fallback_model is not None:
            from poc.preprocess import load_and_fix_length, extract_mel_spectrogram
            waveform = load_and_fix_length(audio_file_path, target_sr=TARGET_SR, duration_seconds=DURATION_SECONDS)
            mel = extract_mel_spectrogram(waveform, sr=TARGET_SR, n_mels=64)
            mel_tensor = torch.from_numpy(mel).unsqueeze(0).unsqueeze(0).float().to(self.device)
            with torch.no_grad():
                out = self.fallback_model(mel_tensor)
                probs = torch.softmax(out / 1.5, dim=1)
                confidence, pred_idx = torch.max(probs, dim=1)
                predicted_class = self.classes[pred_idx.item()]
                conf_val = round(float(confidence.item()), 4)
                return predicted_class, conf_val

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
    from app.database import SessionLocal
    worker = FeedbackSyncWorker(SessionLocal, feedback_service.raw_data_dir)
    async with worker.running():
        yield


# ============================================================================
# ESQUELETO BASE FASTAPI
# ============================================================================
app = FastAPI(
    title="F.A.M.A. Backend API",
    description="Backend orquestador multi-modelo para monitoreo y clasificación bioacústica",
    version="1.1.0",
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

# Inclusión de enrutadores modulares
app.include_router(auth_router)
app.include_router(access_router)
app.include_router(catalogue_router)
app.include_router(users_router)
app.include_router(security_router)
from app.routes.partitions import router as partitions_router
app.include_router(partitions_router)
from app.routes.checkpoints import router as checkpoint_router
app.include_router(checkpoint_router)


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


# Secure by default for every functional route registered below this point.
# Public liveness and authentication routes above retain their own policies.
app.router.dependencies.append(Depends(current_web_user))
app.router.route_class = WebAuthRoute


# ============================================================================
# ENDPOINTS DE INFORMACIÓN Y ESTADO DEL SUPER-ENSAMBLE
# ============================================================================
@app.get(
    "/api/model-info",
    summary="Estado pasivo del servicio bioacústico legacy, sin carga de pesos",
)
def get_model_info(
    dataset_name: Optional[str] = None,
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """Observación acotada del servicio legacy; no representa activación del catálogo."""
    access.require_dataset(dataset_name)
    result = ensemble_service.get_status(dataset_name=dataset_name, db=db,
                                         access=None if access.administrator else access)
    if not access.administrator:
        result["available_domains"] = [name for name in result.get("available_domains", []) if name in access.names]
    return result


# ============================================================================
# ENDPOINT DE MÉTRICAS GLOBALES DEL DASHBOARD MLOPS
# ============================================================================
@app.get(
    "/api/dashboard/stats",
    summary="Métricas y estadísticas consolidadas del Dashboard MLOps",
)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Retorna métricas operativas consolidadas de Ingesta, Entrenamiento y Predicción,
    incluyendo KPIs, curvas de convergencia del último modelo, telemetría y feed reciente.
    """
    # Metrics reads must not trigger checkpoint discovery/loading or activation.
    return dashboard_service.get_stats(db=db, access=access)


# ============================================================================
# CATÁLOGO DE MODELOS DE INFERENCIA
# ============================================================================
@app.get(
    "/api/models",
    response_model=ModelListResponse,
    summary="Catálogo de modelos bioacústicos registrados",
)
def list_models(
    only_available: bool = Query(False, description="Si es True, retorna solo modelos con pesos físicos verificados en disco"),
    registry: ModelRegistry = Depends(get_model_registry),
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Retorna la lista de todos los modelos bioacústicos disponibles en el catálogo,
    sus especificaciones técnicas, clases soportadas, disponibilidad de pesos y el modelo por defecto.
    """
    publication_errors = registry.publish_from_db(db, checkpoints_root=training_service.checkpoints_dir)
    if any(error["code"] == "database_unavailable" for error in publication_errors):
        raise HTTPException(status_code=503, detail={
            "message": "Model catalogue publication incomplete",
            "errors": publication_errors,
        })
    models = registry.list_models(only_with_weights=only_available)
    default_id = registry.get_default_model_id() or ""
    if not access.administrator:
        models = [item for item in models if access.model_allowed(item.id, item.dataset_name)]
        visible_ids = {item.id for item in models}
        default_id = default_id if default_id in visible_ids else ""
        registered_ids = {f"fama_trained_model_{row.id_modelo}" for row in access.query(Modelo).all()}
        publication_errors = [item for item in publication_errors if item.get("model_id") in registered_ids]
    return ModelListResponse(
        models=models,
        total=len(models),
        default_model_id=default_id,
        publication_errors=publication_errors,
    )


# ============================================================================
# ENDPOINT DE PREDICCIÓN BIOACÚSTICA
# ============================================================================
@app.post(
    "/api/predict",
    response_model=PredictionResponse,
    summary="Inferencia bioacústica con selección de modelo, persistencia en Google Cloud Storage y PostgreSQL",
)
async def predict_audio(
    file: UploadFile = File(...),
    model_id: Optional[str] = Query(
        None,
        description="Identificador del modelo a utilizar. Si no se especifica, usa el modelo por defecto.",
    ),
    dataset_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    registry: ModelRegistry = Depends(get_model_registry),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Recibe un archivo de audio por HTTP multipart/form-data.
    1. Valida que la extensión sea estrictamente .wav.
    2. Resuelve y valida el modelo solicitado en el ModelRegistry (falla rápido 404 si no existe).
    3. Sube el archivo a Google Cloud Storage mediante upload_audio_to_gcp (RNF_03).
    4. Ejecuta la inferencia bioacústica a través del AudioPredictor correspondiente.
    5. Inserta el registro histórico en la tabla 'prediccion' de PostgreSQL (incluyendo modelo_id).
    6. Retorna el contrato JSON con la predicción, confirmación de GCS y trazabilidad.
    """
    fecha_carga = datetime.now(timezone.utc)
    # Browser names may contain POSIX or Windows paths; retain only bounded metadata.
    nombre_original = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    nombre_original = "".join(char for char in nombre_original if char.isprintable()).strip()[:255] or None
    filename = file.filename or "audio.wav"

    # 1. Validación de formato: solo archivos .wav permitidos
    if not filename.lower().endswith(".wav"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato no válido. Solo se permiten archivos de audio con extensión .wav",
        )

    # 2. Validación y resolución temprana del modelo (evita subir a GCS si el modelo no existe)
    try:
        predictor = registry.get(model_id)
    except ModelNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modelo no encontrado o no asignado.",
        )

    if not access.model_allowed(predictor.model_id, predictor.dataset_name):
        raise HTTPException(404, "Modelo no encontrado o no asignado.")
    try:
        # Catalogue metadata can be stale; recheck the adapter before any upload.
        # This checks storage availability, not architecture compatibility.
        try:
            has_weights = predictor.has_weights
        except Exception as availability_error:
            raise ModelWeightsError("No se pudo comprobar la disponibilidad de pesos.") from availability_error
        if has_weights is not True:
            raise ModelWeightsError(f"Modelo '{predictor.model_id}': archivos de pesos no disponibles.")
        audio_bytes = await file.read()
        from uuid import uuid4
        source_filename = f"{uuid4().hex}.wav"

        # 3. Persistencia en la nube: Subida a Google Cloud Storage (RNF_03)
        try:
            gcp_success = await upload_audio_to_gcp(audio_bytes, filename=source_filename)
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

        # 4. Procesar audio localmente de forma temporal para la inferencia acústica
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            tmp_audio.write(audio_bytes)
            tmp_path = Path(tmp_audio.name)

        try:
            pred_result = predictor.predict(tmp_path)
            clase = pred_result.clase
            confianza = float(pred_result.confianza)
        except MalformedAudioError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio inválido o no soportado. Proporcione un archivo WAV válido.",
            )
        except ModelWeightsError as weights_err:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Modelo '{predictor.model_id}' no disponible para inferencia: {weights_err}",
            )
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        # 5. Persistencia relacional en PostgreSQL (Tabla 'prediccion')
        try:
            registro_prediccion = Prediccion(
                ruta_audio_prueba=f"raw_audios/{source_filename}",
                etiqueta_predicha=clase,
                confianza=confianza,
                modelo_id=predictor.model_id,
                dataset_name=predictor.dataset_name,
                nombre_original=nombre_original,
                fecha_carga=fecha_carga,
            )
            db.add(registro_prediccion)
            access.record_prediction_origin(registro_prediccion)
            db.commit()
            db.refresh(registro_prediccion)
            db_id = registro_prediccion.id_prediccion
        except Exception as db_save_err:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Fallo al registrar la predicción en PostgreSQL: {db_save_err}",
            )

        # 6. Retorno del formato JSON enriquecido
        executed_model_name = predictor.metadata.name
        executed_labels = [executed_model_name]
        detalles = dict(getattr(pred_result, "detalles", None) or {})
        detalles["dataset_name"] = registro_prediccion.dataset_name
        is_fallback = getattr(predictor, "is_fallback", False)

        return {
            "filename": filename,
            "gcp_upload": True,
            "db_id": db_id,
            "clase": clase,
            "confianza": confianza,
            "modelo_id": predictor.model_id,
            "modelo": executed_model_name,
            "is_fallback": is_fallback,
            "modelos_activos": executed_labels,
            "modelos_ejecutados": executed_labels,
            "detalles": detalles,
        }

    except HTTPException:
        raise
    except ModelWeightsError as weights_err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Modelo no disponible para inferencia: {weights_err}",
        )
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante el procesamiento del audio: {str(err)}",
        )



# ============================================================================
# ENDPOINTS DE INGESTA BIDIRECCIONAL GCS ↔ LOCAL (RF_02)
# ============================================================================
class SyncRequest(BaseModel):
    datasets: List[str]
    preprocess: bool = False


@app.get("/api/ingestion/status")
def get_ingestion_status(access: ResourceAccess = Depends(resource_access)):
    """
    Retorna el estado de conexión con Google Cloud Storage, el bucket activo
    y estadísticas globales del Data Lake bioacústico.
    """
    access.require_administrator()
    return ingestion_service.get_storage_status()


@app.get("/api/ingestion/datasets")
def list_ingestion_datasets(access: ResourceAccess = Depends(resource_access)):
    """
    Lista todos los datasets almacenados en GCS bajo el prefijo 'datasets/',
    reportando métricas de archivos, tamaño y estado de sincronización local.
    """
    datasets = (ingestion_service.list_datasets() if access.administrator else
                ingestion_service.list_datasets(dataset_names=access.names))
    if not access.administrator:
        observed = {item["name"] for item in datasets}
        datasets.extend({"id": ds.nombre, "name": ds.nombre,
                         "file_count": ds.cantidad_audios, "total_size_bytes": ds.tamano_total_bytes,
                         "source": "database", "gcs_available": None, "is_synced": None,
                         "local_file_count": None, "gcs_file_count": None}
                        for ds in access.datasets if ds.nombre not in observed)
    try:
        file_limit, batch_limit = ingestion_service.get_upload_limits()
        limits = {"max_file_bytes": file_limit, "max_batch_bytes": batch_limit}
    except IngestionConfigurationError:
        limits = None
    return {"datasets": datasets, "can_create_dataset": access.administrator, "upload_limits": limits}


@app.get("/api/ingestion/datasets/{dataset_name}/files")
def list_ingestion_dataset_files(dataset_name: str, db: Session = Depends(get_db),
                                 access: ResourceAccess = Depends(resource_access)):
    """
    Lista los archivos individuales contenidos en un dataset en GCS.
    """
    access.require_dataset(dataset_name)
    try:
        files = ingestion_service.list_dataset_files(dataset_name, db=db)
    except IngestionValidationError:
        raise HTTPException(status_code=422, detail="Nombre de dataset inválido.") from None
    return {"dataset": dataset_name, "files": files}


@app.post("/api/ingestion/sync")
def sync_ingestion_datasets(req: SyncRequest, db: Session = Depends(get_db),
                           access: ResourceAccess = Depends(resource_access)):
    """
    Ejecuta la sincronización masiva selectiva (RF_02): descarga desde GCS a local
    únicamente archivos nuevos o modificados para los datasets seleccionados.
    Si req.preprocess es True, ejecuta la extracción tensorial Mel (RF_03).
    Persiste metadatos en las tablas 'conjunto_datos' y 'audio' en PostgreSQL (Tablas 6.4 y 6.5).
    """
    for name in req.datasets:
        access.require_dataset(name)
    results = []
    total_dl = 0
    total_skip = 0
    total_fail = 0
    total_prep = 0

    try:
        ingestion_service.validate_dataset_names(req.datasets)
    except IngestionValidationError:
        raise HTTPException(status_code=422, detail="Nombres de dataset inválidos.") from None

    for ds_name in req.datasets:
        try:
            res = ingestion_service.sync_dataset_to_local(ds_name, preprocess=req.preprocess, db=db)
        except IngestionDatasetUnavailable:
            raise HTTPException(status_code=409, detail="El dataset no contiene audios descargables en el bucket actual.") from None
        except IngestionValidationError:
            raise HTTPException(status_code=422, detail="Destino de dataset inválido.") from None
        results.append(res)
        total_dl += res.get("downloaded", 0)
        total_skip += res.get("skipped", 0)
        total_fail += res.get("failed", 0)
        total_prep += res.get("preprocessed", 0)

    has_errors = total_fail > 0 or any(
        item.get("db_error") or (item.get("preprocess_info") or {}).get("failed", 0) > 0
        for item in results
    )
    status = ("partial" if total_dl + total_skip + total_prep > 0 else "failed") if has_errors else "completed"
    return {
        "status": status,
        "results": results,
        "total_downloaded": total_dl,
        "total_skipped": total_skip,
        "total_failed": total_fail,
        "total_preprocessed": total_prep,
    }


@app.post("/api/ingestion/preprocess")
def preprocess_ingestion_datasets(req: SyncRequest, access: ResourceAccess = Depends(resource_access)):
    """Prepare assigned local audio without downloading or registering cloud data."""
    if not req.datasets:
        raise HTTPException(status_code=422, detail="Selecciona al menos un dataset.")
    for name in req.datasets:
        access.require_dataset(name)
    try:
        ingestion_service.validate_dataset_names(req.datasets)
    except IngestionValidationError:
        raise HTTPException(status_code=422, detail="Nombres de dataset inválidos.") from None
    local = ingestion_service.list_local_datasets(dataset_names=set(req.datasets))
    if not set(req.datasets).issubset({item["id"] for item in local}):
        raise HTTPException(status_code=409, detail="La selección contiene un dataset sin audios locales para preprocesar.")
    results = [ingestion_service.preprocess_dataset_to_tensors(name) for name in req.datasets]
    failures = sum(item["failed"] for item in results)
    processed = sum(item["processed"] for item in results)
    return {"status": ("partial" if processed else "failed") if failures else "completed",
            "results": results, "total_processed": processed, "total_failed": failures}


@app.post("/api/ingestion/upload")
async def upload_ingestion_files(
    dataset_name: str = Form(...),
    class_label: str = Form("General"),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Permite cargar nuevos audios (.wav) directamente a la nube GCS dentro de la jerarquía:
    datasets/{dataset_name}/{class_label}/{filename}
    Registra metadatos en PostgreSQL.
    """
    access.require_dataset(dataset_name)
    try:
        max_file_bytes, max_batch_bytes = ingestion_service.get_upload_limits()
    except IngestionConfigurationError:
        raise HTTPException(status_code=503, detail="Configuración de carga no disponible.") from None
    prepared_files = []
    total_bytes = 0
    for f in files:
        content = bytearray()
        while chunk := await f.read(min(1024 * 1024, max_file_bytes - len(content) + 1,
                                      max_batch_bytes - total_bytes + 1)):
            content.extend(chunk)
            total_bytes += len(chunk)
            if len(content) > max_file_bytes or total_bytes > max_batch_bytes:
                raise HTTPException(status_code=413, detail="La carga supera los límites permitidos.")
        prepared_files.append((f.filename, bytes(content)))

    try:
        result = ingestion_service.upload_files_to_gcs(prepared_files, dataset_name, class_label,
                                                       db=db, actor_id=access.user.id)
    except IngestionPayloadTooLarge:
        raise HTTPException(status_code=413, detail="La carga supera los límites permitidos.") from None
    except IngestionConfigurationError:
        raise HTTPException(status_code=503, detail="Configuración de carga no disponible.") from None
    except IngestionAudioError:
        raise HTTPException(status_code=422, detail="Archivo de audio inválido o formato no admitido.") from None
    except IngestionValidationError:
        raise HTTPException(status_code=422, detail="Nombres de carga inválidos.") from None
    return result


# ============================================================================
# ENDPOINTS DE ENTRENAMIENTO Y MÉTRICAS (RF_04, CU_INV_03, CU_INV_04, CU_INV_05)
from app.schemas.training import StartTrainingRequest


@app.get("/api/training/hardware")
def get_training_hardware():
    """
    Retorna la telemetría de GPU/CPU y estado de VRAM/RAM (Figura 6.8).
    """
    return training_service.get_hardware_status()


@app.get("/api/training/datasets")
def get_training_datasets(db: Session = Depends(get_db), access: ResourceAccess = Depends(resource_access)):
    """
    Retorna la lista de datasets disponibles para entrenar (CU_INV_02).
    """
    datasets = training_service.get_available_datasets(db=db, access=access)
    return {"datasets": datasets}


@app.post("/api/training/start")
def start_training_pipeline(req: StartTrainingRequest, access: ResourceAccess = Depends(resource_access)):
    """
    Inicia un entrenamiento en segundo plano utilizando PyTorch (CU_INV_03).
    Soporta modelo individual, pipeline secuencial de la Tríada Completa o Ensamble Dinámico.
    """
    access.require_dataset(req.dataset_name)
    try:
        kwargs = {
            "user_id": access.user.id,
            "dataset_name": req.dataset_name,
            "architecture": req.architecture,
            "epochs": req.epochs,
            "learning_rate": req.learning_rate,
            "weight_decay": req.weight_decay,
            "batch_size": req.batch_size,
            "framework": req.framework,
            "is_tri_model": req.is_tri_model,
            "early_stopping": req.early_stopping,
        }
        if getattr(req, "_explicit_models", False) and req.models is not None:
            kwargs["models"] = [m.model_dump() for m in req.models]
        if req.partition_version is not None:
            kwargs["partition_version"] = req.partition_version
        if req.audio_config is not None:
            kwargs["audio_config"] = req.audio_config.model_dump()
        if req.windowing_config is not None:
            kwargs["windowing_config"] = req.windowing_config.model_dump()
        if req.regularization_config is not None:
            kwargs["regularization_config"] = req.regularization_config.model_dump()

        result = training_service.start_training(**kwargs)
        return result
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))



@app.get("/api/training/progress")
def get_training_progress(access: ResourceAccess = Depends(resource_access)):
    """
    Retorna el progreso en tiempo real, curvas de Loss/Accuracy y logs (IS_02).
    """
    try:
        return training_service.get_progress(user_id=access.user.id, administrator=access.administrator,
                                             allowed_datasets=access.names)
    except PermissionError:
        raise HTTPException(403, "Trabajo no accesible para este usuario.") from None


@app.post("/api/training/stop")
def stop_training_pipeline(access: ResourceAccess = Depends(resource_access)):
    """
    Solicita la detención segura del entrenamiento en ejecución (CU_INV_03 Paso 2.a).
    """
    try:
        return training_service.stop_training(user_id=access.user.id, administrator=access.administrator,
                                              allowed_datasets=access.names)
    except PermissionError:
        raise HTTPException(403, "Trabajo no accesible para este usuario.") from None


@app.get("/api/training/history")
def get_training_history(db: Session = Depends(get_db), access: ResourceAccess = Depends(resource_access)):
    """
    Retorna el historial de modelos entrenados desde PostgreSQL (CU_INV_04).
    """
    history = training_service.get_history(db=db, access=access)
    return {"history": history}


@app.post("/api/training/models/{model_id}/activate")
def activate_model(model_id: int, db: Session = Depends(get_db), access: ResourceAccess = Depends(resource_access)):
    """
    Activa un modelo para inferencias bioacústicas en tiempo real (CU_INV_05).
    """
    access.require_administrator()
    return training_service.set_active_model(model_id=model_id, db=db)


# ============================================================================
# ENDPOINTS DE RETROALIMENTACIÓN ACTIVA Y CURACIÓN SEMI-MANUAL (RF_06)
# ============================================================================
@app.post("/api/feedback", status_code=status.HTTP_201_CREATED)
def record_feedback(req: FeedbackCreateRequest, db: Session = Depends(get_db),
                    access: ResourceAccess = Depends(resource_access)):
    """
    Registra retroalimentación de usuario/experto sobre una inferencia (RF_06, CU_INV_07).
    Si la predicción fue errónea, valida la etiqueta corregida y respalda en GCS.
    """
    access.require_prediction(req.id_prediccion)
    existing = db.query(Retroalimentacion).filter_by(id_prediccion=req.id_prediccion).with_for_update().first()
    if existing is not None and not access.administrator and existing.id_usuario != access.user.id:
        raise HTTPException(403, "No se permite modificar retroalimentación de otro autor.")
    feedback_rec = feedback_service.record_feedback(
        db=db,
        id_prediccion=req.id_prediccion,
        fue_correcta=req.fue_correcta,
        etiqueta_corregida=req.etiqueta_corregida,
        id_usuario=access.user.id,
    )
    return {
        "id_retroalimentacion": feedback_rec.id_retroalimentacion,
        "id_prediccion": feedback_rec.id_prediccion,
        "id_usuario": feedback_rec.id_usuario,
        "fue_correcta": feedback_rec.fue_correcta,
        "etiqueta_corregida": feedback_rec.etiqueta_corregida,
        "procesado": feedback_rec.procesado,
        "fecha_retroalimentacion": (
            feedback_rec.fecha_retroalimentacion.isoformat()
            if feedback_rec.fecha_retroalimentacion
            else None
        ),
    }


@app.get("/api/feedback/sync", response_model=List[FeedbackSyncState])
def get_feedback_sync_states(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """Read recent accepted local milestones; never upload or change outcomes."""
    try:
        return FeedbackSyncQueue().recent(db, limit=limit, access=access)
    except Exception:
        raise HTTPException(status_code=503, detail="Synchronization states unavailable")


@app.get("/api/feedback/pending")
def get_pending_feedback(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Retorna la lista de retroalimentaciones pendientes de curación semi-manual (procesado == False).
    """
    return feedback_service.get_pending_feedback(db=db, limit=limit, access=access)


@app.post("/api/feedback/{id_retroalimentacion}/approve", response_model=ApproveFeedbackResponse)
def approve_feedback(
    id_retroalimentacion: int,
    dataset_name: Optional[str] = Query(
        None, min_length=1, max_length=100,
        description="Compatibilidad legacy: debe coincidir con el destino persistido; no permite cambiarlo.",
    ),
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Aprueba e incorpora el audio en el destino congelado durante la inferencia,
    actualiza metadata.csv y marca el registro como procesado.
    """
    access.require_feedback(id_retroalimentacion)
    return feedback_service.approve_feedback(
        db=db, id_retroalimentacion=id_retroalimentacion, dataset_name=dataset_name, actor_id=access.user.id,
    )


@app.post("/api/feedback/{id_retroalimentacion}/reject")
def reject_feedback(
    id_retroalimentacion: int,
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Descarta la retroalimentación sin alterar los datasets de entrenamiento,
    marcando el registro como procesado.
    """
    access.require_feedback(id_retroalimentacion)
    return feedback_service.reject_feedback(db=db, id_retroalimentacion=id_retroalimentacion)


@app.get("/api/feedback/stats")
def get_feedback_stats(db: Session = Depends(get_db), access: ResourceAccess = Depends(resource_access)):
    """
    Retorna la telemetría consolidada del bucle de retroalimentación activa (RF_06)
    incluyendo conteo de audios pendientes de curación.
    """
    return feedback_service.get_feedback_stats(db=db, access=access)
