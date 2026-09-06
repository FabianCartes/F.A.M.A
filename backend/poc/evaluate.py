import sys
from pathlib import Path

# Asegurar que la raíz del proyecto esté en sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from typing import List, Dict, Any, Optional, Tuple, Union
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix,
    classification_report,
)
import matplotlib.pyplot as plt
import seaborn as sns

from poc.train import AudioCNN, AudioDataset
from poc.preprocess import (
    extract_active_windows,
    extract_mel_spectrogram,
    GPUAudioFrontEnd,
    TARGET_SR,
    DURATION_SECONDS,
)



def compute_metrics_and_matrix(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    classes: List[str],
    output_image_path: Path,
) -> Dict[str, Any]:
    """Calcula métricas de clasificación y guarda la matriz de confusión como imagen."""
    output_image_path = Path(output_image_path)
    output_image_path.parent.mkdir(parents=True, exist_ok=True)

    acc = accuracy_score(y_true, y_pred)
    prec, rec, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="macro", zero_division=0
    )
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(classes))))
    report_dict = classification_report(
        y_true, y_pred, target_names=classes, output_dict=True, zero_division=0
    )

    # Renderizado estético de la matriz de confusión
    plt.figure(figsize=(11, 9))
    sns.set_theme(style="white")
    ax = sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=classes,
        yticklabels=classes,
        cbar=True,
        linewidths=0.5,
        linecolor="lightgray",
    )
    plt.title("Matriz de Confusión - PoC Bioacústica F.A.M.A.", fontsize=14, pad=15)
    plt.xlabel("Clase Predicha", fontsize=12, labelpad=10)
    plt.ylabel("Clase Verdadera", fontsize=12, labelpad=10)
    plt.xticks(rotation=45, ha="right", fontsize=9)
    plt.yticks(rotation=0, fontsize=9)
    plt.tight_layout()
    plt.savefig(output_image_path, dpi=250)
    plt.close()

    return {
        "accuracy": float(acc),
        "precision_macro": float(prec),
        "recall_macro": float(rec),
        "f1_macro": float(f1),
        "confusion_matrix": cm.tolist(),
        "classification_report": report_dict,
        "confusion_matrix_path": str(output_image_path),
    }


def predict_audio_tta(
    model: nn.Module,
    audio_input: Union[str, Path, np.ndarray, torch.Tensor],
    n_mels: int = 128,
    mode: str = "mean",
    device: Optional[torch.device] = None,
    target_sr: int = TARGET_SR,
    duration_seconds: float = DURATION_SECONDS,
    hop_seconds: float = 2.5,
    top_db: float = 25.0,
) -> Tuple[int, torch.Tensor]:
    """
    Ejecuta Test-Time Augmentation (TTA) multi-crop para una grabación de audio:
    1. Extrae todas las N ventanas activas de longitud duration_seconds (con zero-padding si < duration_seconds).
    2. Convierte las N ventanas en espectrogramas Mel normalizados en un único lote [N, 1, n_mels, time_steps].
    3. Infiere las N ventanas en paralelo en GPU/CPU con el modelo.
    4. Aplica softmax sobre los logits y agrega las probabilidades con 'mean' o 'max'.
    5. Retorna (clase_predicha_idx, probabilidades_agregadas).
    """
    if mode not in ("mean", "max"):
        raise ValueError(f"Modo TTA no soportado: '{mode}'. Opciones válidas: 'mean', 'max'.")

    if device is None:
        try:
            device = next(model.parameters()).device
        except StopIteration:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    windows = None
    if isinstance(audio_input, (str, Path)):
        file_path = Path(audio_input)
        if not file_path.exists():
            target_samples = int(target_sr * duration_seconds)
            windows = [np.zeros(target_samples, dtype=np.float32)]
        else:
            windows = extract_active_windows(
                file_path,
                target_sr=target_sr,
                duration_seconds=duration_seconds,
                hop_seconds=hop_seconds,
                top_db=top_db,
            )
    elif isinstance(audio_input, np.ndarray):
        windows = extract_active_windows(
            audio_input,
            target_sr=target_sr,
            duration_seconds=duration_seconds,
            hop_seconds=hop_seconds,
            top_db=top_db,
        )
    elif isinstance(audio_input, torch.Tensor):
        if audio_input.ndim == 1:
            windows = extract_active_windows(
                audio_input.detach().cpu().numpy(),
                target_sr=target_sr,
                duration_seconds=duration_seconds,
                hop_seconds=hop_seconds,
                top_db=top_db,
            )
        elif audio_input.ndim == 4:
            batch_tensor = audio_input.to(device)
            windows = None
        else:
            raise ValueError(f"Dimensión de tensor no soportada para TTA: {audio_input.shape}")
    else:
        raise TypeError(f"Tipo de entrada no soportado: {type(audio_input)}")

    if windows is not None:
        if not windows:
            target_samples = int(target_sr * duration_seconds)
            windows = [np.zeros(target_samples, dtype=np.float32)]

        wav_batch = torch.from_numpy(np.stack(windows, axis=0)).float().to(device)
        frontend = GPUAudioFrontEnd(n_mels=n_mels, normalize=True).to(device)
        batch_tensor = frontend(wav_batch)

    model.eval()
    with torch.no_grad():
        logits = model(batch_tensor)  # [N, num_classes]
        probs = torch.softmax(logits, dim=-1)  # [N, num_classes]

        if mode == "mean":
            aggregated_probs = torch.mean(probs, dim=0)  # [num_classes]
        else:
            aggregated_probs = torch.max(probs, dim=0).values  # [num_classes]

        pred_idx = int(torch.argmax(aggregated_probs).item())

    return pred_idx, aggregated_probs


