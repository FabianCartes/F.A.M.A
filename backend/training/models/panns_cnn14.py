"""
backend/training/models/panns_cnn14.py
Implementación de la arquitectura PANNs CNN14 preentrenada en AudioSet con soporte para pooling GeM,
congelamiento parcial de etapas y adaptación de canales para tensores HPSS de 3 canales.
"""
from pathlib import Path
from typing import Tuple, Union, Optional
import torch
import torch.nn as nn

from poc.preprocess import GeM


class ConvBlock(nn.Module):
    """Bloque convolucional base de PANNs (2 capas Conv + BatchNorm + ReLU + AvgPool2d)."""

    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.pool = nn.AvgPool2d(kernel_size=2, stride=2)
        self.act = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.act(self.bn1(self.conv1(x)))
        x = self.act(self.bn2(self.conv2(x)))
        x = self.pool(x)
        return x


class PannsCNN14(nn.Module):
    """
    CNN14 (Large-Scale Pretrained Audio Neural Network).
    6 etapas convolucionales profundas que proyectan hacia un vector de 2048 dimensiones.
    """

    def __init__(
        self,
        in_chans: int = 3,
        num_classes: int = 13,
        num_attributes: Optional[int] = None,
        drop_rate: float = 0.3,
        pool_type: str = "gem",
        freeze_stages: int = 0,
    ):
        super().__init__()
        self.in_chans = in_chans
        self.num_classes = num_classes
        self.num_attributes = num_attributes
        self.pool_type = pool_type.lower() if pool_type else "avg"

        self.conv_block1 = ConvBlock(in_chans, 64)
        self.conv_block2 = ConvBlock(64, 128)
        self.conv_block3 = ConvBlock(128, 256)
        self.conv_block4 = ConvBlock(256, 512)
        self.conv_block5 = ConvBlock(512, 1024)
        self.conv_block6 = ConvBlock(1024, 2048)

        if self.pool_type == "gem":
            self.global_pool = GeM(p=3.0, flatten=True)
        else:
            self.global_pool = nn.Sequential(
                nn.AdaptiveAvgPool2d((1, 1)),
                nn.Flatten(1),
            )

        self.dropout = nn.Dropout(p=drop_rate)
        self.fc1 = nn.Linear(2048, 2048)
        self.act = nn.ReLU(inplace=True)
        self.fc_class = nn.Linear(2048, num_classes)
        if self.num_attributes is not None:
            self.fc_attributes = nn.Linear(2048, num_attributes)

        if freeze_stages > 0:
            self.freeze_early_stages(freeze_stages)

    def freeze_early_stages(self, num_stages: int = 4) -> None:
        """Congela los bloques convolucionales iniciales para evitar sobreajuste y conservar features de AudioSet."""
        for i in range(1, min(num_stages + 1, 7)):
            block = getattr(self, f"conv_block{i}", None)
            if block is not None:
                for param in block.parameters():
                    param.requires_grad = False

    def forward(self, x: torch.Tensor) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        """
        Entrada:
            x: [B, in_chans, n_mels, time_frames]
        Salida:
            Logits de clasificación [B, num_classes] o Tuple[class_logits, attr_logits] si num_attributes está definido.
        """
        x = self.conv_block1(x)
        x = self.conv_block2(x)
        x = self.conv_block3(x)
        x = self.conv_block4(x)
        x = self.conv_block5(x)
        x = self.conv_block6(x)

        x = self.global_pool(x)  # [B, 2048]
        x = self.dropout(x)
        x = self.act(self.fc1(x))
        x = self.dropout(x)
        class_logits = self.fc_class(x)

        if self.num_attributes is not None:
            attr_logits = self.fc_attributes(x)
            return class_logits, attr_logits

        return class_logits


def load_panns_cnn14_pretrained(
    model: PannsCNN14,
    checkpoint_path: Union[str, Path],
    device: torch.device = torch.device("cpu"),
) -> Tuple[int, int]:
    """
    Carga los pesos de AudioSet del checkpoint oficial de PANNs en la arquitectura local.
    Adapta automáticamente el tensor de conv_block1 si el modelo usa 3 canales (HPSS).
    """
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    state_dict = ckpt["model"] if isinstance(ckpt, dict) and "model" in ckpt else ckpt

    model_dict = model.state_dict()
    clean_dict = {}
    loaded_count = 0

    for key, value in state_dict.items():
        if key in model_dict:
            # Si el modelo espera 3 canales y los pesos originales eran de 1 canal
            if key == "conv_block1.conv1.weight" and model.in_chans == 3 and value.shape[1] == 1:
                value = value.repeat(1, 3, 1, 1) / 3.0

            if model_dict[key].shape == value.shape:
                clean_dict[key] = value
                loaded_count += 1

    model.load_state_dict(clean_dict, strict=False)
    return loaded_count, len(state_dict)
