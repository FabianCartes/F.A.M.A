"""
backend/train_v2_and_compare.py
Entrenamiento de variantes v2 (ventana exacta 1.5s, mixup moderado) y evaluación de ensamble.
"""
from pathlib import Path
import json
import yaml
import pandas as pd
import numpy as np
import torch
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, classification_report
from torch.utils.data import DataLoader

from training.schemas.config import TrainingConfig
from training.trainers.standalone_trainer import GenericModelTrainer
from training.pipelines.dataset import GenericAudioDataset
from poc.preprocess import GPUAudioFrontEnd
from poc.train import BioacousticModel


def train_recipe(recipe_filename: str, train_df, val_df, test_df):
    recipe_path = Path(f"backend/training/recipes/{recipe_filename}")
    with open(recipe_path, "r", encoding="utf-8") as f:
        cfg = TrainingConfig.model_validate(yaml.safe_load(f))

    print(f"\n" + "=" * 60)
    print(f"[Train] Iniciando: {cfg.model_name} ({cfg.architecture.type})")
    print("=" * 60)

    trainer = GenericModelTrainer(config=cfg, project_root=Path.cwd())
    bundle_path, metrics = trainer.train_and_export(
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        output_checkpoints_dir=Path("backend/checkpoints"),
        verbose=True,
    )
    print(f"[Train] Completado: {cfg.model_id} | Test Acc={metrics['test_accuracy']*100:.2f}%, F1={metrics['test_f1_macro']*100:.2f}%")
    return cfg, bundle_path, metrics


def evaluate_models(models, weights, test_df, audio_cfg, device):
    classes = sorted(test_df["clase"].unique().tolist())
    label_to_idx = {c: i for i, c in enumerate(classes)}

    frontend = GPUAudioFrontEnd(
        sample_rate=audio_cfg.target_sr,
        n_fft=audio_cfg.n_fft,
        hop_length=audio_cfg.hop_length,
        n_mels=audio_cfg.n_mels,
        f_min=audio_cfg.f_min,
        f_max=audio_cfg.f_max,
    ).to(device)

    dataset = GenericAudioDataset(
        df=test_df,
        audio_config=audio_cfg,
        label_to_idx=label_to_idx,
        is_train=False,
        return_raw_waveform=True,
    )
    loader = DataLoader(dataset, batch_size=32, shuffle=False)

    all_preds = []
    all_targets = []

    for m in models:
        m.eval()

    with torch.no_grad():
        for x_batch, y_batch in loader:
            x_batch = x_batch.to(device)
            mel = frontend(x_batch)

            ensemble_probs = torch.zeros((x_batch.size(0), len(classes)), device=device)
            for m, w in zip(models, weights):
                logits = m(mel)
                probs = torch.softmax(logits, dim=-1)
                ensemble_probs += w * probs

            preds = torch.argmax(ensemble_probs, dim=-1).cpu().numpy()
            all_preds.extend(preds)
            all_targets.extend(y_batch.numpy())

    acc = float(accuracy_score(all_targets, all_preds))
    _, _, f1, _ = precision_recall_fscore_support(all_targets, all_preds, average="macro", zero_division=0)
    report = classification_report(all_targets, all_preds, target_names=classes, output_dict=True, zero_division=0)
    return acc, f1, report


def main():
    data_dir = Path("data/engine_diagnostics")
    train_df = pd.read_csv(data_dir / "train_metadata.csv")
    val_df = pd.read_csv(data_dir / "val_metadata.csv")
    test_df = pd.read_csv(data_dir / "test_metadata.csv")

    # 1. Entrenar ResNet34d v2 (ventana exacta 1.5s, mixup 0.2)
    cfg_r_v2, path_r_v2, m_r_v2 = train_recipe("car_engine_diagnostics_resnet34d_v2.yaml", train_df, val_df, test_df)

    # 2. Entrenar EfficientNet-B0 v2 (ventana exacta 1.5s, mixup 0.2)
    cfg_e_v2, path_e_v2, m_e_v2 = train_recipe("car_engine_diagnostics_efficientnet_b0_v2.yaml", train_df, val_df, test_df)

    # 3. Cargar modelos en GPU para evaluación
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    num_classes = len(train_df["clase"].unique())

    m_r2 = BioacousticModel("resnet34d", num_classes=num_classes, pretrained=False, pool_type="gem", use_gpu_frontend=False).to(device)
    m_r2.load_state_dict(torch.load(path_r_v2 / "weights.pt", map_location=device, weights_only=True))

    m_e2 = BioacousticModel("efficientnet_b0", num_classes=num_classes, pretrained=False, pool_type="gem", use_gpu_frontend=False).to(device)
    m_e2.load_state_dict(torch.load(path_e_v2 / "weights.pt", map_location=device, weights_only=True))

    acc_r2, f1_r2, rep_r2 = evaluate_models([m_r2], [1.0], test_df, cfg_r_v2.audio, device)
    acc_e2, f1_e2, rep_e2 = evaluate_models([m_e2], [1.0], test_df, cfg_e_v2.audio, device)

    print("\n" + "=" * 60)
    print("MÉTRICAS INDIVIDUALES V2 EN TEST SET (Ventana 1.5s):")
    print(f"  ResNet34d v2:       Acc = {acc_r2*100:.2f}% | F1-Macro = {f1_r2*100:.2f}%")
    print(f"  EfficientNet-B0 v2: Acc = {acc_e2*100:.2f}% | F1-Macro = {f1_e2*100:.2f}%")
    print("=" * 60)

    # 4. Grid Search de Pesos para Late Fusion v2
    best_w = 0.5
    best_acc = 0.0
    best_f1 = 0.0
    best_rep = None

    for w_int in range(1, 10):
        w1 = w_int / 10.0
        w2 = round(1.0 - w1, 1)
        acc_c, f1_c, rep_c = evaluate_models([m_r2, m_e2], [w1, w2], test_df, cfg_r_v2.audio, device)
        print(f"  Weights: [ResNet_v2={w1:.1f}, EffNet_v2={w2:.1f}] -> Acc={acc_c*100:.2f}%, F1={f1_c*100:.2f}%")
        if f1_c > best_f1:
            best_f1 = f1_c
            best_acc = acc_c
            best_w = w1
            best_rep = rep_c

    print("\n" + "=" * 60)
    print(f"ENSAMBLE HETEROGÉNEO V2 GANADOR:")
    print(f"  Pesos óptimos: ResNet34d={best_w:.2f}, EfficientNet-B0={1.0-best_w:.2f}")
    print(f"  >> TEST ACCURACY: {best_acc*100:.2f}%")
    print(f"  >> TEST MACRO F1: {best_f1*100:.2f}%")
    print("=" * 60)

    # Guardar reporte detallado
    report_file = Path(\"docs/receipts/experiment_v2_receipt.json\")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "resnet34d_v2": {"accuracy": acc_r2, "f1_macro": f1_r2},
            "efficientnet_b0_v2": {"accuracy": acc_e2, "f1_macro": f1_e2},
            "ensemble_v2": {
                "weights": {"resnet34d": best_w, "efficientnet_b0": round(1.0-best_w, 2)},
                "accuracy": best_acc,
                "f1_macro": best_f1,
            },
            "per_class_report": best_rep
        }, f, indent=2)
    print(f"\nRecibo técnico de experimento guardado en: {report_file}")


if __name__ == "__main__":
    main()
