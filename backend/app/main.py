import os

# Read process configuration before importing services with runtime side effects.
# Deliberately do not load dotenv here or normalize an invalid operator value.
_APP_STARTUP_POLICY = os.environ.get("FAMA_APP_STARTUP_POLICY", "normal")
if _APP_STARTUP_POLICY not in {"normal", "isolated"}:
    raise ValueError("FAMA_APP_STARTUP_POLICY must be normal or isolated")

import sys
import asyncio
from functools import partial
from time import perf_counter
from pathlib import Path
from typing import Optional, Tuple, List
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Form, Query, Request, Response, status
from app.services.auth import get_current_user, security_bearer
from app.services.imported_identity import imported_user
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
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

from app.middleware.inference_limits import InferenceLimits
from app.services.inference_execution import InferenceExecution
from app.services.inference_input import InvalidInferenceAudio, validate_audio
from app.services.storage import upload_audio_to_gcp
from app.services.ingestion import (
    ingestion_service, IngestionValidationError, IngestionConfigurationError,
    IngestionPayloadTooLarge, IngestionAudioError,
)
from app.services.training import training_service
from app.services.dashboard import dashboard_service
from app.services.feedback import feedback_service
from app.services.feedback_sync_worker import FeedbackSyncWorker
from app.services.feedback_sync import FeedbackSyncQueue
from app.database import Base, engine, get_db
from app.models import Prediccion, ConjuntoDatos, Audio, Modelo, MetricaEntrenamiento, Retroalimentacion, Usuario
from app.routes.auth import router as auth_router
from app.routes.dataset_imports import router as dataset_import_router
from app.services.registry import get_model_registry, ModelRegistry, ModelNotFoundError
from app.services.evaluation_catalogue import read_model_evaluations
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
# PERSISTENCIA: INICIALIZACIÓN DE TABLAS EN BASE DE DATOS
# ============================================================================
if _APP_STARTUP_POLICY == "normal":
    try:
        # Imported provenance is migrated explicitly, even if a maintenance module
        # registered its ORM table before this entrypoint. Keep legacy bootstrap intact.
        Base.metadata.create_all(bind=engine, tables=[
            table for table in Base.metadata.tables.values()
            if table.name not in {"imported_model_source", "sesion_web", "cuota_acceso", "evento_seguridad"}
        ])
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
        roots = [self.checkpoints_dir, _BACKEND_ROOT.parent / "checkpoints"]
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

    def get_status(self, dataset_name: Optional[str] = None, db: Optional[Session] = None) -> dict:
        """
        Observa el servicio bioacústico legacy sin cargar, activar ni inferir.
        Registro, presencia de archivo y carga en memoria son hechos separados.
        is_ready conserva compatibilidad como alias de carga, no prueba de inferencia.
        """
        # Determinar dataset objetivo
        available_datasets = training_service.get_available_datasets(db=db)
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
    La política isolated omite únicamente los efectos de startup de este módulo.
    """
    if _APP_STARTUP_POLICY == "isolated":
        yield
        return

    try:
        ensemble_service.load_models()
    except Exception as init_err:
        print(f"[Startup Warning] Excepción al inicializar SuperEnsemble: {init_err}")
    try:
        from app.database import SessionLocal
        from app.services.auth import seed_initial_admin
        with SessionLocal() as db_session:
            seed_initial_admin(db_session)
    except Exception as seed_err:
        print(f"[Startup Warning] Excepción al realizar seeding inicial: {seed_err}")
    from app.database import SessionLocal
    try:
        registry = get_model_registry()
        with SessionLocal() as db_session:
            failures = registry.prewarm_from_db(
                db_session, checkpoints_root=training_service.checkpoints_dir)
        if failures:
            print(f"[Startup Warning] Metadata prewarm skipped {failures} unavailable models.")
    except Exception:
        # Never expose private identities, paths or database diagnostics here.
        print("[Startup Warning] Metadata prewarm unavailable.")
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

inference_execution = InferenceExecution()
MAX_INFERENCE_BODY_BYTES = 110 * 1024 * 1024
INFERENCE_WAIT_SECONDS = 270
app.add_middleware(InferenceLimits, execution=inference_execution,
                   body_limit=lambda: MAX_INFERENCE_BODY_BYTES,
                   wait_seconds=lambda: INFERENCE_WAIT_SECONDS)

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
app.include_router(dataset_import_router)
from app.routes.imported_training import router as imported_training_router
app.include_router(imported_training_router)
from app.routes.prediction_history import router as prediction_history_router
app.include_router(prediction_history_router)


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
# ENDPOINTS DE INFORMACIÓN Y ESTADO DEL SUPER-ENSAMBLE
# ============================================================================
@app.get(
    "/api/model-info",
    summary="Estado pasivo del servicio bioacústico legacy, sin carga de pesos",
)
def get_model_info(
    dataset_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Observación acotada del servicio legacy; no representa activación del catálogo."""
    return ensemble_service.get_status(dataset_name=dataset_name, db=db)


