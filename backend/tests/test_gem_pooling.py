import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

from poc.preprocess import GeM


def test_gem_equivalence_gap_when_p_equals_one():
    """Con p=1.0, p_trainable=False e inputs positivos, la salida debe ser idéntica a GAP."""
    gem = GeM(p=1.0, p_trainable=False, flatten=True)
    # Entrada positiva en rango representativo
    x = torch.rand(4, 32, 7, 7) + 0.1

    gem_out = gem(x)
    gap_out = F.adaptive_avg_pool2d(x, (1, 1)).flatten(1)

    assert gem_out.shape == gap_out.shape
    assert torch.allclose(gem_out, gap_out, atol=1e-5)


def test_gem_peak_emphasis_over_gap():
    """Con un pulso alto de 10.0 y fondo plano de 0.1, GeM(p=3.0) produce activación > 4x que GAP."""
    gem = GeM(p=3.0, p_trainable=False, flatten=True)
    # Matriz 10x10 con fondo plano de 0.1 y un único pico de 10.0 (simulando un trino breve)
    x = torch.full((1, 1, 10, 10), 0.1, dtype=torch.float32)
    x[0, 0, 5, 5] = 10.0

    gem_out = gem(x)
    gap_out = F.adaptive_avg_pool2d(x, (1, 1)).flatten(1)

    assert gem_out.item() > 4.0 * gap_out.item(), (
        f"GeM ({gem_out.item():.4f}) debe enfatizar picos bioacústicos > 4x sobre GAP ({gap_out.item():.4f})"
    )


def test_gem_numerical_stability_silu_negatives():
    """Con valores negativos de SiLU, ni forward ni backward deben generar NaN o Inf."""
    gem = GeM(p=3.0, p_trainable=True, flatten=True)
    # Valores negativos característicos del mínimo de SiLU (~ -0.278) y extremos
    vals = [-1.0, -0.278, 0.0, 0.5, 2.0]
    x = torch.tensor(vals, dtype=torch.float32).repeat(2, 4, 1, 1).requires_grad_(True)

    out = gem(x)
    assert not torch.isnan(out).any(), "Forward produjo NaN con activaciones negativas"
    assert not torch.isinf(out).any(), "Forward produjo Inf con activaciones negativas"

    loss = out.sum()
    loss.backward()

    assert x.grad is not None
    assert not torch.isnan(x.grad).any(), "Backward produjo NaN en gradientes de entrada"
    assert not torch.isinf(x.grad).any(), "Backward produjo Inf en gradientes de entrada"
    assert gem.p.grad is not None
    assert not torch.isnan(gem.p.grad).any(), "Backward produjo NaN en gradiente de p"
    assert not torch.isinf(gem.p.grad).any(), "Backward produjo Inf en gradiente de p"


def test_gem_p_gradient_flow():
    """Verifica que el parámetro p acumule gradientes finitos y válidos tras backward."""
    gem = GeM(p=3.0, p_trainable=True, flatten=True)
    x = torch.rand(2, 16, 8, 8, requires_grad=True) + 0.1

    assert gem.p.requires_grad is True
    out = gem(x)
    target = torch.randn_like(out)
    loss = F.mse_loss(out, target)
    loss.backward()

    assert gem.p.grad is not None
    assert torch.isfinite(gem.p.grad).all()
    assert gem.p.grad.item() != 0.0
