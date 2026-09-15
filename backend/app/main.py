import sys
import tempfile
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Query, status
from sqlalchemy.orm import Session

# Asegurar que la carpeta backend esté en sys.path para importar módulos de app y poc
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.storage import upload_audio_to_gcp
from app.database import Base, engine, get_db
from app.models.prediction import Prediccion
from app.services.registry import get_model_registry, ModelRegistry, ModelNotFoundError
from app.schemas.model_info import ModelListResponse
from app.schemas.prediction import PredictionResponse
from app.services.predictors.cnn_predictor import AudioCNNPredictor

# Alias de compatibilidad retroactiva para scripts o tests previos
AudioPredictorService = AudioCNNPredictor


# ============================================================================
# PERSISTENCIA: INICIALIZACIÓN DE TABLAS EN BASE DE DATOS
# ============================================================================
try:
    Base.metadata.create_all(bind=engine)
    print("[Database] Tablas sincronizadas exitosamente en PostgreSQL.")
except Exception as db_init_err:
    print(f"[Database] Advertencia al sincronizar tablas con PostgreSQL: {db_init_err}")


# ============================================================================
# ESQUELETO BASE FASTAPI
# ============================================================================
app = FastAPI(
    title="F.A.M.A. Backend API",
    description="Backend orquestador multi-modelo para monitoreo y clasificación bioacústica",
    version="1.1.0",
)


# ============================================================================
# ENDPOINTS DE SALUD Y COMPROBACIÓN
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
# CATÁLOGO DE MODELOS DE INFERENCIA
# ============================================================================
@app.get(
    "/api/models",
    response_model=ModelListResponse,
    summary="Catálogo de modelos bioacústicos registrados",
)
def list_models(
    registry: ModelRegistry = Depends(get_model_registry),
):
    """
    Retorna la lista de todos los modelos bioacústicos disponibles en el catálogo,
    sus especificaciones técnicas, clases soportadas y el modelo por defecto.
    """
    models = registry.list_models()
    default_id = registry.get_default_model_id() or "chilean-birds-cnn"
    return ModelListResponse(
        models=models,
        total=len(models),
        default_model_id=default_id,
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
    db: Session = Depends(get_db),
    registry: ModelRegistry = Depends(get_model_registry),
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
            detail=str(err),
        )

    try:
        audio_bytes = await file.read()

        # 3. Persistencia en la nube: Subida a Google Cloud Storage (RNF_03)
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

        # 4. Procesar audio localmente de forma temporal para la inferencia acústica
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            tmp_audio.write(audio_bytes)
            tmp_path = Path(tmp_audio.name)

        try:
            pred_result = predictor.predict(tmp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        # 5. Persistencia relacional en PostgreSQL (Tabla 'prediccion')
        try:
            registro_prediccion = Prediccion(
                ruta_audio_prueba=filename,
                etiqueta_predicha=pred_result.clase,
                confianza=pred_result.confianza,
                modelo_id=predictor.model_id,
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

        # 6. Retorno del formato JSON con gcp_upload, db_id y modelo_id
        return {
            "filename": filename,
            "gcp_upload": True,
            "db_id": db_id,
            "clase": pred_result.clase,
            "confianza": pred_result.confianza,
            "modelo_id": predictor.model_id,
        }

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante el procesamiento del audio: {str(err)}",
        )
