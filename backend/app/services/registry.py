"""
Registro centralizado y catálogo de modelos de predicción bioacústica.
Permite registrar y resolver dinámicamente instancias de AudioPredictor en tiempo de ejecución.
"""
from typing import Dict, List, Optional
from app.schemas.model_info import ModelMetadata
from app.services.predictors.base import AudioPredictor


class ModelNotFoundError(Exception):
    """Excepción lanzada cuando se solicita un modelo no registrado."""
    pass


class ModelRegistry:
    """
    Catálogo y gestor de ciclo de vida de modelos en memoria.
    """

    def __init__(self):
        self._predictors: Dict[str, AudioPredictor] = {}
        self._default_model_id: Optional[str] = None

    def register(self, predictor: AudioPredictor, is_default: bool = False) -> None:
        """
        Registra una estrategia predictora en el catálogo.

        Parámetros:
            predictor: Instancia de AudioPredictor.
            is_default: Si es True, designa a este modelo como el fallback por defecto.
        """
        model_id = predictor.model_id
        self._predictors[model_id] = predictor
        if is_default or self._default_model_id is None:
            self._default_model_id = model_id

    def get(self, model_id: Optional[str] = None) -> AudioPredictor:
        """
        Recupera una estrategia predictora según su ID.
        Si model_id es None o 'default', retorna el modelo por defecto.
        """
        if not self._predictors:
            raise ModelNotFoundError("El catálogo de modelos está vacío.")

        target_id = model_id if (model_id and model_id != "default") else self._default_model_id

        if not target_id or target_id not in self._predictors:
            disponibles = list(self._predictors.keys())
            raise ModelNotFoundError(
                f"Modelo '{model_id}' no encontrado en el catálogo. Modelos disponibles: {disponibles}"
            )

        return self._predictors[target_id]

    def list_models(self) -> List[ModelMetadata]:
        """Retorna la lista de metadatos de todos los modelos registrados."""
        models = []
        for predictor in self._predictors.values():
            meta = predictor.metadata.model_copy()
            meta.is_default = (predictor.model_id == self._default_model_id)
            models.append(meta)
        return models

    def get_default_model_id(self) -> Optional[str]:
        """Retorna el identificador del modelo por defecto."""
        return self._default_model_id

    def has_model(self, model_id: str) -> bool:
        """Verifica si un modelo específico está registrado."""
        return model_id in self._predictors


def build_default_registry() -> ModelRegistry:
    """Construye y puebla el catálogo con los modelos estándar de F.A.M.A."""
    reg = ModelRegistry()
    from app.services.predictors.cnn_predictor import AudioCNNPredictor
    from app.services.predictors.ensemble_predictor import ChileanBirdsEnsemblePredictor

    cnn = AudioCNNPredictor()
    ensemble = ChileanBirdsEnsemblePredictor(lazy_load=True)

    reg.register(cnn, is_default=True)
    reg.register(ensemble, is_default=False)
    return reg


_global_model_registry: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """Proveedor de dependencias para FastAPI (Dependency Injection)."""
    global _global_model_registry
    if _global_model_registry is None:
        _global_model_registry = build_default_registry()
    return _global_model_registry


def set_global_model_registry(registry: Optional[ModelRegistry]) -> None:
    """Permite sobrescribir el registro global para propósitos de prueba."""
    global _global_model_registry
    _global_model_registry = registry