# ============================================================================
# ENDPOINT DE MÉTRICAS GLOBALES DEL DASHBOARD MLOPS
# ============================================================================
@app.get(
    "/api/dashboard/stats",
    summary="Métricas y estadísticas consolidadas del Dashboard MLOps",
)
def get_dashboard_stats(
    db: Session = Depends(get_db),
):
    """
    Retorna métricas operativas consolidadas de Ingesta, Entrenamiento y Predicción,
    incluyendo KPIs, curvas de convergencia del último modelo, telemetría y feed reciente.
    """
    # Metrics reads must not trigger checkpoint discovery/loading or activation.
    return dashboard_service.get_stats(db=db)


# ============================================================================
# CATÁLOGO DE MODELOS DE INFERENCIA
# ============================================================================
@app.get(
    "/api/models",
    response_model=ModelListResponse,
    summary="Catálogo de modelos bioacústicos registrados",
)
def list_models(
    request: Request,
    response: Response,
    only_available: bool = Query(False, description="Si es True, retorna solo modelos con pesos físicos verificados en disco"),
    registry: ModelRegistry = Depends(get_model_registry),
    db: Session = Depends(get_db),
    include_imported: bool = Query(False, description="Añade solo modelos importados del usuario activo autenticado; no cambia el default global"),
    private_only: bool = Query(False, description="Solo modelos privados propios; exige autenticación y no cambia el default global"),
    credentials=Depends(security_bearer),
):
    """
    Retorna la lista de todos los modelos bioacústicos disponibles en el catálogo,
    sus especificaciones técnicas, clases soportadas, disponibilidad de pesos y el modelo por defecto.
    Por defecto conserva el catálogo público legacy. include_imported=true exige
    identidad activa cookie/Bearer y añade solo los importados de ese propietario.
    """
    user = imported_user(request, response, credentials, db) if include_imported or private_only else None
    owner_scope = {"owner_id": user.id} if user is not None else {}
    admitted_pair_ids = {}
    publication_errors = registry.publish_from_db(
        db, checkpoints_root=training_service.checkpoints_dir,
        admitted_pair_ids=admitted_pair_ids,
        **owner_scope,
    )
    if any(error["code"] == "database_unavailable" for error in publication_errors):
        raise HTTPException(status_code=503, detail={
            "message": "Model catalogue publication incomplete",
            "errors": [{"code": "database_unavailable"}] if private_only else publication_errors,
        })
    models = registry.list_models(only_with_weights=only_available, private_only=private_only, **owner_scope)
    if private_only:
        # Publication also checks public rows; none of their diagnostics belong
        # to this private catalogue (including unpublished/unknown identities).
        publication_errors = []
    evaluations = read_model_evaluations(db, models, admitted_pair_ids)
    for model in models:
        model.evaluations = evaluations.by_model_id.get(model.id)
    default_id = "" if private_only else registry.get_default_model_id() or ""
    return ModelListResponse(
        models=models,
        total=len(models),
        default_model_id=default_id,
        publication_errors=publication_errors,
        evaluation_catalogue_status="available" if evaluations.available else "unavailable",
        evaluation_catalogue_error=evaluations.error_code,
    )


# ============================================================================
# ENDPOINT DE PREDICCIÓN BIOACÚSTICA
# ============================================================================
MAX_AUDIO_BYTES = 100 * 1024 * 1024