def evaluate_test_set(
    model: nn.Module,
    test_loader: DataLoader,
    classes: List[str],
    output_image_path: Path,
    device: Optional[torch.device] = None,
    use_tta: bool = False,
    tta_mode: str = "mean",
    n_mels: int = 128,
) -> Dict[str, Any]:
    """Evalúa un modelo sobre el test loader (o vía TTA por archivo) y genera métricas + visualización."""
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model.eval()
    all_preds = []
    all_targets = []

    if not use_tta:
        frontend = GPUAudioFrontEnd(n_mels=n_mels, normalize=True).to(device)
        with torch.no_grad():
            for x_batch, y_batch in test_loader:
                x_batch = x_batch.to(device)
                if x_batch.ndim <= 2 or (x_batch.ndim == 3 and x_batch.shape[1] == 1):
                    x_batch = frontend(x_batch)
                outputs = model(x_batch)
                _, preds = torch.max(outputs, 1)

                all_preds.extend(preds.cpu().numpy().tolist())
                all_targets.extend(y_batch.cpu().numpy().tolist())
    else:
        dataset = test_loader.dataset
        if hasattr(dataset, "df"):
            for idx in range(len(dataset)):
                row = dataset.df.iloc[idx]
                file_path = dataset._resolve_file_path(row)
                label_str = str(row["clase"])
                label_idx = dataset.label_to_idx.get(label_str, 0)

                pred_idx, _ = predict_audio_tta(
                    model=model,
                    audio_input=file_path,
                    n_mels=n_mels,
                    mode=tta_mode,
                    device=device,
                )
                all_preds.append(pred_idx)
                all_targets.append(label_idx)
        else:
            for idx in range(len(dataset)):
                sample = dataset[idx]
                x_val, y_val = sample[0], sample[1]
                x_input = x_val.unsqueeze(0) if x_val.ndim == 3 else x_val
                pred_idx, _ = predict_audio_tta(
                    model=model,
                    audio_input=x_input,
                    n_mels=n_mels,
                    mode=tta_mode,
                    device=device,
                )
                all_preds.append(pred_idx)
                all_targets.append(int(y_val.item()) if hasattr(y_val, "item") else int(y_val))

    y_true = np.array(all_targets)
    y_pred = np.array(all_preds)

    return compute_metrics_and_matrix(y_true, y_pred, classes, output_image_path)


