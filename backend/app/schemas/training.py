"""
Esquemas DTOs para el subsistema de entrenamiento y ensamble dinámico de modelos.
"""
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

VALID_ARCHITECTURES = {
    "EfficientNet-B0",
    "ConvNeXt-Nano",
    "ResNet-34d",
    "PANNs-CNN14",
    "AudioCNN",
}


class ModelEnsembleItem(BaseModel):
    """
    Especificación de un modelo miembro del ensamble con su respectiva ponderación.
    """
    architecture: str
    weight: float = Field(ge=0.0, le=1.0)

    @field_validator("architecture")
    @classmethod
    def validate_architecture(cls, v: str) -> str:
        if v not in VALID_ARCHITECTURES:
            raise ValueError(
                f"Arquitectura '{v}' no válida. Opciones permitidas: {sorted(list(VALID_ARCHITECTURES))}"
            )
        return v


class StartTrainingRequest(BaseModel):
    """
    Contrato de solicitud para iniciar el pipeline de entrenamiento.
    Permite composición dinámica de 1 a 3 modelos o retrocompatibilidad con arquitectura única/tríada fija.
    """
    dataset_name: str = "AvesChilenas"
    architecture: Optional[str] = "EfficientNet-B0"
    epochs: int = 10
    learning_rate: float = 0.001
    batch_size: int = 16
    framework: str = "pytorch"
    is_tri_model: bool = False
    models: Optional[List[ModelEnsembleItem]] = None
    _explicit_models: bool = False

    def __init__(self, **data):
        has_models = "models" in data and data["models"] is not None
        super().__init__(**data)
        object.__setattr__(self, "_explicit_models", has_models)

    @model_validator(mode="after")

    def validate_and_normalize_models(self) -> "StartTrainingRequest":
        if self.models is not None:
            if len(self.models) == 0:
                raise ValueError("La lista de modelos no puede estar vacía.")
            if len(self.models) > 3:
                raise ValueError("No se permite un ensamble de más de 3 modelos.")

            total_weight = sum(item.weight for item in self.models)
            if total_weight <= 0.0:
                raise ValueError("La suma de ponderaciones debe ser mayor a 0.")

            # Auto-normalización determinista de pesos
            normalized_models = []
            for item in self.models:
                normalized_models.append(
                    ModelEnsembleItem(
                        architecture=item.architecture,
                        weight=item.weight / total_weight,
                    )
                )
            self.models = normalized_models
        else:
            # Retrocompatibilidad con peticiones históricas
            if self.is_tri_model:
                is_engine = self.dataset_name in ["engine_diagnostics", "MotoresVehiculares"]
                archs = (
                    ["ResNet-34d", "EfficientNet-B0", "PANNs-CNN14"]
                    if is_engine
                    else ["EfficientNet-B0", "ConvNeXt-Nano", "ResNet-34d"]
                )
                self.models = [
                    ModelEnsembleItem(architecture=a, weight=1.0 / len(archs))
                    for a in archs
                ]
            else:
                arch = self.architecture or "EfficientNet-B0"
                self.models = [ModelEnsembleItem(architecture=arch, weight=1.0)]

        return self
