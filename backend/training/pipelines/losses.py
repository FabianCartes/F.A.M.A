"""
backend/training/pipelines/losses.py
Funciones de pérdida avanzadas para clasificación bioacústica multi-task y multi-etiqueta.
Implementación de Asymmetric Loss (ASL) con margin shifting (Ben-Baruch et al., ICCV 2021).
"""
import torch
import torch.nn as nn


class AsymmetricLoss(nn.Module):
    """
    Asymmetric Loss (ASL) para clasificación multi-etiqueta desbalanceada.
    Desacopla los parámetros focales gamma_pos y gamma_neg y aplica margin shifting
    para anular a cero el gradiente generado por negativos fáciles dominantes.
    """

    def __init__(
        self,
        gamma_neg: float = 4.0,
        gamma_pos: float = 1.0,
        clip: float = 0.05,
        eps: float = 1e-8,
        reduction: str = "mean",
    ):
        super().__init__()
        self.gamma_neg = gamma_neg
        self.gamma_pos = gamma_pos
        self.clip = clip
        self.eps = eps
        self.reduction = reduction

    def forward(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        """
        Parámetros:
            x: Logits no normalizados [B, K]
            y: Etiquetas binarias [B, K]
        """
        # Calcular probabilidades
        xs_pos = torch.sigmoid(x)
        xs_neg = 1.0 - xs_pos

        # Margin shifting asimétrico en negativos
        if self.clip is not None and self.clip > 0:
            xs_neg = (xs_neg + self.clip).clamp(max=1.0)

        # Pérdidas logarítmicas básicas
        los_pos = y * torch.log(xs_pos.clamp(min=self.eps))
        los_neg = (1.0 - y) * torch.log(xs_neg.clamp(min=self.eps))
        loss = los_pos + los_neg

        # Modulación focal asimétrica
        if self.gamma_neg > 0 or self.gamma_pos > 0:
            pt0 = xs_pos * y
            pt1 = xs_neg * (1.0 - y)
            pt = pt0 + pt1
            one_sided_gamma = self.gamma_pos * y + self.gamma_neg * (1.0 - y)
            one_sided_w = torch.pow((1.0 - pt).clamp(min=0.0), one_sided_gamma)
            loss *= one_sided_w

        loss = -loss

        if self.reduction == "mean":
            return loss.mean()
        elif self.reduction == "sum":
            return loss.sum()
        return loss