@app.post(
    "/api/predict",
    response_model=PredictionResponse,
    summary="Inferencia bioacústica con selección de modelo, persistencia en Google Cloud Storage y PostgreSQL",
)
async def predict_audio(
    file: UploadFile = File(...),
    model_id: Optional[str] = Query(
        None,
        description="ID o alias exacto del modelo; los importados requieren su propietario autenticado. Omitirlo conserva el default público.",
    ),
    dataset_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    registry: ModelRegistry = Depends(get_model_registry),
    request: Request = None,
    response: Response = None,
    credentials=Depends(security_bearer),
):
    """
    Recibe un archivo de audio por HTTP multipart/form-data.
    1. Valida que la extensión sea estrictamente .wav.
    2. Resuelve y valida el modelo solicitado en el ModelRegistry (falla rápido 404 si no existe).
    3. Para modelos importados conserva audio local privado; el flujo legacy conserva GCS.
    4. Ejecuta la inferencia bioacústica a través del AudioPredictor correspondiente.
    5. Inserta el registro histórico en la tabla 'prediccion' de PostgreSQL (incluyendo modelo_id).
    6. Retorna persistencia local/cloud veraz; no sincroniza GCS para modelos importados.
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

    # Public cached models retain legacy selection without a new DB preflight.
    # Both initial and owner-scoped resolution share the HTTP error mapping.
    try:
        try:
            predictor = registry.get(model_id)
        except ModelNotFoundError:
            if not model_id or model_id == "default":
                raise
            from sqlalchemy import inspect
            from sqlalchemy.exc import SQLAlchemyError
            from urllib.parse import urlparse, unquote
            owner_id, private_key = None, None
            try:
                if inspect(db.get_bind()).has_table("imported_model_source"):
                    from app.models.imported_training_source import ImportedModelSource
                    matches = []
                    for model, source in db.query(Modelo, ImportedModelSource).join(
                            ImportedModelSource, ImportedModelSource.model_id == Modelo.id_modelo).all():
                        route = urlparse(model.ruta_binario_gcp)
                        basename = Path(unquote(route.path) if route.scheme else model.ruta_binario_gcp).name
                        key = f"fama_trained_model_{model.id_modelo}"
                        if model_id in (key, str(model.id_modelo), basename, Path(basename).stem):
                            matches.append((key, source.owner_id))
                    if matches:
                        user = imported_user(request, response, credentials, db)
                        if len(matches) != 1 or user.id != matches[0][1]:
                            raise HTTPException(status_code=404, detail="Modelo no disponible.")
                        private_key, owner_id = matches[0][0], user.id
                        registry.publish_from_db(db, checkpoints_root=training_service.checkpoints_dir,
                                                 owner_id=owner_id)
            except SQLAlchemyError:
                db.rollback()
                raise HTTPException(status_code=503, detail="Catálogo de modelos temporalmente no disponible.") from None
            if private_key is None:
                raise
            predictor = registry.get(private_key, owner_id=owner_id)
    except ModelNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        )
    except ModelWeightsError as weights_err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Modelo no disponible para inferencia: {weights_err}",
        )
    local_store, local_owner, local_key = None, None, None
    imported_identity = getattr(predictor, "imported_source", None)
    if imported_identity is not None:
        user = imported_user(request, response, credentials, db)
        if not isinstance(imported_identity, dict) or imported_identity.get("owner_id") != user.id:
            raise HTTPException(status_code=404, detail="Modelo no disponible.")
        import os
        from app.services.local_prediction_audio import LocalPredictionAudio
        root = feedback_service.import_root or os.environ.get("FAMA_IMPORT_ROOT")
        if not root:
            raise HTTPException(status_code=503, detail="Almacenamiento local de inferencia no disponible.")
        local_store, local_owner = LocalPredictionAudio(root), user.id
    lease = getattr(request.state, "inference_lease", None) if request is not None else None
    owns_lease = lease is None
    if owns_lease:
        lease = inference_execution.acquire()
    if lease is None:
        raise HTTPException(status_code=503, detail="Inferencia ocupada. Intente nuevamente más tarde.",
                            headers={"Retry-After": "5"})

    total_started, request_outcome = perf_counter(), "ok"
    try:
        # Storage availability is separate from architecture compatibility.
        try:
            has_weights = predictor.has_weights
        except Exception as availability_error:
            raise ModelWeightsError("No se pudo comprobar la disponibilidad de pesos.") from availability_error
        if has_weights is not True:
            raise ModelWeightsError(f"Modelo '{predictor.model_id}': archivos de pesos no disponibles.")
        with lease.stage("read"):
            audio_buffer = bytearray()
            while True:
                chunk = await file.read(min(1024 * 1024, MAX_AUDIO_BYTES + 1 - len(audio_buffer)))
                if not chunk:
                    break
                if len(audio_buffer) + len(chunk) > MAX_AUDIO_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="El archivo supera el límite de 100 MiB (104.857.600 bytes).",
                    )
                audio_buffer.extend(chunk)
            audio_bytes = bytes(audio_buffer)
            del audio_buffer
        try:
            await lease.run(validate_audio, audio_bytes, stage="validation")
        except InvalidInferenceAudio as audio_error:
            raise HTTPException(status_code=400, detail=str(audio_error))
        from uuid import uuid4
        source_filename = f"{uuid4().hex}.wav"

        # Imported private inference is local-first. Legacy uploads retain their
        # existing contract; no cloud attempt is made for imported predictions.
        gcp_success = False
        if local_store is None:
            # 3. Persistencia en la nube: Subida a Google Cloud Storage (RNF_03)
            try:
                gcp_success = await upload_audio_to_gcp(
                    audio_bytes, filename=source_filename, timeout=60,
                    thread_runner=partial(lease.run, stage="upload"),
                )
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Fallo en la persistencia en Google Cloud Storage.",
                ) from None

            if not gcp_success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No fue posible confirmar la subida a Google Cloud Storage.",
                )

        # 4. Keep synchronous inference off the event loop; never pass db to its thread.
        try:
            pred_result = await lease.predict(predictor, audio_bytes)
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

        if local_store is not None:
            try:
                local_key = await lease.run(local_store.save, local_owner, audio_bytes, stage="persist")
            except Exception:
                raise HTTPException(status_code=503, detail="No fue posible guardar el audio local de la predicción.") from None

        # 5. Persistencia relacional en PostgreSQL (Tabla 'prediccion')
        try:
            with lease.stage("persist"):
                registro_prediccion = Prediccion(
                    ruta_audio_prueba=local_key or f"raw_audios/{source_filename}",
                    etiqueta_predicha=clase,
                    confianza=confianza,
                    modelo_id=predictor.model_id,
                    dataset_name=("imported:" + imported_identity["dataset_id"]
                                  if local_store is not None else predictor.dataset_name),
                    nombre_original=nombre_original,
                    fecha_carga=fecha_carga,
                )
                db.add(registro_prediccion)
                db.commit()
                db.refresh(registro_prediccion)
                db_id = registro_prediccion.id_prediccion
        except Exception as db_save_err:
            db.rollback()
            if local_key is not None:
                # A failed response/refresh is not proof of a failed commit.
                # Remove only our new file after proving no persisted reference.
                try:
                    referenced = db.query(Prediccion).filter_by(ruta_audio_prueba=local_key).first()
                    if referenced is None:
                        await lease.run(local_store.discard, local_owner, local_key, stage="persist")
                except Exception:
                    # Retain an uncertain source rather than delete referenced data.
                    pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=("No fue posible registrar la predicción local." if local_store is not None
                        else f"Fallo al registrar la predicción en PostgreSQL: {db_save_err}"),
            )

        # 6. Retorno del formato JSON enriquecido
        executed_model_name = predictor.metadata.name
        executed_labels = [executed_model_name]
        detalles = dict(getattr(pred_result, "detalles", None) or {})
        # Only result-level weights prove participation in this execution. Catalogue
        # metadata/global readiness cannot establish members (e.g. silence bypasses).
        execution_weights = detalles.get("ensemble_weights")
        active_labels = None
        if isinstance(execution_weights, dict) and execution_weights:
            if all(
                isinstance(name, str) and name.strip()
                and isinstance(weight, (int, float)) and not isinstance(weight, bool)
                and np.isfinite(weight) and 0 <= weight <= 1
                for name, weight in execution_weights.items()
            ):
                active_labels = [
                    f"{name} ({int(round(weight * 100))}%)"
                    for name, weight in execution_weights.items()
                ]
        detalles["dataset_name"] = registro_prediccion.dataset_name
        is_fallback = getattr(predictor, "is_fallback", None)
        if is_fallback is None and detalles.get("is_mock") is False:
            is_fallback = False

        return {
            "filename": filename,
            "gcp_upload": bool(gcp_success),
            **({"local_audio_saved": True, "cloud_status": "deferred"} if local_key is not None else {}),
            "db_id": db_id,
            "clase": clase,
            "confianza": confianza,
            "modelo_id": predictor.model_id,
            "modelo": executed_model_name,
            "is_fallback": is_fallback,
            "modelos_activos": active_labels,
            "modelos_ejecutados": executed_labels,
            "detalles": detalles,
        }

    except asyncio.CancelledError:
        request_outcome = "cancelled"
        raise
    except HTTPException:
        request_outcome = "error"
        raise
    except ModelWeightsError as weights_err:
        request_outcome = "error"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Modelo no disponible para inferencia: {weights_err}",
        )
    except Exception as err:
        request_outcome = "error"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante el procesamiento del audio: {str(err)}",
        )
    finally:
        if owns_lease:
            lease.release()
            lease.record("total", total_started, request_outcome)



# ============================================================================
# ENDPOINTS DE INGESTA BIDIRECCIONAL GCS ↔ LOCAL (RF_02)
# ============================================================================
def validate_ingestion_segment(value: str) -> str:
    """Legacy routes accept a name, never a relative filesystem reference."""
    import unicodedata
    if (not value or value in (".", "..") or value.startswith((".", "__"))
            or any(c in value for c in "/\\")
            or any(unicodedata.category(c).startswith("C") for c in value)):
        raise ValueError("Dataset and class names must be safe single path segments")
    return value


class SyncRequest(BaseModel):
    datasets: List[str]
    preprocess: bool = False

    @field_validator("datasets")
    @classmethod
    def safe_destinations(cls, values):
        return [validate_ingestion_segment(value) for value in values]


@app.get("/api/ingestion/status")
def get_ingestion_status():
    """
    Retorna el estado de conexión con Google Cloud Storage, el bucket activo
    y estadísticas globales del Data Lake bioacústico.
    """
    return ingestion_service.get_storage_status()


@app.get("/api/ingestion/datasets")
def list_ingestion_datasets():
    """
    Lista todos los datasets almacenados en GCS bajo el prefijo 'datasets/',
    reportando métricas de archivos, tamaño y estado de sincronización local.
    """
    datasets = ingestion_service.list_datasets()
    return {"datasets": datasets}


@app.get("/api/ingestion/datasets/{dataset_name}/files")
def list_ingestion_dataset_files(
    dataset_name: str, db: Session = Depends(get_db),
    browse: bool = Query(False, description="Opt-in bounded, read-only audio browser."),
    class_name: Optional[str] = Query(None, description="Exact real class; intersects feedback."),
    feedback: Optional[bool] = Query(None, description="Filter confirmed incorporated feedback origin."),
    limit: int = Query(50, ge=1, le=200, description="Browse page size; inventory enumeration remains eager."),
    cursor: Optional[str] = Query(None, description="Opaque cursor bound to dataset, filters and inventory snapshot."),
):
    """Legacy full list by default; browse adds full facets and snapshot-bound pages.

    Shared rows are read-only. Cursor mismatch is 422; inventory drift is 409.
    No cloud streaming or individual download is provided by browsing.
    """
    try:
        validate_ingestion_segment(dataset_name)
        if browse:
            return ingestion_service.browse_dataset_files(
                dataset_name, db=db, class_name=class_name, feedback=feedback,
                limit=limit, cursor=cursor)
        files = ingestion_service.list_dataset_files(dataset_name, db=db)
    except ValueError:
        raise HTTPException(status_code=422, detail="Nombre de dataset inválido.") from None
    return {"dataset": dataset_name, "files": files}


@app.post("/api/ingestion/sync")
def sync_ingestion_datasets(req: SyncRequest, db: Session = Depends(get_db)):
    """
    Ejecuta la sincronización masiva selectiva (RF_02): descarga desde GCS a local
    únicamente archivos nuevos o modificados para los datasets seleccionados.
    Si req.preprocess es True, ejecuta la extracción tensorial Mel (RF_03).
    Persiste metadatos en las tablas 'conjunto_datos' y 'audio' en PostgreSQL (Tablas 6.4 y 6.5).
    """
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


@app.post("/api/ingestion/upload")
async def upload_ingestion_files(
    dataset_name: str = Form(...),
    class_label: str = Form("General"),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    Permite cargar nuevos audios (.wav) directamente a la nube GCS dentro de la jerarquía:
    datasets/{dataset_name}/{class_label}/{filename}
    Registra metadatos en PostgreSQL.
    """
    try:
        validate_ingestion_segment(dataset_name)
        validate_ingestion_segment(class_label)
    except ValueError:
        raise HTTPException(status_code=422, detail="Nombres de carga inválidos.") from None
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
        result = ingestion_service.upload_files_to_gcs(prepared_files, dataset_name, class_label, db=db)
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
from app.services.imported_training_source import ImportedSourceError