def run_evaluation(
    checkpoint_path: Path,
    test_csv: Path,
    raw_dir: Path,
    output_image_path: Path,
    device: Optional[str] = None,
    use_tta: bool = True,
    tta_mode: str = "mean",
) -> Dict[str, Any]:
    """Carga el mejor checkpoint y ejecuta la evaluación oficial en el conjunto de prueba."""
    if device is None:
        device_obj = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device_obj = torch.device(device)

    print(f"\nCargando checkpoint: {checkpoint_path}")
    checkpoint = torch.load(checkpoint_path, map_location=device_obj)

    classes = checkpoint["classes"]
    label_to_idx = checkpoint["label_to_idx"]
    model_type = checkpoint.get("model_type", "audiocnn")
    n_mels = checkpoint.get("n_mels", 64)

    if str(model_type).lower().startswith("efficientnet"):
        from poc.train import BioacousticEfficientNet
        model = BioacousticEfficientNet(
            model_name=model_type,
            num_classes=len(classes),
            pretrained=False,
        )
    else:
        model = AudioCNN(num_classes=len(classes))

    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device_obj)
    model.eval()

    test_df = pd.read_csv(test_csv)
    print(f"Cargando {len(test_df)} muestras del conjunto de prueba: {test_csv} (Modelo: {model_type}, n_mels: {n_mels})")
    if use_tta:
        print(f"Estrategia de inferencia: Test-Time Augmentation (TTA) activado [Modo: {tta_mode}]")
    else:
        print("Estrategia de inferencia: Estándar (Single-Crop sin TTA)")

    test_ds = AudioDataset(test_df, raw_dir, label_to_idx, n_mels=n_mels, return_raw_waveform=True)
    test_loader = DataLoader(test_ds, batch_size=16, shuffle=False)

    results = evaluate_test_set(
        model=model,
        test_loader=test_loader,
        classes=classes,
        output_image_path=output_image_path,
        device=device_obj,
        use_tta=use_tta,
        tta_mode=tta_mode,
        n_mels=n_mels,
    )

    print(f"\n=======================================================")
    print(f"RESULTADOS FINALES EN CONJUNTO DE PRUEBA (TEST SET)")
    print(f"=======================================================")
    print(f"Accuracy Final:     {results['accuracy'] * 100:.2f}%")
    print(f"Precision (macro): {results['precision_macro'] * 100:.2f}%")
    print(f"Recall (macro):    {results['recall_macro'] * 100:.2f}%")
    print(f"F1-Score (macro):  {results['f1_macro'] * 100:.2f}%")
    print(f"Matriz guardada en: {output_image_path}")
    print(f"=======================================================\n")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluar modelo F.A.M.A. en Test Set")
    parser.add_argument("--checkpoint", type=str, default=None, help="Nombre del checkpoint (.pt)")
    parser.add_argument("--output", type=str, default=None, help="Nombre de la imagen de salida (.png)")
    parser.add_argument("--no-tta", action="store_true", default=False, help="Deshabilitar Test-Time Augmentation (TTA)")
    parser.add_argument("--use-tta", action="store_true", default=None, help="Habilitar Test-Time Augmentation (TTA) [activado por defecto]")
    parser.add_argument(
        "--tta-mode",
        type=str,
        default="mean",
        choices=["mean", "max"],
        help="Estrategia de agregación para TTA (mean o max, default: mean)",
    )
    args = parser.parse_args()

    use_tta = False if args.no_tta else (args.use_tta if args.use_tta is not None else True)

    project_root = Path(__file__).resolve().parent.parent
    repo_root = project_root if (project_root / "data").exists() else project_root.parent

    # Seleccionar checkpoint por defecto: preferir augmented_best.pt si existe
    ckpt_dir = repo_root / "checkpoints"
    suffix = f"_tta_{args.tta_mode}" if use_tta else ""
    if args.checkpoint:
        ckpt_path = ckpt_dir / args.checkpoint
        out_name = args.output or f"confusion_matrix_{Path(args.checkpoint).stem}{suffix}.png"
    elif (ckpt_dir / "augmented_best.pt").exists():
        ckpt_path = ckpt_dir / "augmented_best.pt"
        out_name = args.output or f"confusion_matrix_augmented{suffix}.png"
    else:
        ckpt_path = ckpt_dir / "baseline_best.pt"
        out_name = args.output or f"confusion_matrix{suffix}.png"

    run_evaluation(
        checkpoint_path=ckpt_path,
        test_csv=repo_root / "data" / "test.csv",
        raw_dir=repo_root / "data" / "raw",
        output_image_path=project_root / "poc" / out_name,
        use_tta=use_tta,
        tta_mode=args.tta_mode,
    )

