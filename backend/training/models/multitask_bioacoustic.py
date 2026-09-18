"""
backend/training/models/multitask_bioacoustic.py
Arquitectura multi-task bioacústica con entrada espectral multicanal (HPSS) y cabezas desacopladas.
"""
from typing import Tuple, Optional
import torch
import torch.nn as nn
import timm

from poc.preprocess import GeM


class MultiTaskBioacousticModel(nn.Module):
    """
    Modelo convolucional bioacústico con soporte nativo para 3 canales de entrada (HPSS)
    y arquitectura Multi-Task de doble cabeza:
      1. Cabeza de clasificación de clase (13 clases mecánicas)
      2. Cabeza auxiliar de atributos ortogonales (7 subsistemas mecánicos)
    """

    def __init__(
        self,
        model_name: str = "resnet34d",
        num_classes: int = 13,
        num_attributes: int = 7,
        pretrained: bool = True,
        in_chans: int = 3,
        drop_rate: float = 0.3,
        pool_type: str = "gem",
    ):
        super().__init__()
        self.model_name = model_name
        self.num_classes = num_classes
        self.num_attributes = num_attributes
        self.pool_type = pool_type.lower() if pool_type else "avg"

        # Extractor convolucional con num_classes=0 para obtener el vector de características [B, D]
        self.backbone = timm.create_model(
            model_name,
            pretrained=pretrained,
            in_chans=in_chans,
            drop_rate=drop_rate,
            num_classes=0,
        )

        # Configurar GeM pooling si está solicitado
        if self.pool_type == "gem":
            if hasattr(self.backbone, "global_pool") and getattr(self.backbone, "global_pool") is not None:
                self.backbone.global_pool = GeM(p=3.0, flatten=True)
            elif hasattr(self.backbone, "head") and hasattr(self.backbone.head, "global_pool"):
                self.backbone.head.global_pool = GeM(p=3.0, flatten=True)

        num_features = getattr(self.backbone, "num_features", None)
        if num_features is None:
            # Fallback en caso de que timm exponga head.fc o head.in_features
            if hasattr(self.backbone, "head") and hasattr(self.backbone.head, "fc"):
                num_features = self.backbone.head.fc.in_features
            else:
                num_features = 512

        self.dropout = nn.Dropout(p=drop_rate)
        self.head_class = nn.Linear(num_features, num_classes)
        self.head_attributes = nn.Linear(num_features, num_attributes)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Entrada:
            x: Tensor espectral [B, 3, n_mels, time_frames]
        Salida:
            Tuple[class_logits, attr_logits]
        """
        features = self.backbone(x)
        features = self.dropout(features)

        class_logits = self.head_class(features)
        attr_logits = self.head_attributes(features)

        return class_logits, attr_logits

    def predict_class_logits(self, x: torch.Tensor) -> torch.Tensor:
        """Método de conveniencia para inferencia estándar donde solo se requieren los logits de clase."""
        class_logits, _ = self.forward(x)
        return class_logits