@app.get("/api/training/hardware")
def get_training_hardware():
    """
    Retorna la telemetría de GPU/CPU y estado de VRAM/RAM (Figura 6.8).
    """
    return training_service.get_hardware_status()


@app.get("/api/training/datasets")
def get_training_datasets(request: Request, response: Response, db: Session = Depends(get_db), include_imported: bool = False,
                          include_unavailable: bool = False, credentials=Depends(security_bearer)):
    """
    Retorna la lista de datasets disponibles para entrenar (CU_INV_02).
    include_imported=true exige usuario activo y añade solo sus fuentes preparadas.
    Los motivos de elegibilidad no acreditan pesos, ejecución ni evaluación.
    """
    user = imported_user(request, response, credentials, db) if include_imported else None
    # Opt-in projection only; preserve the historical call and response by default.
    datasets = (training_service.get_available_datasets(db=db, include_unavailable=True)
                if include_unavailable else training_service.get_available_datasets(db=db))
    if include_imported:
        from app.services.imported_training_source import configured_sources
        from app.database import SessionLocal
        try:
            sources = training_service.imported_sources or configured_sources(SessionLocal)
            datasets += sources.catalog(user.id)
        except ImportedSourceError as exc:
            raise HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)})
    return {"datasets": datasets}


@app.post("/api/training/start")
def start_training_pipeline(req: StartTrainingRequest, request: Request, response: Response, credentials=Depends(security_bearer),
                            db: Session = Depends(get_db)):
    """
    Inicia un entrenamiento en segundo plano utilizando PyTorch (CU_INV_03).
    Legacy soporta modelo individual, Tríada Completa o Ensamble Dinámico.
    Importados exigen Bearer activo y dataset/snapshot/versión propios explícitos;
    usan una arquitectura/perfil preparado, sin rutas del cliente ni fallback legacy.
    started solo acredita admisión; checkpoint_persisted queda pendiente de evaluación.
    """
    owner = imported_user(request, response, credentials, db) if req.imported_dataset_id is not None else None
    try:
        kwargs = {
            "dataset_name": req.dataset_name,
            "architecture": req.architecture,
            "epochs": req.epochs,
            "learning_rate": req.learning_rate,
            "weight_decay": req.weight_decay,
            "batch_size": req.batch_size,
            "framework": req.framework,
            "is_tri_model": req.is_tri_model,
            "seed": req.seed,
            "early_stopping": req.early_stopping,
        }
        if owner is not None:
            kwargs.update(imported_dataset_id=req.imported_dataset_id, snapshot_id=req.snapshot_id,
                          imported_prepared_version=req.imported_prepared_version, owner_id=owner.id)
        if getattr(req, "_explicit_models", False) and req.models is not None:
            kwargs["models"] = [m.model_dump() for m in req.models]
        if req.prepared_version is not None:
            kwargs["prepared_version"] = req.prepared_version
        if req.allow_historical_preparation:
            kwargs["allow_historical_preparation"] = True
        if req.audio_config is not None:
            kwargs["audio_config"] = req.audio_config.model_dump()
        if req.windowing_config is not None:
            kwargs["windowing_config"] = req.windowing_config.model_dump()
        if req.regularization_config is not None:
            kwargs["regularization_config"] = req.regularization_config.model_dump()

        result = training_service.start_training(**kwargs)
        return result
    except ImportedSourceError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))



