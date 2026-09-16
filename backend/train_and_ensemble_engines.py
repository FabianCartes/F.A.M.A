"""
backend/train_and_ensemble_engines.py
Entrenamiento de ConvNeXt-Nano y EfficientNet-B0, seguido de evaluación y ensamblado tri-modelo.
"""
from pathlib import Path
import yaml
import pandas as pd
import numpy as np
import torch
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

from training.schemas.config import TrainingConfig
from training.trainers.standalone_trainer import GenericModelTrainer
from training.pipelines.dataset import GenericAudioDataset
from training.pipelines.test_guard import verify_test_set_integrity, FROZEN_ENGINE_TEST_SHA256
from training.pipelines.ensemble_tuner import tune_ensemble_calibration, evaluate_calibrated_ensemble
from torch.utils.data import DataLoader
from poc.preprocess import GPUAudioFrontEnd
from poc.train import BioacousticModel


def train_model(recipe_name: str, train_df, val_df, test_df):
    recipe_path = Path(f"backend/training/recipes/{recipe_name}")
    with open(recipe_path, "r", encoding="utf-8") as f:
        cfg = TrainingConfig.model_validate(yaml.safe_load(f))

    print(f"\n" + "=" * 60)
    print(f"[Train] Iniciando entrenamiento: {cfg.model_name} ({cfg.architecture.type})")
    print("=" * 60)

    trainer = GenericModelTrainer(config=cfg, project_root=Path.cwd())
    bundle_path, metrics = trainer.train_and_export(
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        output_checkpoints_dir=Path("backend/checkpoints"),
        verbose=True,
    )
    print(f"[Train] Completado: {cfg.model_id} | Test F1={metrics['test_f1_macro']:.4f}")
    return cfg, bundle_path, metrics


def evaluate_ensemble(models, weights, test_df, audio_cfg, device):
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
    return acc, f1


