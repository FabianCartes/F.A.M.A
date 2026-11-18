import os

# Read process configuration before importing services with runtime side effects.
# Deliberately do not load dotenv here or normalize an invalid operator value.
_APP_STARTUP_POLICY = os.environ.get("FAMA_APP_STARTUP_POLICY", "normal")
if _APP_STARTUP_POLICY not in {"normal", "isolated"}:
    raise ValueError("FAMA_APP_STARTUP_POLICY must be normal or isolated")

import sys
import logging
import asyncio
from functools import partial
from time import perf_counter
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Form, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session, sessionmaker
import numpy as np

# ============================================================================
# RUTEO DE MÓDULOS DEL BACKEND Y ML CORE
# ============================================================================
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.middleware.inference_limits import InferenceLimits
from app.middleware.upload_limits import UploadBodyLimit
from app.services.inference_execution import InferenceExecution
from app.services.inference_input import InvalidInferenceAudio, validate_audio
from app.services.storage import upload_audio_to_gcp
from app.services.ingestion import (
    ingestion_service, IngestionValidationError, IngestionConfigurationError,
    IngestionPayloadTooLarge, IngestionAudioError, IngestionDatasetUnavailable,
)
from app.services.dataset_comparison import verify_dataset_content
from app.services.dataset_download import DatasetDownloads, DownloadInProgress, summarize_results
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
from app.services.triad_compositions import TRIAD_PREFIX, composition_query, parse_triad_key, triad_model_key
from app.routes.import_capability import zip_router