def _training_resource_owner(request, response, credentials, db, *, required=False):
    current_owner = training_service.current_source_owner
    user = imported_user(request, response, credentials, db) if required or current_owner is not None else None
    if current_owner is not None and user.id != current_owner:
        raise HTTPException(status_code=404, detail="Recurso de entrenamiento no disponible.")
    return user.id if user else None


@app.get("/api/training/progress")
def get_training_progress(request: Request, response: Response, credentials=Depends(security_bearer), db: Session = Depends(get_db)):
    """
    Retorna el progreso en tiempo real, curvas de Loss/Accuracy y logs (IS_02).
    """
    owner = _training_resource_owner(request, response, credentials, db)
    try:
        return training_service.get_progress(owner_id=owner)
    except ImportedSourceError:
        raise HTTPException(status_code=404, detail="Recurso de entrenamiento no disponible.")


@app.post("/api/training/stop")
def stop_training_pipeline(request: Request, response: Response, credentials=Depends(security_bearer), db: Session = Depends(get_db)):
    """
    Solicita la detención segura del entrenamiento en ejecución (CU_INV_03 Paso 2.a).
    """
    owner = _training_resource_owner(request, response, credentials, db)
    try:
        return training_service.stop_training(owner_id=owner)
    except ImportedSourceError:
        raise HTTPException(status_code=404, detail="Recurso de entrenamiento no disponible.")


