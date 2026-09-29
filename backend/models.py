"""
Modelos de Base de Datos para F.A.M.A.
Re-exporta los modelos de app.models para compatibilidad con la raíz de backend.
"""
from app.models.prediction import Prediccion
from app.models.dataset import ConjuntoDatos, Audio
from app.models.training import Modelo, MetricaEntrenamiento
from app.models.feedback import Retroalimentacion
from app.models.user import Usuario

__all__ = [
    "Prediccion",
    "ConjuntoDatos",
    "Audio",
    "Modelo",
    "MetricaEntrenamiento",
    "Retroalimentacion",
    "Usuario",
]

