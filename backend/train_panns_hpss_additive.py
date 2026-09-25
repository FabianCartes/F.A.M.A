"""
backend/train_panns_hpss_additive.py
Entrenamiento de Transfer Learning con PANNs CNN14 (AudioSet) incorporando:
1. Entrada espectral HPSS de 3 canales (Original, Armónico, Percusivo)
2. Síntesis Aditiva Física (Physics-Guided Additive Mixing) para multiplicar muestras compuestas
3. Cabeza Multi-Task desacoplada (13 clases mecánicas + 7 subsistemas ortogonales)
4. Congelamiento de etapas convolucionales iniciales 1-4 para mitigar sobreajuste
"""
from pathlib import Path
import json
import time
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, classification_report

from training.schemas.config import AudioConfig
from training.pipelines.dataset import GenericAudioDataset
from training.pipelines.hpss_frontend import HPSSAudioFrontEnd
from training.pipelines.multitask_mapping import (
    MECHANICAL_ATTRIBUTES,
    CLASS_NAMES_13,
    build_multitask_targets_batch,
    decode_joint_predictions,
)
from training.pipelines.additive_mixing import AdditiveCompoundSampler
from training.pipelines.test_guard import (
    verify_test_set_integrity,
    FROZEN_ENGINE_TEST_SHA256,
    compute_expected_calibration_error,
)
from training.models.panns_cnn14 import PannsCNN14, load_panns_cnn14_pretrained
from poc.train import FocalLoss


def main():
    data_dir = Path("data/engine_diagnostics")
    test_csv = data_dir / "test_metadata.csv"
    verify_test_set_integrity(test_csv, FROZEN_ENGINE_TEST_SHA256)
    print(f"\n[Test Guard] Test set verificado bajo SHA-256 congelado: {FROZEN_ENGINE_TEST_SHA256[:16]}...")

    train_df = pd.read_csv(data_dir / "train_metadata.csv")
    val_df = pd.read_csv(data_dir / "val_metadata.csv")
    test_df = pd.read_csv(data_dir / "test_metadata.csv")

    classes = CLASS_NAMES_13
    label_to_idx = {c: i for i, c in enumerate(classes)}
    num_classes = len(classes)
    num_attributes = len(MECHANICAL_ATTRIBUTES)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[Setup] Dispositivo: {device} | Clases: {num_classes} | Atributos: {num_attributes}")

    audio_cfg = AudioConfig(
        target_sr=32000,
        duration_seconds=2.0,
        n_mels=128,
        n_fft=2048,
        hop_length=256,
        f_min=20.0,
        f_max=8000.0,
    )

    # 1. Frontend HPSS 3 Canales
    frontend = HPSSAudioFrontEnd(
        sample_rate=audio_cfg.target_sr,
        n_fft=audio_cfg.n_fft,
        hop_length=audio_cfg.hop_length,
        n_mels=audio_cfg.n_mels,
        f_min=audio_cfg.f_min,
        f_max=audio_cfg.f_max,
        kernel_size=15,
    ).to(device)

    # 2. Sampler de Síntesis Aditiva Física
    additive_sampler = AdditiveCompoundSampler(
        df=train_df,
        target_sr=audio_cfg.target_sr,
        duration_seconds=audio_cfg.duration_seconds,
    )

    # 3. Datasets y Dataloaders
    train_dataset = GenericAudioDataset(
        train_df,
        audio_config=audio_cfg,
        label_to_idx=label_to_idx,
        is_train=True,
        return_raw_waveform=True,
        additive_sampler=additive_sampler,
        synth_prob=0.5,
    )
    val_dataset = GenericAudioDataset(val_df, audio_config=audio_cfg, label_to_idx=label_to_idx, is_train=False, return_raw_waveform=True)
    test_dataset = GenericAudioDataset(test_df, audio_config=audio_cfg, label_to_idx=label_to_idx, is_train=False, return_raw_waveform=True)

    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)

    # 4. PANNs CNN14 MultiTask con AudioSet Transfer
    print("\n[PANNs] Instanciando CNN14 HPSS MultiTask con transferencia de AudioSet...")
    model = PannsCNN14(
        in_chans=3,
        num_classes=num_classes,
        num_attributes=num_attributes,
        drop_rate=0.3,
        pool_type="gem",
        freeze_stages=4,
    ).to(device)

    ckpt_path = Path("backend/checkpoints/pretrained/Cnn14_mAP=0.431.pth")
    loaded, total = load_panns_cnn14_pretrained(model, ckpt_path, device=device)
    print(f"[PANNs] Pesos transferidos desde AudioSet: {loaded}/{total} tensores cargados con éxito.")

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    print(f"[PANNs] Parámetros entrenables: {sum(p.numel() for p in trainable_params):,} de {sum(p.numel() for p in model.parameters()):,}")

    epochs = 30
    criterion_focal = FocalLoss(gamma=2.0)
    criterion_bce = nn.BCEWithLogitsLoss()

    optimizer = torch.optim.AdamW(trainable_params, lr=0.0005, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-6)

    print("\n" + "=" * 60)
    print(f"[Entrenamiento] Iniciando PANNs CNN14 HPSS MultiTask + Síntesis Aditiva ({epochs} épocas)")
    print("=" * 60)

    best_val_f1 = -1.0
    best_state_dict = None
    best_val_report = None

    for epoch in range(1, epochs + 1):
        t0 = time.time()
        model.train()
        train_loss = 0.0
        train_samples = 0
        train_correct = 0

        for x_wave, y_class in train_loader:
            x_wave = x_wave.to(device)
            y_class = y_class.to(device)

            features_3ch = frontend(x_wave)

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

        print(f"Época [{epoch:02d}/{epochs:02d}] ({dur:.1f}s) | Train Loss: {train_loss_avg:.4f} Acc: {train_acc*100:.1f}% | Val Acc: {val_acc*100:.1f}% F1: {val_f1:.4f}")

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            best_state_dict = {k: v.cpu() for k, v in model.state_dict().items()}
            best_val_report = classification_report(val_targets, joint_preds, target_names=classes, output_dict=True, zero_division=0)

    # 5. Cargar mejor estado y evaluación ciega en test_df
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
    print("RESULTADOS STANDALONE PANNs CNN14 HPSS ADITIVO EN TEST SET CIEGO:")
    print(f"  >> VALIDACIÓN: Best Val Macro F1 = {best_val_f1*100:.2f}%")
    print(f"  >> TEST SET CIEGO:")
    print(f"     Accuracy: {test_acc*100:.2f}%")
    print(f"     Macro F1: {test_f1*100:.2f}%")
    print(f"     ECE:      {test_ece:.4f}")
    print("=" * 60)

    ckpt_dir = Path("backend/checkpoints/car-engine-diagnostics-panns-cnn14-hpss-additive")
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    torch.save(best_state_dict, ckpt_dir / "weights.pt")

    receipt_path = Path(\"docs/receipts/fase6_panns_additive_receipt.json\")
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump({
            "model_id": "car-engine-diagnostics-panns-cnn14-hpss-additive",
            "architecture": "panns_cnn14_multitask_hpss_gem_additive",
            "technique": "Physics-Guided Additive Mixing + HPSS 3ch + AudioSet Transfer",
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