@app.get("/api/training/history")
def get_training_history(request: Request, response: Response, db: Session = Depends(get_db), include_imported: bool = False,
                         credentials=Depends(security_bearer)):
    """
    Retorna el historial de modelos entrenados desde PostgreSQL (CU_INV_04).
    Por defecto excluye importados; include_imported=true autentica y añade solo los propios.
    """
    user = imported_user(request, response, credentials, db) if include_imported else None
    history = training_service.get_history(db=db, owner_id=user.id if include_imported and user else None)
    return {"history": history}


@app.post("/api/training/models/{model_id}/activate")
def activate_model(model_id: int, request: Request, response: Response, db: Session = Depends(get_db), credentials=Depends(security_bearer)):
    """
    Activa un modelo para inferencias bioacústicas en tiempo real (CU_INV_05).
    """
    from sqlalchemy import inspect
    source_owner = None
    if inspect(db.get_bind()).has_table("imported_model_source"):
        from app.models.imported_training_source import ImportedModelSource
        association = db.get(ImportedModelSource, model_id)
        source_owner = association.owner_id if association else None
    user = imported_user(request, response, credentials, db) if source_owner is not None else None
    if source_owner is not None and user.id != source_owner:
        raise HTTPException(status_code=404, detail="Recurso de entrenamiento no disponible.")
    return training_service.set_active_model(model_id=model_id, db=db)


