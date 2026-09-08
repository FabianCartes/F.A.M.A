"""
Punto de entrada directo del backend F.A.M.A.
Re-exporta la instancia de FastAPI y los servicios del Super-Ensamble
desde app.main para compatibilidad total con uvicorn main:app.
"""
from app.main import (
    app,
    ensemble_service,
    SPECIES_CLASSES,
    ENSEMBLE_WEIGHTS,
)

__all__ = ["app", "ensemble_service", "SPECIES_CLASSES", "ENSEMBLE_WEIGHTS"]
