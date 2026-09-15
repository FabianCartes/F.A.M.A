"""
Modelos de Base de Datos para F.A.M.A.
Re-exporta los modelos de app.models para compatibilidad con la raíz de backend.
"""
from app.models.prediction import Prediccion

__all__ = ["Prediccion"]