# ============================================================================
# ENDPOINTS DE RETROALIMENTACIÓN ACTIVA Y CURACIÓN SEMI-MANUAL (RF_06)
# ============================================================================
def _feedback_imported_user(db, prediction_id, request, response, credentials):
    """Authenticate imported feedback by its persisted model association, never a client owner."""
    from sqlalchemy import inspect
    from app.models.prediction import Prediccion
    if prediction_id is None:
        return None
    prediction = db.get(Prediccion, prediction_id)
    if prediction is None:
        return None
    from app.services.imported_feedback import imported_model_id
    model_id = imported_model_id(prediction.modelo_id)
    association = None
    if model_id is not None and inspect(db.get_bind()).has_table("imported_model_source"):
        from app.models.imported_training_source import ImportedModelSource
        association = db.get(ImportedModelSource, model_id)
    private = str(prediction.dataset_name or "").startswith("imported:")
    if association is None and not private:
        return None
    user = imported_user(request, response, credentials, db)
    if (association is None or user.id != association.owner_id
            or prediction.dataset_name != "imported:" + association.dataset_id):
        raise HTTPException(status_code=404, detail="Retroalimentación no disponible.")
    return user


def _feedback_prediction_id(db, feedback_id):
    from app.models.feedback import Retroalimentacion
    feedback = db.get(Retroalimentacion, feedback_id)
    return feedback.id_prediccion if feedback is not None else None


def _feedback_visible_prediction_ids(db, request, response, credentials):
    """Scope SQL before aggregation or pagination; anonymous callers see legacy only."""
    from sqlalchemy import String, and_, cast, inspect, or_
    from app.models.prediction import Prediccion
    user = None
    if credentials is not None or request.cookies:
        try:
            user = imported_user(request, response, credentials, db)
        except HTTPException as error:
            if error.status_code not in (401, 404):
                raise
    legacy = or_(Prediccion.dataset_name.is_(None),
                 ~Prediccion.dataset_name.startswith("imported:"))
    visible = legacy
    if inspect(db.get_bind()).has_table("imported_model_source"):
        from app.models.imported_training_source import ImportedModelSource
        stored_id = cast(ImportedModelSource.model_id, String)
        association = db.query(ImportedModelSource).filter(or_(
            Prediccion.modelo_id == stored_id,
            Prediccion.modelo_id == "fama_trained_model_" + stored_id))
        visible = and_(legacy, ~association.exists())
        if user is not None:
            owned = association.filter(ImportedModelSource.owner_id == user.id,
                Prediccion.dataset_name == "imported:" + ImportedModelSource.dataset_id).exists()
            visible = or_(visible, owned)
    return db.query(Prediccion.id_prediccion).filter(visible)


