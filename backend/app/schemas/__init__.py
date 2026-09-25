"""
Módulo de esquemas DTOs (Data Transfer Objects) con Pydantic.
"""
from app.schemas.model_info import ModelMetadata, ModelListResponse
from app.schemas.prediction import PredictionResult, PredictionResponse

__all__ = [
    "ModelMetadata",
    "ModelListResponse",
    "PredictionResult",
    "PredictionResponse",
]
