"""
Esquemas Pydantic para el módulo de información y catálogo de modelos.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ModelMetadata(BaseModel):
    """Metadatos descriptivos de un modelo de inferencia acústica."""
    id: str = Field(..., description="Identificador único del modelo (slug)")
    name: str = Field(..., description="Nombre amigable del modelo")
    description: str = Field(..., description="Descripción técnica de la arquitectura y entrenamiento")
    target_sr: int = Field(22050, description="Tasa de muestreo requerida en Hz")
    duration_seconds: float = Field(5.0, description="Duración de ventana de análisis en segundos")
    classes: List[str] = Field(default_factory=list, description="Lista de clases/especies reconocidas")
    is_default: bool = Field(False, description="Indica si es el modelo por defecto del sistema")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Métricas de evaluación conocidas (F1, Accuracy)")


class ModelListResponse(BaseModel):
    """Respuesta del catálogo de modelos disponibles."""
    models: List[ModelMetadata]
    total: int
    default_model_id: str
