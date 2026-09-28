"""
Módulo de esquemas DTOs (Data Transfer Objects) con Pydantic.
"""
from app.schemas.model_info import ModelMetadata, ModelListResponse
from app.schemas.prediction import PredictionResult, PredictionResponse
from app.schemas.feedback import (
    FeedbackCreateRequest,
    FeedbackResponse,
    PendingFeedbackItem,
    FeedbackStatsResponse,
    ApproveFeedbackResponse,
)

__all__ = [
    "ModelMetadata",
    "ModelListResponse",
    "PredictionResult",
    "PredictionResponse",
    "FeedbackCreateRequest",
    "FeedbackResponse",
    "PendingFeedbackItem",
    "FeedbackStatsResponse",
    "ApproveFeedbackResponse",
    "ModelEnsembleItem",
    "StartTrainingRequest",
]

from app.schemas.training import ModelEnsembleItem, StartTrainingRequest


