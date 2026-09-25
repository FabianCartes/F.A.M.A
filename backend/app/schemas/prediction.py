"""
Esquemas Pydantic para resultados de predicción e inferencia bioacústica.
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class PredictionResult(BaseModel):
    """Objeto de valor con el resultado de una inferencia retornada por un AudioPredictor."""
    clase: str = Field(..., description="Etiqueta predicha (nombre de especie, silencio o ruido)")
    confianza: float = Field(..., description="Probabilidad o nivel de confianza [0.0, 1.0]")
    detalles: Optional[Dict[str, Any]] = Field(None, description="Metadatos acústicos diagnósticos (RMS, Flatness, etc.)")


class PredictionResponse(BaseModel):
    """Contrato de respuesta HTTP para el endpoint POST /api/predict."""
    filename: str = Field(..., description="Nombre del archivo procesado")
    gcp_upload: bool = Field(..., description="Estado de persistencia en Google Cloud Storage")
    db_id: int = Field(..., description="ID del registro histórico en PostgreSQL")
    clase: str = Field(..., description="Clase predicha")
    confianza: float = Field(..., description="Nivel de confianza calibrado")
    modelo_id: str = Field(..., description="Identificador del modelo que generó la inferencia")
    modelo: Optional[str] = Field(None, description="Nombre descriptivo del modelo activo")
    is_fallback: Optional[bool] = Field(None, description="Indica si opera en modo fallback")
    modelos_activos: Optional[list] = Field(None, description="Lista de modelos activos con ponderaciones")
