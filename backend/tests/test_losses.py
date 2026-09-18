"""
backend/tests/test_losses.py
Pruebas de TDD para la función de pérdida Asymmetric Loss (ASL) con margin shifting para atributos mecánicos multi-etiqueta.
"""
import pytest
import torch
from training.pipelines.losses import AsymmetricLoss


def test_asymmetric_loss_forward_and_backward():
    criterion = AsymmetricLoss(gamma_neg=4.0, gamma_pos=1.0, clip=0.05)

    bsz = 4
    num_attrs = 7
    logits = torch.randn(bsz, num_attrs, requires_grad=True)
    targets = torch.zeros(bsz, num_attrs)
    targets[0, 2] = 1.0
    targets[1, 0] = 1.0
    targets[2, 3] = 1.0

    loss = criterion(logits, targets)

    assert loss.dim() == 0  # Scalar loss
    assert not torch.isnan(loss)
    assert not torch.isinf(loss)
    assert loss.item() > 0

    loss.backward()
    assert logits.grad is not None
    assert not torch.isnan(logits.grad).any()


def test_asymmetric_loss_zeroes_easy_negatives_gradient():
    criterion = AsymmetricLoss(gamma_neg=4.0, gamma_pos=0.0, clip=0.05)

    # Logit muy negativo tal que sigma(x) < 0.05 (ej. x = -5 -> sigma(x) = 0.0067)
    logits = torch.tensor([[-5.0]], requires_grad=True)
    targets = torch.tensor([[0.0]])

    loss = criterion(logits, targets)
    loss.backward()

    # El gradiente de un negativo fácil debe ser exactamente cero por el margin clipping
    assert logits.grad.item() == pytest.approx(0.0, abs=1e-6)
