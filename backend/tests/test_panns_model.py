"""
backend/tests/test_panns_model.py
Pruebas de TDD para la arquitectura PANNs CNN14, congelamiento parcial de etapas y carga de pesos de AudioSet.
"""
from pathlib import Path
import pytest
import torch

from training.models.panns_cnn14 import PannsCNN14, load_panns_cnn14_pretrained


def test_panns_cnn14_forward_pass():
    model = PannsCNN14(
        in_chans=3,
        num_classes=13,
        pool_type="gem",
    )

    bsz = 2
    # Entrada Mel 3 canales: [B, 3, n_mels=128, time_frames=94]
    x = torch.randn(bsz, 3, 128, 94)
    logits = model(x)

    assert logits.shape == (bsz, 13)
    assert not torch.isnan(logits).any()


def test_panns_cnn14_freeze_stages():
    model = PannsCNN14(
        in_chans=3,
        num_classes=13,
        freeze_stages=4,
    )

    # Las etapas 1 a 4 deben estar congeladas (requires_grad = False)
    for block_idx in range(1, 5):
        block = getattr(model, f"conv_block{block_idx}")
        for param in block.parameters():
            assert param.requires_grad is False

    # Las etapas 5 y 6 y las cabezas deben estar entrenables
    for block_idx in [5, 6]:
        block = getattr(model, f"conv_block{block_idx}")
        for param in block.parameters():
            assert param.requires_grad is True

    assert model.fc_class.weight.requires_grad is True


def test_panns_weight_loading_with_channel_adaptation():
    ckpt_path = Path("backend/checkpoints/pretrained/Cnn14_mAP=0.431.pth")
    if not ckpt_path.exists():
        pytest.skip("Pretrained checkpoint not present on disk")

    model = PannsCNN14(in_chans=3, num_classes=13)
    loaded_keys, total_keys = load_panns_cnn14_pretrained(model, ckpt_path)

    assert loaded_keys > 50
    # Comprobar que conv_block1.conv1.weight tenga forma [64, 3, 3, 3] adaptada
    assert model.conv_block1.conv1.weight.shape == (64, 3, 3, 3)