@app.post("/api/feedback", status_code=status.HTTP_201_CREATED)
def record_feedback(req: FeedbackCreateRequest, request: Request, response: Response,
                    db: Session = Depends(get_db), credentials=Depends(security_bearer)):
    """
    Registra retroalimentación de usuario/experto sobre una inferencia (RF_06, CU_INV_07).
    Si la predicción fue errónea, valida la etiqueta corregida y respalda en GCS.
    """
    user = _feedback_imported_user(db, req.id_prediccion, request, response, credentials)
    feedback_rec = feedback_service.record_feedback(
        db=db,
        id_prediccion=req.id_prediccion,
        fue_correcta=req.fue_correcta,
        etiqueta_corregida=req.etiqueta_corregida,
        id_usuario=user.id if user is not None else req.id_usuario or 1,
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
    request: Request, response: Response,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), credentials=Depends(security_bearer),
):
    """Read recent accepted local milestones; never upload or change outcomes."""
    try:
        visible = _feedback_visible_prediction_ids(db, request, response, credentials)
        return FeedbackSyncQueue().recent(db, limit=limit, prediction_ids=visible)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Synchronization states unavailable")


@app.get("/api/feedback/pending")
def get_pending_feedback(
    request: Request, response: Response,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), credentials=Depends(security_bearer),
):
    """
    Retorna la lista de retroalimentaciones pendientes de curación semi-manual (procesado == False).
    """
    visible = _feedback_visible_prediction_ids(db, request, response, credentials)
    return feedback_service.get_pending_feedback(db=db, limit=limit, prediction_ids=visible)


@app.post("/api/feedback/{id_retroalimentacion}/approve", response_model=ApproveFeedbackResponse)
def approve_feedback(
    id_retroalimentacion: int, request: Request, response: Response,
    curation_source_id: Optional[str] = Query(
        None, min_length=1, max_length=200,
        description="Human-reviewed original canonical xc_id; catalog reference validation is not acoustic verification.",
    ),
    dataset_name: Optional[str] = Query(
        None, min_length=1, max_length=100,
        description="Compatibilidad legacy: debe coincidir con el destino persistido; no permite cambiarlo.",
    ),
    db: Session = Depends(get_db), credentials=Depends(security_bearer),
):
    """
    Aprueba e incorpora el audio en el destino congelado durante la inferencia,
    actualiza metadata.csv y marca el registro como procesado.
    """
    user = _feedback_imported_user(db, _feedback_prediction_id(db, id_retroalimentacion),
                                   request, response, credentials)
    kwargs = {"db": db, "id_retroalimentacion": id_retroalimentacion, "dataset_name": dataset_name}
    if user is not None:
        kwargs["owner_id"] = user.id
    if curation_source_id is not None:
        kwargs["curation_source_id"] = curation_source_id
    return feedback_service.approve_feedback(**kwargs)


@app.post("/api/feedback/{id_retroalimentacion}/reject")
def reject_feedback(
    id_retroalimentacion: int, request: Request, response: Response,
    db: Session = Depends(get_db), credentials=Depends(security_bearer),
):
    """
    Descarta la retroalimentación sin alterar los datasets de entrenamiento,
    marcando el registro como procesado.
    """
    _feedback_imported_user(db, _feedback_prediction_id(db, id_retroalimentacion),
                            request, response, credentials)
    return feedback_service.reject_feedback(db=db, id_retroalimentacion=id_retroalimentacion)


@app.get("/api/feedback/stats")
def get_feedback_stats(request: Request, response: Response, db: Session = Depends(get_db),
                       credentials=Depends(security_bearer)):
    """
    Retorna la telemetría consolidada del bucle de retroalimentación activa (RF_06)
    incluyendo conteo de audios pendientes de curación.
    """
    visible = _feedback_visible_prediction_ids(db, request, response, credentials)
    return feedback_service.get_feedback_stats(db=db, prediction_ids=visible)
