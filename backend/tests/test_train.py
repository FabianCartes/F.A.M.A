import torch
import torch.nn as nn
import pandas as pd
import numpy as np
import pytest
import soundfile as sf
from poc.train import (
    AudioCNN,
    AudioDataset,
    train_one_epoch,
    evaluate_loss_acc,
    build_dataloaders,
    apply_mixup,
)

def test_audiocnn_forward_pass():
    num_classes = 15
    model = AudioCNN(num_classes=num_classes)
    
    # Input batch: (batch_size=4, channels=1, n_mels=64, time_steps=216)
    x = torch.randn(4, 1, 64, 216)
    out = model(x)
    
    assert out.shape == (4, num_classes)
    assert not torch.isnan(out).any()

def test_audio_dataset_synthetic(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sp_dir = raw_dir / "chincol"
    sp_dir.mkdir()
    
    fake_audio = np.random.randn(22050 * 2).astype(np.float32)
    sf.write(str(sp_dir / "101.mp3"), fake_audio, 22050)
    
    df = pd.DataFrame([
        {"nombre_archivo": "101.mp3", "clase": "Chincol", "xc_id": "101", "recordist": "Rec1"}
    ])
    label_to_idx = {"Chincol": 0}
    
    dataset = AudioDataset(df, raw_dir=raw_dir, label_to_idx=label_to_idx, n_mels=64, is_train=False)
    assert len(dataset) == 1
    
    mel_tensor, label_tensor = dataset[0]
    assert isinstance(mel_tensor, torch.Tensor)
    assert mel_tensor.shape[0] == 1  # 1 channel
    assert mel_tensor.shape[1] == 64  # 64 mel bins
    assert label_tensor.item() == 0

def test_audio_dataset_deterministic_when_eval(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sp_dir = raw_dir / "zorzal"
    sp_dir.mkdir()
    
    # 8 seconds audio
    t = np.linspace(0, 8.0, int(22050 * 8.0), endpoint=False)
    fake_audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sf.write(str(sp_dir / "202.mp3"), fake_audio, 22050)
    
    df = pd.DataFrame([
        {"nombre_archivo": "202.mp3", "clase": "Zorzal", "xc_id": "202", "recordist": "Rec2"}
    ])
    label_to_idx = {"Zorzal": 0}
    
    # is_train=False -> deterministic
    eval_ds = AudioDataset(df, raw_dir=raw_dir, label_to_idx=label_to_idx, is_train=False)
    tensor1, _ = eval_ds[0]
    tensor2, _ = eval_ds[0]
    
    assert torch.equal(tensor1, tensor2), "Evaluation dataset must be 100% deterministic!"

def test_audio_dataset_augmentation_in_train(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sp_dir = raw_dir / "tordo"
    sp_dir.mkdir()
    
    # 10 seconds active audio with harmonics
    t = np.linspace(0, 10.0, int(22050 * 10.0), endpoint=False)
    fake_audio = (0.4 * np.sin(2 * np.pi * 500 * t) + 0.3 * np.sin(2 * np.pi * 1200 * t)).astype(np.float32)
    sf.write(str(sp_dir / "303.mp3"), fake_audio, 22050)
    
    df = pd.DataFrame([
        {"nombre_archivo": "303.mp3", "clase": "Tordo", "xc_id": "303", "recordist": "Rec3"}
    ])
    label_to_idx = {"Tordo": 0}
    
    # is_train=True -> on-the-fly augmentation enabled
    train_ds = AudioDataset(
        df,
        raw_dir=raw_dir,
        label_to_idx=label_to_idx,
        is_train=True,
        time_shift_prob=1.0,
        gain_prob=1.0,
        noise_prob=1.0,
        spec_augment_prob=1.0,
    )
    
    tensors = [train_ds[0][0] for _ in range(3)]
    for t in tensors:
        assert t.shape == (1, 64, 216)
    
    # Check that variations exist between stochastic draws
    diff_0_1 = torch.abs(tensors[0] - tensors[1]).sum().item()
    assert diff_0_1 > 0.1, "Augmentations should introduce variation across training draws"


def test_audio_dataset_raw_waveform(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sp_dir = raw_dir / "chincol"
    sp_dir.mkdir()

    fake_audio = np.random.randn(22050 * 3).astype(np.float32)
    sf.write(str(sp_dir / "101.mp3"), fake_audio, 22050)

    df = pd.DataFrame([
        {"nombre_archivo": "101.mp3", "clase": "Chincol", "xc_id": "101", "recordist": "Rec1"}
    ])
    label_to_idx = {"Chincol": 0}

    dataset = AudioDataset(
        df,
        raw_dir=raw_dir,
        label_to_idx=label_to_idx,
        is_train=False,
        return_raw_waveform=True,
    )
    assert len(dataset) == 1

    wav_tensor, label_tensor = dataset[0]
    assert isinstance(wav_tensor, torch.Tensor)
    assert wav_tensor.ndim == 1
    assert wav_tensor.shape[0] == 110250
    assert label_tensor.item() == 0

    # is_train=True with data augmentation
    train_dataset = AudioDataset(
        df,
        raw_dir=raw_dir,
        label_to_idx=label_to_idx,
        is_train=True,
        time_shift_prob=1.0,
        gain_prob=1.0,
        noise_prob=1.0,
        return_raw_waveform=True,
    )
    w1, _ = train_dataset[0]
    w2, _ = train_dataset[0]
    assert w1.shape == (110250,)
    assert w2.shape == (110250,)
    assert not torch.equal(w1, w2)


def test_train_and_eval_step():
    model = AudioCNN(num_classes=2)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    
    features = torch.randn(8, 1, 64, 216)
    labels = torch.tensor([0, 1, 0, 1, 0, 1, 0, 1])
    dataset = torch.utils.data.TensorDataset(features, labels)
    loader = torch.utils.data.DataLoader(dataset, batch_size=4)
    
    device = torch.device("cpu")
    loss, acc = train_one_epoch(
        model,
        loader,
        criterion,
        optimizer,
        device,
        epoch=1,
        total_epochs=3,
        show_progress=True,
    )
    assert loss > 0.0
    assert 0.0 <= acc <= 1.0
    
    val_loss, val_acc = evaluate_loss_acc(model, loader, criterion, device)
    assert val_loss > 0.0
    assert 0.0 <= val_acc <= 1.0


def test_build_dataloaders_concurrency_and_seeding(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sp_dir = raw_dir / "chincol"
    sp_dir.mkdir()

    # Create 4 synthetic audio files
    for i in range(4):
        fake_audio = np.random.randn(int(22050 * 1.5)).astype(np.float32)
        sf.write(str(sp_dir / f"{i}.mp3"), fake_audio, 22050)

    train_df = pd.DataFrame([
        {"nombre_archivo": "0.mp3", "clase": "Chincol", "xc_id": "0", "recordist": "R1"},
        {"nombre_archivo": "1.mp3", "clase": "Chincol", "xc_id": "1", "recordist": "R1"},
    ])
    val_df = pd.DataFrame([
        {"nombre_archivo": "2.mp3", "clase": "Chincol", "xc_id": "2", "recordist": "R2"},
        {"nombre_archivo": "3.mp3", "clase": "Chincol", "xc_id": "3", "recordist": "R2"},
    ])
    label_to_idx = {"Chincol": 0}

    train_loader, val_loader = build_dataloaders(
        train_df=train_df,
        val_df=val_df,
        raw_dir=raw_dir,
        label_to_idx=label_to_idx,
        batch_size=2,
        num_workers=2,
        pin_memory=False,
    )

    assert train_loader.num_workers == 2
    assert val_loader.num_workers == 2

    # Verify batch consumption without deadlocks or serialization errors
    x_tr, y_tr = next(iter(train_loader))
    assert x_tr.shape == (2, 1, 64, 216)
    assert y_tr.shape == (2,)

    x_val, y_val = next(iter(val_loader))
    assert x_val.shape == (2, 1, 64, 216)
    assert y_val.shape == (2,)


def test_build_dataloaders_raw_waveform(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sp_dir = raw_dir / "chincol"
    sp_dir.mkdir()

    for i in range(2):
        fake_audio = np.random.randn(int(22050 * 1.0)).astype(np.float32)
        sf.write(str(sp_dir / f"{i}.mp3"), fake_audio, 22050)

    train_df = pd.DataFrame([
        {"nombre_archivo": "0.mp3", "clase": "Chincol", "xc_id": "0", "recordist": "R1"},
    ])
    val_df = pd.DataFrame([
        {"nombre_archivo": "1.mp3", "clase": "Chincol", "xc_id": "1", "recordist": "R2"},
    ])
    label_to_idx = {"Chincol": 0}

    train_loader, val_loader = build_dataloaders(
        train_df=train_df,
        val_df=val_df,
        raw_dir=raw_dir,
        label_to_idx=label_to_idx,
        batch_size=1,
        num_workers=0,
        return_raw_waveform=True,
    )

    x_tr, y_tr = next(iter(train_loader))
    assert x_tr.shape == (1, 110250)
    assert y_tr.shape == (1,)

    x_val, y_val = next(iter(val_loader))
    assert x_val.shape == (1, 110250)
    assert y_val.shape == (1,)


def test_focal_loss_equivalence_when_gamma_zero():
    from poc.train import FocalLoss

    criterion_fl = FocalLoss(gamma=0.0)
    criterion_ce = nn.CrossEntropyLoss()

    logits = torch.tensor([[2.0, 1.0, 0.1], [0.5, 2.5, 0.2]], requires_grad=True)
    targets = torch.tensor([0, 1])

    loss_fl = criterion_fl(logits, targets)
    loss_ce = criterion_ce(logits, targets)

    assert torch.allclose(loss_fl, loss_ce, atol=1e-5)


def test_focal_loss_modulates_easy_examples():
    from poc.train import FocalLoss

    criterion_fl = FocalLoss(gamma=2.0)
    criterion_ce = nn.CrossEntropyLoss()

    # Ejemplo muy fácil (alta confianza para la clase correcta)
    easy_logits = torch.tensor([[10.0, -5.0, -5.0]])
    targets = torch.tensor([0])

    loss_fl = criterion_fl(easy_logits, targets)
    loss_ce = criterion_ce(easy_logits, targets)

    # Con gamma=2.0, la pérdida para un ejemplo fácil debe ser sustancialmente menor que CE
    assert loss_fl < loss_ce * 0.1
    assert not torch.isnan(loss_fl)


def test_bioacoustic_efficientnet():
    from poc.train import BioacousticEfficientNet

    model = BioacousticEfficientNet(model_name="efficientnet_b0", num_classes=15, pretrained=False)
    # Batch de 2 espectrogramas con 128 bandas Mel y 216 pasos de tiempo
    x = torch.randn(2, 1, 128, 216)
    out = model(x)

    assert out.shape == (2, 15)
    assert not torch.isnan(out).any()


def test_apply_mixup_properties():
    batch_size = 8
    x = torch.randn(batch_size, 1, 64, 216, dtype=torch.float32)
    y = torch.arange(batch_size, dtype=torch.long)

    x_mix, y_a, y_b, lam = apply_mixup(x, y, alpha=0.2, prob=1.0)

    assert isinstance(x_mix, torch.Tensor)
    assert isinstance(y_a, torch.Tensor)
    assert isinstance(y_b, torch.Tensor)
    assert isinstance(lam, float)

    assert x_mix.shape == x.shape
    assert x_mix.dtype == x.dtype
    assert y_a.shape == y.shape
    assert y_a.dtype == y.dtype
    assert y_b.shape == y.shape
    assert y_b.dtype == y.dtype

    # Symmetrization check: lam must be >= 0.5 and <= 1.0
    assert 0.5 <= lam <= 1.0

    # Original targets y_a should match y
    assert torch.equal(y_a, y)

    # Convex combination check: since y is arange(batch_size), y_b is the permutation indices!
    # Therefore x[y_b] is exactly x[perm].
    expected_mix = lam * x + (1.0 - lam) * x[y_b]
    assert torch.allclose(x_mix, expected_mix, atol=1e-5)

    # Respect prob=0.0: intact tensors and lam=1.0
    x_no_mix, y_a_no, y_b_no, lam_no = apply_mixup(x, y, alpha=0.2, prob=0.0)
    assert lam_no == 1.0
    assert torch.equal(x_no_mix, x)
    assert torch.equal(y_a_no, y)
    assert torch.equal(y_b_no, y)


def test_mixup_focal_loss_backward():
    from poc.train import BioacousticEfficientNet, FocalLoss

    model = BioacousticEfficientNet(model_name="efficientnet_b0", num_classes=4, pretrained=False)
    criterion = FocalLoss(gamma=2.0)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    x = torch.randn(4, 1, 128, 216)
    y = torch.tensor([0, 1, 2, 3], dtype=torch.long)

    x_mix, y_a, y_b, lam = apply_mixup(x, y, alpha=0.2, prob=1.0)

    optimizer.zero_grad()
    outputs = model(x_mix)
    loss = lam * criterion(outputs, y_a) + (1.0 - lam) * criterion(outputs, y_b)

    assert loss.item() > 0.0
    assert not torch.isnan(loss)

    loss.backward()

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    assert len(trainable_params) > 0
    for p in trainable_params:
        assert p.grad is not None
        assert not torch.isnan(p.grad).any()


def test_train_one_epoch_with_mixup():
    model = AudioCNN(num_classes=2)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    features = torch.randn(8, 1, 64, 216)
    labels = torch.tensor([0, 1, 0, 1, 0, 1, 0, 1])
    dataset = torch.utils.data.TensorDataset(features, labels)
    loader = torch.utils.data.DataLoader(dataset, batch_size=4)

    device = torch.device("cpu")
    loss, acc = train_one_epoch(
        model,
        loader,
        criterion,
        optimizer,
        device,
        epoch=1,
        total_epochs=1,
        show_progress=False,
        mixup_alpha=0.2,
        mixup_prob=1.0,
    )
    assert loss > 0.0
    assert 0.0 <= acc <= 1.0


def test_train_and_eval_with_frontend_and_specaugment():
    from poc.preprocess import GPUAudioFrontEnd, GPUSpecAugment

    model = AudioCNN(num_classes=2)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    frontend = GPUAudioFrontEnd(n_mels=64, normalize=True)
    spec_augment = GPUSpecAugment(prob=1.0)

    raw_waves = torch.randn(8, 110250)
    labels = torch.tensor([0, 1, 0, 1, 0, 1, 0, 1])
    dataset = torch.utils.data.TensorDataset(raw_waves, labels)
    loader = torch.utils.data.DataLoader(dataset, batch_size=4)

    device = torch.device("cpu")
    loss, acc = train_one_epoch(
        model,
        loader,
        criterion,
        optimizer,
        device,
        epoch=1,
        total_epochs=1,
        show_progress=False,
        frontend=frontend,
        spec_augment=spec_augment,
        mixup_alpha=0.2,
        mixup_prob=1.0,
    )
    assert loss > 0.0
    assert 0.0 <= acc <= 1.0

    val_loss, val_acc = evaluate_loss_acc(
        model,
        loader,
        criterion,
        device,
        frontend=frontend,
    )
    assert val_loss > 0.0
    assert 0.0 <= val_acc <= 1.0


def test_bioacoustic_efficientnet_gem_forward():
    from poc.train import BioacousticEfficientNet
    from poc.preprocess import GeM

    model = BioacousticEfficientNet(
        model_name="efficientnet_b0",
        num_classes=15,
        pretrained=False,
        pool_type="gem",
    )
    assert isinstance(model.backbone.global_pool, GeM)

    x = torch.randn(2, 1, 128, 216)
    out = model(x)

    assert out.shape == (2, 15)
    assert not torch.isnan(out).any()


def test_bioacoustic_efficientnet_freeze_lifecycle():
    from poc.train import BioacousticEfficientNet

    model = BioacousticEfficientNet(
        model_name="efficientnet_b0",
        num_classes=15,
        pretrained=False,
        pool_type="gem",
    )

    # Fase 1: Warmup (congelar backbone)
    model.freeze_backbone()
    assert model.backbone.global_pool.p.requires_grad is False

    classifier = model.backbone.get_classifier()
    if isinstance(classifier, torch.nn.Module):
        for p in classifier.parameters():
            assert p.requires_grad is True

    # Fase 2: Fine-Tuning (descongelar backbone)
    model.unfreeze_backbone()
    assert model.backbone.global_pool.p.requires_grad is True


def test_checkpoint_backward_compatibility():
    from poc.train import BioacousticEfficientNet

    # Modelo con GAP tradicional (pool_type="avg")
    model_avg = BioacousticEfficientNet(
        model_name="efficientnet_b0",
        num_classes=15,
        pretrained=False,
        pool_type="avg",
    )
    state_dict_avg = model_avg.state_dict()
    assert "backbone.global_pool.p" not in state_dict_avg

    # Cargar checkpoint con pool_type="avg" sin romper llaves ni generar incompatibilidad
    loaded_avg = BioacousticEfficientNet(
        model_name="efficientnet_b0",
        num_classes=15,
        pretrained=False,
        pool_type="avg",
    )
    loaded_avg.load_state_dict(state_dict_avg)
    x = torch.randn(2, 1, 128, 216)
    out_avg = loaded_avg(x)
    assert out_avg.shape == (2, 15)

    # Modelo con GeM (pool_type="gem")
    model_gem = BioacousticEfficientNet(
        model_name="efficientnet_b0",
        num_classes=15,
        pretrained=False,
        pool_type="gem",
    )
    state_dict_gem = model_gem.state_dict()
    assert "backbone.global_pool.p" in state_dict_gem
    loaded_gem = BioacousticEfficientNet(
        model_name="efficientnet_b0",
        num_classes=15,
        pretrained=False,
        pool_type="gem",
    )
    loaded_gem.load_state_dict(state_dict_gem)
    out_gem = loaded_gem(x)
    assert out_gem.shape == (2, 15)


def test_bioacoustic_model_supports_convnext():
    from poc.train import BioacousticModel

    model = BioacousticModel(
        model_name="convnext_nano.d1h_in1k",
        num_classes=15,
        pretrained=False,
    )
    # Forward pass con tensor de entrada [B, 1, 128, 216]
    x = torch.randn(2, 1, 128, 216)
    out = model(x)
    assert out.shape == (2, 15)
    assert not torch.isnan(out).any()

    # Verificar freeze_backbone()
    model.freeze_backbone()
    conv_params = [p for name, p in model.named_parameters() if "fc" not in name and "classifier" not in name]
    assert len(conv_params) > 0
    assert all(not p.requires_grad for p in conv_params)

    # Parámetros de la cabeza clasificadora deben estar descongelados
    classifier = model.backbone.get_classifier() if hasattr(model.backbone, "get_classifier") else None
    if isinstance(classifier, torch.nn.Module):
        assert all(p.requires_grad for p in classifier.parameters())
    elif hasattr(model.backbone, "head") and hasattr(model.backbone.head, "fc"):
        assert all(p.requires_grad for p in model.backbone.head.fc.parameters())

    # Verificar unfreeze_backbone()
    model.unfreeze_backbone()
    assert all(p.requires_grad for p in model.parameters())


def test_bioacoustic_model_supports_resnet34d():
    from poc.train import BioacousticModel

    model = BioacousticModel(
        model_name="resnet34d",
        num_classes=15,
        pretrained=False,
    )
    # Forward pass con tensor de entrada [B, 1, 128, 216]
    x = torch.randn(2, 1, 128, 216)
    out = model(x)
    assert out.shape == (2, 15)
    assert not torch.isnan(out).any()

    # Verificar freeze_backbone()
    model.freeze_backbone()
    conv_params = [p for name, p in model.named_parameters() if "fc" not in name and "classifier" not in name]
    assert len(conv_params) > 0
    assert all(not p.requires_grad for p in conv_params)

    # Parámetros de la cabeza clasificadora (get_classifier() o .fc) deben estar descongelados
    classifier = model.backbone.get_classifier() if hasattr(model.backbone, "get_classifier") else None
    if isinstance(classifier, torch.nn.Module):
        assert all(p.requires_grad for p in classifier.parameters())
    elif hasattr(model.backbone, "fc"):
        assert all(p.requires_grad for p in model.backbone.fc.parameters())

    # Verificar unfreeze_backbone()
    model.unfreeze_backbone()
    assert all(p.requires_grad for p in model.parameters())




