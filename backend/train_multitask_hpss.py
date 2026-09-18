"""
backend/train_multitask_hpss.py
Entrenamiento de Fase 1: MultiTaskBioacousticModel con entrada HPSS de 3 canales y supervisión multi-task.
"""
from pathlib import Path
import json
import time
import yaml
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, classification_report

from training.schemas.config import TrainingConfig
from training.pipelines.dataset import GenericAudioDataset
from training.pipelines.hpss_frontend import HPSSAudioFrontEnd
from training.pipelines.multitask_mapping import (
    MECHANICAL_ATTRIBUTES,
    CLASS_NAMES_13,
    build_multitask_targets_batch,
    decode_joint_predictions,
)
from training.pipelines.test_guard import (
    verify_test_set_integrity,
    FROZEN_ENGINE_TEST_SHA256,
    compute_expected_calibration_error,
)
from training.models.multitask_bioacoustic import MultiTaskBioacousticModel
from poc.train import FocalLoss


def main():
    data_dir = Path("data/engine_diagnostics")
    test_csv = data_dir / "test_metadata.csv"
    verify_test_set_integrity(test_csv, FROZEN_ENGINE_TEST_SHA256)
    print(f"\n[Test Guard] Test set íntegro y congelado (SHA-256: {FROZEN_ENGINE_TEST_SHA256[:16]}...)")

    recipe_path = Path("backend/training/recipes/car_engine_diagnostics_resnet34d_multitask_hpss.yaml")
    with open(recipe_path, "r", encoding="utf-8") as f:
        cfg = TrainingConfig.model_validate(yaml.safe_load(f))

    train_df = pd.read_csv(data_dir / "train_metadata.csv")
    val_df = pd.read_csv(data_dir / "val_metadata.csv")
    test_df = pd.read_csv(data_dir / "test_metadata.csv")

    classes = CLASS_NAMES_13
    label_to_idx = {c: i for i, c in enumerate(classes)}
    num_classes = len(classes)
    num_attributes = len(MECHANICAL_ATTRIBUTES)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n[Setup] Dispositivo: {device} | Clases: {num_classes} | Atributos Multi-Task: {num_attributes}")

    # 1. Frontend HPSS 3 Canales con física de motor
    frontend = HPSSAudioFrontEnd(
        sample_rate=cfg.audio.target_sr,
        n_fft=cfg.audio.n_fft,
        hop_length=cfg.audio.hop_length,
        n_mels=cfg.audio.n_mels,
        f_min=cfg.audio.f_min,
        f_max=cfg.audio.f_max,
        kernel_size=15,
    ).to(device)

    # 2. Datasets & Loaders
    train_dataset = GenericAudioDataset(train_df, audio_config=cfg.audio, label_to_idx=label_to_idx, is_train=True, return_raw_waveform=True)
    val_dataset = GenericAudioDataset(val_df, audio_config=cfg.audio, label_to_idx=label_to_idx, is_train=False, return_raw_waveform=True)
    test_dataset = GenericAudioDataset(test_df, audio_config=cfg.audio, label_to_idx=label_to_idx, is_train=False, return_raw_waveform=True)

    train_loader = DataLoader(train_dataset, batch_size=cfg.batch_size, shuffle=True, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=cfg.batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=cfg.batch_size, shuffle=False)

    # 3. Modelo Multi-Task Bioacústico
    model = MultiTaskBioacousticModel(
        model_name="resnet34d",
        num_classes=num_classes,
        num_attributes=num_attributes,
        pretrained=True,
        in_chans=3,
        drop_rate=cfg.architecture.drop_rate,
        pool_type=cfg.architecture.pool_type,
    ).to(device)

    # Criterios de pérdida
    criterion_focal = FocalLoss(gamma=2.0)
    criterion_bce = nn.BCEWithLogitsLoss()

    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.optimizer.lr, weight_decay=cfg.optimizer.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=cfg.epochs, eta_min=1e-6)

    print("\n" + "=" * 60)
    print(f"[Fase 1] Iniciando entrenamiento de MultiTaskBioacousticModel (35 épocas)")
    print("=" * 60)

    best_val_f1 = -1.0
    best_state_dict = None
    best_val_report = None

    for epoch in range(1, cfg.epochs + 1):
        t0 = time.time()
        model.train()
        train_loss = 0.0
        train_samples = 0
        train_correct = 0

        for x_wave, y_class in train_loader:
            x_wave = x_wave.to(device)
            y_class = y_class.to(device)

            # Extraer 3 canales espectrales HPSS
            features_3ch = frontend(x_wave)

            # Construir targets binarios de atributos para el batch
            batch_class_names = [classes[idx] for idx in y_class.cpu().numpy()]
            y_attr = build_multitask_targets_batch(batch_class_names).to(device)

            optimizer.zero_grad()
            class_logits, attr_logits = model(features_3ch)

            loss_cls = criterion_focal(class_logits, y_class)
            loss_att = criterion_bce(attr_logits, y_attr)
            loss = loss_cls + 0.5 * loss_att

            loss.backward()
            optimizer.step()

            bsz = x_wave.size(0)
            train_loss += float(loss.item()) * bsz
            train_samples += bsz
            preds = torch.argmax(class_logits, dim=-1)
            train_correct += int(torch.sum(preds == y_class).item())

        scheduler.step()
        train_loss_avg = train_loss / max(1, train_samples)
        train_acc = train_correct / max(1, train_samples)

        # Validación
        model.eval()
        val_preds = []
        val_targets = []
        all_class_logits = []
        all_attr_logits = []

        with torch.no_grad():
            for x_wave, y_class in val_loader:
                x_wave = x_wave.to(device)
                features_3ch = frontend(x_wave)
                c_logits, a_logits = model(features_3ch)

                all_class_logits.append(c_logits.cpu())
                all_attr_logits.append(a_logits.cpu())
                val_targets.extend(y_class.numpy())

        cat_class_logits = torch.cat(all_class_logits, dim=0)
        cat_attr_logits = torch.cat(all_attr_logits, dim=0)
        joint_preds = decode_joint_predictions(cat_class_logits, cat_attr_logits, alpha_prior=0.25)

        val_acc = float(accuracy_score(val_targets, joint_preds))
        _, _, val_f1, _ = precision_recall_fscore_support(val_targets, joint_preds, average="macro", zero_division=0)
        dur = time.time() - t0

        print(f"Época [{epoch:02d}/{cfg.epochs:02d}] ({dur:.1f}s) | Train Loss: {train_loss_avg:.4f} Acc: {train_acc*100:.1f}% | Val Acc: {val_acc*100:.1f}% F1: {val_f1:.4f}")

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            best_state_dict = {k: v.cpu() for k, v in model.state_dict().items()}
            best_val_report = classification_report(val_targets, joint_preds, target_names=classes, output_dict=True, zero_division=0)

    # 4. Cargar mejor estado y evaluar CIEGAMENTE sobre Test Set
    if best_state_dict is not None:
        model.load_state_dict({k: v.to(device) for k, v in best_state_dict.items()})

    model.eval()
    test_targets = []
    test_class_logits = []
    test_attr_logits = []

    with torch.no_grad():
        for x_wave, y_class in test_loader:
            x_wave = x_wave.to(device)
            features_3ch = frontend(x_wave)
            c_logits, a_logits = model(features_3ch)

            test_class_logits.append(c_logits.cpu())
            test_attr_logits.append(a_logits.cpu())
            test_targets.extend(y_class.numpy())

    cat_test_class = torch.cat(test_class_logits, dim=0)
    cat_test_attr = torch.cat(test_attr_logits, dim=0)
    test_joint_preds = decode_joint_predictions(cat_test_class, cat_test_attr, alpha_prior=0.25)

    test_acc = float(accuracy_score(test_targets, test_joint_preds))
    _, _, test_f1, _ = precision_recall_fscore_support(test_targets, test_joint_preds, average="macro", zero_division=0)
    test_probs = torch.softmax(cat_test_class, dim=-1).numpy()
    test_ece = compute_expected_calibration_error(test_probs, np.array(test_targets))
    test_report = classification_report(test_targets, test_joint_preds, target_names=classes, output_dict=True, zero_division=0)

    print("\n" + "=" * 60)
    print("RESULTADOS FINALES FASE 1 (MultiTask + HPSS 3-Canales):")
    print(f"  >> VALIDACIÓN: Best Val Macro F1 = {best_val_f1*100:.2f}%")
    print(f"  >> TEST SET (CIEGO):")
    print(f"     Accuracy: {test_acc*100:.2f}%")
    print(f"     Macro F1: {test_f1*100:.2f}%")
    print(f"     ECE:      {test_ece:.4f}")
    print("=" * 60)

    # Guardar Checkpoint y Recibo RDD
    ckpt_dir = Path("backend/checkpoints/car-engine-diagnostics-resnet34d-multitask-hpss")
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    torch.save(best_state_dict, ckpt_dir / "weights.pt")

    receipt_path = Path("docs/fase1_multitask_hpss_receipt.json")
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump({
            "model_id": cfg.model_id,
            "architecture": "resnet34d_multitask_hpss",
            "in_chans": 3,
            "audio_specs": {
                "sample_rate": cfg.audio.target_sr,
                "n_fft": cfg.audio.n_fft,
                "hop_length": cfg.audio.hop_length,
                "n_mels": cfg.audio.n_mels,
                "f_min": cfg.audio.f_min,
                "f_max": cfg.audio.f_max,
            },
            "validation_metrics": {
                "best_val_macro_f1": best_val_f1,
                "val_report": best_val_report,
            },
            "blind_test_metrics": {
                "test_accuracy": test_acc,
                "test_macro_f1": test_f1,
                "test_ece": test_ece,
                "test_report": test_report,
            }
        }, f, indent=2)

    print(f"\n[RDD Receipt] Recibo técnico guardado en: {receipt_path}")


if __name__ == "__main__":
    main()