from app.services.registry import get_model_registry, initialize_model_registry, ModelRegistry, ModelNotFoundError
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
# CICLO DE VIDA (LIFESPAN / STARTUP): CARGA ÚNICA EN MEMORIA
# ============================================================================
def _prewarm_model_metadata(*, isolated: bool = False):
    from app.database import SessionLocal
    try:
        registry = (initialize_model_registry(metadata_only=True)
                    if isolated else get_model_registry())
        with SessionLocal() as db_session:
            failures = registry.prewarm_from_db(
                db_session, checkpoints_root=training_service.checkpoints_dir)
        if failures:
            print(f"[Startup Warning] Metadata prewarm skipped {failures} unavailable models.")
    except Exception:
        # Never expose private identities, paths or database diagnostics here.
        print("[Startup Warning] Metadata prewarm unavailable.")


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Precalienta los metadatos del catálogo y arranca el worker de feedback.

    Isolated precalienta solo metadatos; omite seed y workers.
    """
    if _APP_STARTUP_POLICY == "isolated":
        _prewarm_model_metadata(isolated=True)
        yield
        return

    from app.database import SessionLocal
    _prewarm_model_metadata()
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

logger = logging.getLogger(__name__)
inference_execution = InferenceExecution()
MAX_INFERENCE_BODY_BYTES = 110 * 1024 * 1024
INFERENCE_WAIT_SECONDS = 270
app.add_middleware(InferenceLimits, execution=inference_execution,
                   body_limit=lambda: MAX_INFERENCE_BODY_BYTES,
                   wait_seconds=lambda: INFERENCE_WAIT_SECONDS)

# Multipart boundaries, part headers and form fields on top of the audio batch.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


def upload_body_limit():
    """Raw upload body bound derived from the configured batch limit."""
    return ingestion_service.get_upload_limits()[1] + MULTIPART_OVERHEAD_BYTES


app.add_middleware(UploadBodyLimit, body_limit=upload_body_limit)

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
app.include_router(zip_router())
from app.routes.prediction_history import router as prediction_history_router
app.include_router(prediction_history_router)
from app.routes.triad_compositions import router as triad_composition_router
app.include_router(triad_composition_router)



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
    request: Request,
    response: Response,
    only_available: bool = Query(False, description="Si es True, retorna solo modelos con pesos físicos verificados en disco"),
    registry: ModelRegistry = Depends(get_model_registry),
    db: Session = Depends(get_db),
    include_imported: bool = Query(False, description="Opción retirada; true se rechaza."),
    private_only: bool = Query(False, description="Opción retirada; true se rechaza."),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Retorna la lista de todos los modelos bioacústicos disponibles en el catálogo,
    sus especificaciones técnicas, clases soportadas, disponibilidad de pesos y el modelo por defecto.
    El catálogo filtra por el acceso vigente al dataset; las opciones privadas retiradas se rechazan.
    """
    if include_imported or private_only:
        raise HTTPException(422, "El catálogo privado importado fue retirado.")
    owner_scope = {}
    admitted_pair_ids = {}
    publication_errors = registry.publish_from_db(
        db, checkpoints_root=training_service.checkpoints_dir,
        admitted_pair_ids=admitted_pair_ids,
        access=access,
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
    default_id = "" if private_only else registry.get_default_model_id() or ""
    if not access.administrator:
        # Owner-scoped imported models were already admitted by the registry.
        models = [item for item in models if access.model_allowed(item.id, item.dataset_name)]
        visible_ids = {item.id for item in models}
        default_id = default_id if default_id in visible_ids else ""
        registered_ids = {f"fama_trained_model_{row.id_modelo}" for row in access.query(Modelo).all()}
        registered_ids |= {triad_model_key(row.id) for row in composition_query(access).all()}
        publication_errors = [item for item in publication_errors if item.get("model_id") in registered_ids]
    evaluations = read_model_evaluations(db, models, admitted_pair_ids)
    for model in models:
        model.evaluations = evaluations.by_model_id.get(model.id)
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
        description="ID o alias exacto de un modelo autorizado; omitirlo selecciona el default.",
    ),
    dataset_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    registry: ModelRegistry = Depends(get_model_registry),
    access: ResourceAccess = Depends(resource_access),
    request: Request = None,
    response: Response = None,
):
    """
    Recibe un archivo de audio por HTTP multipart/form-data.
    1. Valida que la extensión sea estrictamente .wav.
    2. Resuelve y valida el modelo solicitado en el ModelRegistry (falla rápido 404 si no existe).
    3. Conserva audio local privado cuando está configurado; de otro modo usa GCS.
    4. Ejecuta la inferencia bioacústica a través del AudioPredictor correspondiente.
    5. Inserta el registro histórico en la tabla 'prediccion' de PostgreSQL (incluyendo modelo_id).
    6. Retorna el estado real de persistencia local o cloud.
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
    # Imported models keep owner-scoped admission below, outside dataset grants.
    requested = model_id if model_id and model_id != "default" else registry.get_default_model_id()
    if requested and requested.startswith("fama_trained_model_") and not access.administrator:
        suffix = requested.removeprefix("fama_trained_model_")
        if (not suffix.isascii() or not suffix.isdecimal() or len(suffix) > 10
                or not 1 <= int(suffix) <= 2 ** 31 - 1
                or access.query(Modelo).filter_by(id_modelo=int(suffix)).first() is None):
            raise HTTPException(404, "Modelo no encontrado o no asignado.")
    triad_id = parse_triad_key(requested)
    if triad_id is not None and composition_query(access).filter_by(id=triad_id).first() is None:
        raise HTTPException(404, "Modelo no encontrado o no asignado.")
    try:
        try:
            predictor = registry.get(model_id)
        except ModelNotFoundError:
            if not model_id or model_id == "default":
                raise
            raise
    except ModelNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modelo no encontrado o no asignado.",
        )
    except ModelWeightsError as weights_err:
        if not access.administrator and not (requested and requested.startswith(("fama_trained_model_", TRIAD_PREFIX))):
            raise HTTPException(404, "Modelo no encontrado o no asignado.") from None
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Modelo no disponible para inferencia: {weights_err}",
        )
    local_store, local_owner, local_key = None, None, None
    if not access.model_allowed(predictor.model_id, predictor.dataset_name):
        raise HTTPException(404, "Modelo no encontrado o no asignado.")
    import os
    from app.services.local_prediction_audio import LocalPredictionAudio
    root = feedback_service.import_root or os.environ.get("FAMA_IMPORT_ROOT")
    if root:
        local_store, local_owner = LocalPredictionAudio(root), access.user.id
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
        # Refuse replaced weights before the audio is read, uploaded or persisted.
        await lease.run(predictor.verify_checkpoint, stage="checkpoint")
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
                    dataset_name=predictor.dataset_name,
                    nombre_original=nombre_original,
                    fecha_carga=fecha_carga,
                )
                db.add(registro_prediccion)
                access.record_prediction_origin(registro_prediccion)
                db.commit()
                db.refresh(registro_prediccion)
                db_id = registro_prediccion.id_prediccion

        except Exception:
            logger.exception("Prediction persistence failed")
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
                        else "Fallo al registrar la predicción en PostgreSQL."),
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
    except Exception:
        request_outcome = "error"
        logger.exception("Audio prediction failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error durante el procesamiento del audio.",
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


dataset_downloads = DatasetDownloads()


class SyncRequest(BaseModel):
    datasets: List[str]
    preprocess: bool = False

    @field_validator("datasets")
    @classmethod
    def safe_destinations(cls, values):
        return [validate_ingestion_segment(value) for value in values]


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
    descriptions = dict(access.query(ConjuntoDatos).with_entities(ConjuntoDatos.nombre, ConjuntoDatos.descripcion))
    for item in datasets:
        item["description"] = descriptions.get(item["name"])
    try:
        file_limit, batch_limit = ingestion_service.get_upload_limits()
        limits = {"max_file_bytes": file_limit, "max_batch_bytes": batch_limit}
    except IngestionConfigurationError:
        limits = None
    return {"datasets": datasets, "can_create_dataset": access.administrator, "upload_limits": limits}


@app.get("/api/ingestion/datasets/counts")
def count_ingestion_datasets(access: ResourceAccess = Depends(resource_access)):
    """Registered audio totals per visible dataset, without listing the bucket.

    Meant for frequent polling while an import publishes; ``cantidad_audios``
    counts the audio rows confirmed after each uploaded batch.
    """
    rows = access.query(ConjuntoDatos).order_by(ConjuntoDatos.nombre).all()
    return {"datasets": [{"name": row.nombre, "file_count": row.cantidad_audios or 0} for row in rows]}


@app.get("/api/ingestion/datasets/{dataset_name}/files")
def list_ingestion_dataset_files(
    dataset_name: str, db: Session = Depends(get_db),
    browse: bool = Query(False, description="Opt-in bounded, read-only audio browser."),
    class_name: Optional[str] = Query(None, description="Exact real class; intersects feedback."),
    feedback: Optional[bool] = Query(None, description="Filter confirmed incorporated feedback origin."),
    limit: int = Query(50, ge=1, le=200, description="Browse page size; inventory enumeration remains eager."),
    cursor: Optional[str] = Query(None, description="Opaque cursor bound to dataset, filters and inventory snapshot."),
    access: ResourceAccess = Depends(resource_access),
):
    """Legacy full list by default; browse adds full facets and snapshot-bound pages.

    Shared rows are read-only. Cursor mismatch is 422; inventory drift is 409.
    No cloud streaming or individual download is provided by browsing.
    """
    access.require_dataset(dataset_name)
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


@app.post("/api/ingestion/datasets/{dataset_name}/compare")
def compare_ingestion_dataset(dataset_name: str,
                              access: ResourceAccess = Depends(resource_access)):
    """Verify local audio against the GCS checksums (MD5/CRC32C) on explicit request.

    Same authorization and name validation as the download endpoints. It reads
    and hashes local files but never writes or transfers anything.
    """
    access.require_dataset(dataset_name)
    try:
        ingestion_service.validate_dataset_names([dataset_name])
    except IngestionValidationError:
        raise HTTPException(status_code=422, detail="Nombre de dataset inválido.") from None
    try:
        return verify_dataset_content(ingestion_service, dataset_name)
    except IngestionDatasetUnavailable:
        raise HTTPException(status_code=409, detail="El dataset no contiene audios en el bucket actual.") from None
    except Exception:
        raise HTTPException(status_code=502, detail="No se pudo consultar el bucket para comparar.") from None


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

    return summarize_results(results)


def _visible_download(access: ResourceAccess, snapshot):
    """A download is visible to exactly the accounts that may sync all its datasets."""
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Recurso no encontrado o no asignado.")
    for name in snapshot["datasets"]:
        access.require_dataset(name)
    return snapshot


@app.post("/api/ingestion/sync/start", status_code=202)
def start_ingestion_download(req: SyncRequest, db: Session = Depends(get_db),
                             access: ResourceAccess = Depends(resource_access)):
    """Start the GCS -> local download in the background; poll the returned operation.

    Same authorization and validation as the synchronous ``POST /api/ingestion/sync``,
    which stays available for callers that can hold one long request.
    """
    if not req.datasets:
        raise HTTPException(status_code=422, detail="Selecciona al menos un dataset.")
    for name in req.datasets:
        access.require_dataset(name)
    try:
        ingestion_service.validate_dataset_names(req.datasets)
    except IngestionValidationError:
        raise HTTPException(status_code=422, detail="Nombres de dataset inválidos.") from None
    try:
        return dataset_downloads.start(
            ingestion_service, req.datasets, preprocess=req.preprocess,
            session_factory=sessionmaker(bind=db.get_bind()))
    except DownloadInProgress as running:
        raise HTTPException(status_code=409, detail={
            "message": "Ya hay una descarga en curso para este dataset.",
            "operation_id": running.operation_id}) from None


@app.get("/api/ingestion/sync/active")
def list_active_ingestion_downloads(access: ResourceAccess = Depends(resource_access)):
    """Running downloads the account may see, so a reloaded page can re-attach."""
    visible = []
    for snapshot in dataset_downloads.active():
        if access.administrator or set(snapshot["datasets"]) <= access.names:
            visible.append(snapshot)
    return {"operations": visible}


@app.get("/api/ingestion/sync/operations/{operation_id}")
def get_ingestion_download(operation_id: str, access: ResourceAccess = Depends(resource_access)):
    """Server-side state of one download, independent of the request that started it."""
    return _visible_download(access, dataset_downloads.snapshot(operation_id))


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
def get_training_datasets(request: Request, response: Response, db: Session = Depends(get_db),
                          include_unavailable: bool = False,
                          access: ResourceAccess = Depends(resource_access)):
    """
    Retorna la lista de datasets disponibles para entrenar (CU_INV_02).
    Los ZIP publicados se seleccionan por dataset_name y partition_version.
    No ofrece snapshots ni preparaciones importadas; include_imported explícito se rechaza.
    """
    if "include_imported" in request.query_params:
        raise HTTPException(422, "La opción include_imported fue retirada del catálogo de entrenamiento.")
    # Opt-in projection only; preserve the historical call and response by default.
    datasets = (training_service.get_available_datasets(db=db, access=access, include_unavailable=True)
                if include_unavailable else training_service.get_available_datasets(db=db, access=access))
    return {"datasets": datasets}


@app.post("/api/training/start")
def start_training_pipeline(req: StartTrainingRequest, request: Request, response: Response,
                            db: Session = Depends(get_db), access: ResourceAccess = Depends(resource_access)):
    """
    Inicia un entrenamiento en segundo plano utilizando PyTorch (CU_INV_03).
    Soporta modelo individual, Tríada Completa o Ensamble Dinámico por dataset.
    La selección importada histórica se rechaza antes de admitir el trabajo.
    started solo acredita admisión; checkpoint_persisted queda pendiente de evaluación.
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
            "seed": req.seed,
            "early_stopping": req.early_stopping,
        }
        if getattr(req, "_explicit_models", False) and req.models is not None:
            kwargs["models"] = [m.model_dump() for m in req.models]
        if req.partition_version is not None:
            kwargs["partition_version"] = req.partition_version
        if req.prepared_version is not None:
            kwargs["prepared_version"] = req.prepared_version
        if req.allow_historical_preparation:
            kwargs["allow_historical_preparation"] = True

        if req.audio_config is not None:
            kwargs["audio_config"] = req.audio_config.model_dump()
        if req.regularization_config is not None:
            kwargs["regularization_config"] = req.regularization_config.model_dump()

        result = training_service.start_training(**kwargs)
        return result
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))



