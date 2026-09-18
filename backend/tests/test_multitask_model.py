"""
backend/tests/test_multitask_model.py
Pruebas de TDD para la arquitectura bioacústica multi-task con entrada de 3 canales (HPSS) y doble cabeza de clasificación.
"""
import pytest
import torch

from training.models.multitask_bioacoustic import MultiTaskBioacousticModel
from training.pipelines.multitask_mapping import MECHANICAL_ATTRIBUTES


def test_multitask_bioacoustic_model_instantiation_and_forward():
    num_classes = 13
    num_attrs = len(MECHANICAL_ATTRIBUTES)

    model = MultiTaskBioacousticModel(
        model_name="resnet34d",
        num_classes=num_classes,
        num_attributes=num_attrs,
        pretrained=False,
        in_chans=3,
        pool_type="gem",
    )

    # Tensor de entrada [B, 3, n_mels, time_frames]
    bsz = 2
    x = torch.randn(bsz, 3, 128, 94)

    class_logits, attr_logits = model(x)

    assert class_logits.shape == (bsz, num_classes)
    assert attr_logits.shape == (bsz, num_attrs)


def test_multitask_bioacoustic_loss_backward():
    num_classes = 13
    num_attrs = len(MECHANICAL_ATTRIBUTES)
    model = MultiTaskBioacousticModel(
        model_name="resnet34d",
        num_classes=num_classes,
        num_attributes=num_attrs,
        pretrained=False,
        in_chans=3,
    )

    x = torch.randn(2, 3, 64, 30)
    y_class = torch.tensor([0, 5])
    y_attr = torch.zeros(2, num_attrs)
    y_attr[0, 0] = 1.0

    class_logits, attr_logits = model(x)

    crit_class = torch.nn.CrossEntropyLoss()
    crit_attr = torch.nn.BCEWithLogitsLoss()

    loss = crit_class(class_logits, y_class) + 0.5 * crit_attr(attr_logits, y_attr)
    loss.backward()

    # Comprobar que los gradientes fluyan hacia ambas cabezas y el extractor
    assert model.head_class.weight.grad is not None
    assert model.head_attributes.weight.grad is not None


def test_multitask_bioacoustic_efficientnet_instantiation_and_backward():
    num_classes = 13
    num_attrs = len(MECHANICAL_ATTRIBUTES)
    model = MultiTaskBioacousticModel(
        model_name="efficientnet_b0",
        num_classes=num_classes,
        num_attributes=num_attrs,
        pretrained=False,
        in_chans=3,
        pool_type="gem",
    )

    x = torch.randn(2, 3, 128, 94)
    y_class = torch.tensor([1, 4])
    y_attr = torch.zeros(2, num_attrs)
    y_attr[0, 1] = 1.0

    class_logits, attr_logits = model(x)
    assert class_logits.shape == (2, num_classes)
    assert attr_logits.shape == (2, num_attrs)

    crit_class = torch.nn.CrossEntropyLoss()
    crit_attr = torch.nn.BCEWithLogitsLoss()
    loss = crit_class(class_logits, y_class) + 0.5 * crit_attr(attr_logits, y_attr)
    loss.backward()

    assert model.head_class.weight.grad is not None
    assert model.head_attributes.weight.grad is not None

