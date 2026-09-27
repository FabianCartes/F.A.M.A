"""
Pydantic schemas for RF_06 Active Feedback Loop and Semi-Manual Curation.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator


class FeedbackCreateRequest(BaseModel):
    """Payload schema for submitting feedback on a prediction."""
    id_prediccion: int = Field(..., description="ID of the prediction in the database")
    fue_correcta: bool = Field(..., description="Whether the prediction was correct")
    etiqueta_corregida: Optional[str] = Field(None, description="Corrected taxonomic label if prediction was incorrect")
    id_usuario: Optional[int] = Field(1, description="ID of the user providing feedback")

    @model_validator(mode="after")
    def validate_correction_label(self):
        if not self.fue_correcta and not self.etiqueta_corregida:
            raise ValueError("Field 'etiqueta_corregida' is required when 'fue_correcta' is false.")
        return self


class FeedbackResponse(BaseModel):
    """Response schema for recorded feedback."""
    model_config = ConfigDict(from_attributes=True)

    id_retroalimentacion: int
    id_prediccion: int
    id_usuario: int
    fue_correcta: bool
    etiqueta_corregida: Optional[str] = None
    procesado: bool
    fecha_retroalimentacion: Optional[datetime] = None


class PendingFeedbackItem(BaseModel):
    """Response item for uncurated feedback in the curation queue."""
    id_retroalimentacion: int
    id_prediccion: int
    ruta_audio_prueba: str
    etiqueta_predicha: str
    confianza: float
    etiqueta_corregida: Optional[str] = None
    fecha_retroalimentacion: Optional[str] = None
    fue_correcta: bool
    procesado: bool
    id_usuario: int


class FeedbackStatsResponse(BaseModel):
    """Consolidated telemetry and metrics for active feedback."""
    total_validated: int
    correct_count: int
    corrected_count: int
    accuracy_rate: float
    pending_curation_count: int
    corrections_breakdown: List[Dict[str, Any]]


class ApproveFeedbackResponse(BaseModel):
    """Response schema when feedback audio is approved and ingested into the raw dataset."""
    status: str
    id_retroalimentacion: int
    destination_path: str
    clase: str
    filename: Optional[str] = None