@app.get("/api/training/progress")
def get_training_progress(request: Request, response: Response, db: Session = Depends(get_db),
                          access: ResourceAccess = Depends(resource_access)):
    """
    Retorna el progreso en tiempo real, curvas de Loss/Accuracy y logs (IS_02).
    """
    try:
        return training_service.get_progress(user_id=access.user.id,
                                             administrator=access.administrator, allowed_datasets=access.names)
    except PermissionError:
        raise HTTPException(403, "Trabajo no accesible para este usuario.") from None


@app.post("/api/training/stop")
def stop_training_pipeline(request: Request, response: Response, db: Session = Depends(get_db),
                           access: ResourceAccess = Depends(resource_access)):
    """
    Solicita la detención segura del entrenamiento en ejecución (CU_INV_03 Paso 2.a).
    """
    try:
        return training_service.stop_training(user_id=access.user.id,
                                              administrator=access.administrator, allowed_datasets=access.names)
    except PermissionError:
        raise HTTPException(403, "Trabajo no accesible para este usuario.") from None


@app.get("/api/training/history")
def get_training_history(request: Request, response: Response, db: Session = Depends(get_db), include_imported: bool = False,
                         access: ResourceAccess = Depends(resource_access)):
    """
    Retorna el historial de modelos entrenados desde PostgreSQL (CU_INV_04).
    La opción include_imported=true fue retirada.
    """
    if include_imported:
        raise HTTPException(422, "El historial importado fue retirado.")
    history = training_service.get_history(db=db, access=access)
    from app.models.training import Modelo
    from app.models.dataset import ConjuntoDatos
    from app.services.model_names import dataset_label
    from app.services.triad_compositions import (
        component_architectures, component_ids, component_weights, composition_query, latest_compositions,
        triad_display_name, triad_ordinals, validate_weights, TriadCompositionError,
    )
    authorized = {composition.id for composition in composition_query(access).all()}
    visible = {item["id"] for item in history}
    models_by_id = {model.id_modelo: model for model in access.query(Modelo).all()}
    datasets = {model_id: model.id_conjunto_datos for model_id, model in models_by_id.items()}
    ordinals = triad_ordinals(db)
    compositions = []
    for composition in latest_compositions(db):
        ids = component_ids(composition)
        if (composition.id not in authorized or len(set(ids)) != 3
                or any(model_id not in visible or datasets.get(model_id) != composition.dataset_id for model_id in ids)):
            continue
        try:
            weights = validate_weights(component_weights(composition))
        except TriadCompositionError:
            continue
        architectures = component_architectures(composition, models_by_id)
        dataset = db.get(ConjuntoDatos, composition.dataset_id)
        compositions.append({"id": composition.id, "version": composition.version,
                             "job_id": composition.job_id,
                             "name": triad_display_name(dataset_label(getattr(dataset, "nombre", None)),
                                                        ordinals[composition.id], architectures),
                             "architectures": architectures,
                             "components": [{"id_modelo": model_id, "weight": weight}
                                            for model_id, weight in zip(ids, weights)]})
    from app.services.triad_evaluations import TriadEvaluationService, joint_evaluation_summary
    attempts = TriadEvaluationService(db).latest_by_split([item["id"] for item in compositions])
    for item in compositions:
        # Stored attempts of this exact composition only; reading never runs inference.
        item["evaluation"] = joint_evaluation_summary(attempts.get(item["id"], {}))
    return {"history": history, "compositions": compositions}