def main():
    data_dir = Path("data/engine_diagnostics")
    train_df = pd.read_csv(data_dir / "train_metadata.csv")
    val_df = pd.read_csv(data_dir / "val_metadata.csv")
    test_df = pd.read_csv(data_dir / "test_metadata.csv")

    checkpoints_dir = Path("backend/checkpoints")

    # 1. Cargar o entrenar ConvNeXt-Nano
    conv_ckpt = checkpoints_dir / "car-engine-diagnostics-convnext-nano"
    if (conv_ckpt / "weights.pt").exists() and (conv_ckpt / "manifest.json").exists():
        import json
        with open(conv_ckpt / "manifest.json", "r", encoding="utf-8") as f:
            m_conv = json.load(f).get("metrics", {})
        recipe_path = Path("backend/training/recipes/car_engine_diagnostics_convnext_nano.yaml")
        with open(recipe_path, "r", encoding="utf-8") as f:
            cfg_conv = TrainingConfig.model_validate(yaml.safe_load(f))
        path_conv = conv_ckpt
        print(f"[ConvNeXt-Nano] Checkpoint existente encontrado en {path_conv}. Métricas previas: Test Acc={m_conv.get('test_accuracy', 0)*100:.2f}%, F1={m_conv.get('test_f1_macro', 0)*100:.2f}%")
    else:
        cfg_conv, path_conv, m_conv = train_model("car_engine_diagnostics_convnext_nano.yaml", train_df, val_df, test_df)

    # 2. Cargar o entrenar EfficientNet-B0
    eff_ckpt = checkpoints_dir / "car-engine-diagnostics-efficientnet-b0"
    if (eff_ckpt / "weights.pt").exists() and (eff_ckpt / "manifest.json").exists():
        import json
        with open(eff_ckpt / "manifest.json", "r", encoding="utf-8") as f:
            m_eff = json.load(f).get("metrics", {})
        recipe_path = Path("backend/training/recipes/car_engine_diagnostics_efficientnet_b0.yaml")
        with open(recipe_path, "r", encoding="utf-8") as f:
            cfg_eff = TrainingConfig.model_validate(yaml.safe_load(f))
        path_eff = eff_ckpt
        print(f"[EfficientNet-B0] Checkpoint existente encontrado en {path_eff}. Métricas previas: Test Acc={m_eff.get('test_accuracy', 0)*100:.2f}%, F1={m_eff.get('test_f1_macro', 0)*100:.2f}%")
    else:
        cfg_eff, path_eff, m_eff = train_model("car_engine_diagnostics_efficientnet_b0.yaml", train_df, val_df, test_df)

    # 0. Higiene Metodológica: Verificar Integridad Criptográfica del Test Set Congelado
    test_csv = data_dir / "test_metadata.csv"
    verify_test_set_integrity(test_csv, FROZEN_ENGINE_TEST_SHA256)
    print(f"\n[Test Guard] Integridad verificada. Hash SHA-256 congelado: {FROZEN_ENGINE_TEST_SHA256[:16]}...")

    # 3. Cargar modelos en GPU/CPU para calibración y evaluación
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    classes = sorted(train_df["clase"].unique().tolist())
    num_classes = len(classes)
    label_to_idx = {c: i for i, c in enumerate(classes)}

    print(f"\n[Carga] Cargando modelos en {device}...")
    m_resnet = BioacousticModel("resnet34d", num_classes=num_classes, pretrained=False, pool_type="gem", use_gpu_frontend=False).to(device)
    m_resnet.load_state_dict(torch.load(checkpoints_dir / "car-engine-diagnostics-resnet34d" / "weights.pt", map_location=device, weights_only=True))

    m_effnet = BioacousticModel("efficientnet_b0", num_classes=num_classes, pretrained=False, pool_type="gem", use_gpu_frontend=False).to(device)
    m_effnet.load_state_dict(torch.load(path_eff / "weights.pt", map_location=device, weights_only=True))

    frontend = GPUAudioFrontEnd(
        sample_rate=cfg_eff.audio.target_sr,
        n_fft=cfg_eff.audio.n_fft,
        hop_length=cfg_eff.audio.hop_length,
        n_mels=cfg_eff.audio.n_mels,
        f_min=cfg_eff.audio.f_min,
        f_max=cfg_eff.audio.f_max,
    ).to(device)

    # DataLoaders para Validación y Test
    val_dataset = GenericAudioDataset(val_df, audio_config=cfg_eff.audio, label_to_idx=label_to_idx, is_train=False, return_raw_waveform=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

    test_dataset = GenericAudioDataset(test_df, audio_config=cfg_eff.audio, label_to_idx=label_to_idx, is_train=False, return_raw_waveform=True)
    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)

    # 4. TUNING EXCLUSIVO EN VALIDACIÓN (Zero Test Leakage)
    print("\n" + "=" * 60)
    print("[FASE 0 - TUNING] Optimizando Temperatura y Pesos SOLO en Validación (val_df)...")
    print("=" * 60)
    calib_result = tune_ensemble_calibration(
        models=[m_resnet, m_effnet],
        val_loader=val_loader,
        frontend=frontend,
        device=device,
        classes=classes,
    )

    print(f"  Resultados en Validación:")
    print(f"  >> Val Accuracy:    {calib_result.val_accuracy*100:.2f}%")
    print(f"  >> Val Macro F1:    {calib_result.val_macro_f1*100:.2f}%")
    print(f"  >> Val ECE:         {calib_result.val_ece:.4f}")
    print(f"  >> Pesos Óptimos:   ResNet34d={calib_result.optimal_weights[0]:.2f}, EffNet-B0={calib_result.optimal_weights[1]:.2f}")
    print(f"  >> Temp Óptimas:    ResNet34d={calib_result.optimal_temperatures[0]:.2f}, EffNet-B0={calib_result.optimal_temperatures[1]:.2f}")

    # 5. EVALUACIÓN CIEGA EN TEST SET CONGELADO (Evaluación única sin re-tuning)
    print("\n" + "=" * 60)
    print("[FASE 0 - EVALUACIÓN] Evaluación Ciega en Test Set Congelado (test_df)...")
    print("=" * 60)
    test_results = evaluate_calibrated_ensemble(
        models=[m_resnet, m_effnet],
        calibration_result=calib_result,
        data_loader=test_loader,
        frontend=frontend,
        device=device,
        classes=classes,
    )

    print(f"  >> TEST ACCURACY:   {test_results['accuracy']*100:.2f}%")
    print(f"  >> TEST MACRO F1:   {test_results['macro_f1']*100:.2f}%")
    print(f"  >> TEST ECE:        {test_results['ece']:.4f}")
    print("=" * 60)

    # Guardar Recibo RDD Fase 0
    receipt_path = Path("docs/fase0_higiene_receipt.json")
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump({
            "test_sha256": FROZEN_ENGINE_TEST_SHA256,
            "test_file": str(test_csv),
            "tuning_split": "validation_only",
            "validation_metrics": {
                "val_accuracy": calib_result.val_accuracy,
                "val_macro_f1": calib_result.val_macro_f1,
                "val_ece": calib_result.val_ece,
                "optimal_weights": calib_result.optimal_weights,
                "optimal_temperatures": calib_result.optimal_temperatures,
            },
            "blind_test_metrics": {
                "test_accuracy": test_results["accuracy"],
                "test_macro_f1": test_results["macro_f1"],
                "test_ece": test_results["ece"],
            },
            "per_class_report": test_results["per_class_report"],
        }, f, indent=2)

    print(f"\n[RDD Receipt] Recibo técnico guardado exitosamente en: {receipt_path}")


if __name__ == "__main__":
    main()


