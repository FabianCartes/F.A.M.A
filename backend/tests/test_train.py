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