@app.post("/api/training/models/{model_id}/activate")
def activate_model(model_id: int, request: Request, response: Response, db: Session = Depends(get_db),
                   access: ResourceAccess = Depends(resource_access)):
    """
    Activa un modelo para inferencias bioacústicas en tiempo real (CU_INV_05).
    """
    access.require_administrator()
    return training_service.set_active_model(model_id=model_id, db=db)


# ============================================================================
# ENDPOINTS DE RETROALIMENTACIÓN ACTIVA Y CURACIÓN SEMI-MANUAL (RF_06)
# ============================================================================
@app.post("/api/feedback", status_code=status.HTTP_201_CREATED)
def record_feedback(req: FeedbackCreateRequest, request: Request, response: Response,
                    db: Session = Depends(get_db),
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
    request: Request, response: Response,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """Read recent accepted local milestones; never upload or change outcomes."""
    try:
        return FeedbackSyncQueue().recent(db, limit=limit, offset=offset, access=access)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Synchronization states unavailable")


@app.get("/api/feedback/pending")
def get_pending_feedback(
    request: Request, response: Response,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Retorna la lista de retroalimentaciones pendientes de curación semi-manual (procesado == False).
    """
    return feedback_service.get_pending_feedback(db=db, limit=limit, offset=offset, access=access)


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
    db: Session = Depends(get_db),
    access: ResourceAccess = Depends(resource_access),
):
    """
    Aprueba e incorpora el audio en el destino congelado durante la inferencia,
    actualiza metadata.csv y marca el registro como procesado.
    """
    access.require_feedback(id_retroalimentacion)
    kwargs = {"db": db, "id_retroalimentacion": id_retroalimentacion, "dataset_name": dataset_name, "actor_id": access.user.id}
    if curation_source_id is not None:
        kwargs["curation_source_id"] = curation_source_id
    return feedback_service.approve_feedback(**kwargs)



@app.post("/api/feedback/{id_retroalimentacion}/reject")
def reject_feedback(
    id_retroalimentacion: int, request: Request, response: Response,
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
def get_feedback_stats(request: Request, response: Response, db: Session = Depends(get_db),
                       access: ResourceAccess = Depends(resource_access)):
    """
    Retorna la telemetría consolidada del bucle de retroalimentación activa (RF_06)
    incluyendo conteo de audios pendientes de curación.
    """
    return feedback_service.get_feedback_stats(db=db, access=access)
