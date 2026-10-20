"""
Esquemas Pydantic para el módulo de información y catálogo de modelos.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_serializer

from app.schemas.evaluation import EvaluationProvenance


class EvaluationAttemptSummary(BaseModel):
    """Safe read-only view of the newest attempt for one split."""
    id_evaluation: int
    status: Literal["pending", "running", "completed", "failed"]
    provenance: EvaluationProvenance
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class CompletedEvaluationSummary(BaseModel):
    """Validated final report from the newest completed attempt for one split."""
    id_evaluation: int
    provenance: EvaluationProvenance
    report: Dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class EvaluationSplitSummary(BaseModel):
    latest_attempt: Optional[EvaluationAttemptSummary] = None
    latest_completed: Optional[CompletedEvaluationSummary] = None
    admitted_completed: Optional[CompletedEvaluationSummary] = None


class ModelEvaluations(BaseModel):
    val: Optional[EvaluationSplitSummary] = None
    test: Optional[EvaluationSplitSummary] = None


class ModelMetadata(BaseModel):
    """Metadatos descriptivos de un modelo de inferencia acústica."""
    id: str = Field(..., description="Identificador único del modelo (slug)")
    name: str = Field(..., description="Nombre amigable del modelo")
    architecture: Optional[str] = None
    dataset: Optional[str] = Field(None, description="Etiqueta visual; no acredita procedencia")
    version: Optional[int] = Field(None, description="Versión visual calculada, no identidad inmutable")
    description: str = Field(..., description="Descripción técnica de la arquitectura y entrenamiento")
    target_sr: int = Field(22050, description="Tasa de muestreo requerida en Hz")
    duration_seconds: float = Field(5.0, description="Duración de ventana de análisis en segundos")
    dataset_name: Optional[str] = Field(None, description="Destino canónico de almacenamiento verificado; null si desconocido")
    classes: List[str] = Field(default_factory=list, description="Lista de clases/especies reconocidas")
    is_default: bool = Field(False, description="Indica si es el modelo por defecto del sistema")
    has_weights: bool = Field(True, description="Disponibilidad de pesos reportada por el adaptador; no garantiza compatibilidad, integridad ni inferencia exitosa")
    checkpoint_sha256: Optional[str] = Field(
        None,
        description="SHA-256 de los bytes actuales del archivo checkpoint registrado; no acredita los parámetros cargados en memoria",
    )
    loaded_checkpoint_sha256: Optional[str] = Field(
        None,
        description="SHA-256 de la instantánea de checkpoint deserializada por esta instancia predictora",
    )
    metrics: Optional[Dict[str, Any]] = Field(None, description="Métricas históricas existentes del modelo")
    evaluations: Optional[ModelEvaluations] = Field(None, description="Últimos intentos e informes finales por split")


class ModelPublicationError(BaseModel):
    """Sanitized failure to publish one persisted model in the catalogue."""
    model_id: str
    code: str
    reason: Optional[Literal[
        "runtime_configuration_incompatible",
        "evaluation_pair_incomplete",
        "checkpoint_invalid",
        "pair_provenance_invalid",
        "model_state_incomplete",
    ]] = None

    @model_serializer(mode="wrap")
    def omit_unknown_reason(self, handler):
        serialized = handler(self)
        if self.reason is None:
            serialized.pop("reason", None)
        return serialized


class ModelListResponse(BaseModel):
    """Respuesta del catálogo de modelos disponibles."""
    models: List[ModelMetadata]
    total: int
    default_model_id: str
    publication_errors: List[ModelPublicationError] = Field(default_factory=list)
    evaluation_catalogue_status: Literal["available", "unavailable"] = "available"
    evaluation_catalogue_error: Optional[Literal["evaluation_store_unavailable", "evaluation_records_invalid"]] = None
