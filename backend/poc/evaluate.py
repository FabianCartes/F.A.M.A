import sys
from pathlib import Path

# Asegurar que la raíz del proyecto esté en sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from typing import List, Dict, Any, Optional
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


def evaluate_test_set(
    model: nn.Module,
    test_loader: DataLoader,
    classes: List[str],
    output_image_path: Path,
    device: Optional[torch.device] = None,
) -> Dict[str, Any]:
    """Evalúa un modelo sobre el test loader y genera métricas + visualización."""
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model.eval()
    all_preds = []
    all_targets = []

    with torch.no_grad():
        for x_batch, y_batch in test_loader:
            x_batch = x_batch.to(device)
            outputs = model(x_batch)
            _, preds = torch.max(outputs, 1)

            all_preds.extend(preds.cpu().numpy().tolist())
            all_targets.extend(y_batch.cpu().numpy().tolist())

    y_true = np.array(all_targets)
    y_pred = np.array(all_preds)

    return compute_metrics_and_matrix(y_true, y_pred, classes, output_image_path)


def run_evaluation(
    checkpoint_path: Path,
    test_csv: Path,
    raw_dir: Path,
    output_image_path: Path,
    device: Optional[str] = None,
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

    model = AudioCNN(num_classes=len(classes))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device_obj)
    model.eval()

    test_df = pd.read_csv(test_csv)
    print(f"Cargando {len(test_df)} muestras del conjunto de prueba: {test_csv}")

    test_ds = AudioDataset(test_df, raw_dir, label_to_idx)
    test_loader = DataLoader(test_ds, batch_size=16, shuffle=False)

    results = evaluate_test_set(
        model=model,
        test_loader=test_loader,
        classes=classes,
        output_image_path=output_image_path,
        device=device_obj,
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
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent

    # Seleccionar checkpoint por defecto: preferir augmented_best.pt si existe
    if args.checkpoint:
        ckpt_path = project_root / "checkpoints" / args.checkpoint
        out_name = args.output or f"confusion_matrix_{Path(args.checkpoint).stem}.png"
    elif (project_root / "checkpoints" / "augmented_best.pt").exists():
        ckpt_path = project_root / "checkpoints" / "augmented_best.pt"
        out_name = args.output or "confusion_matrix_augmented.png"
    else:
        ckpt_path = project_root / "checkpoints" / "baseline_best.pt"
        out_name = args.output or "confusion_matrix.png"

    run_evaluation(
        checkpoint_path=ckpt_path,
        test_csv=project_root / "data" / "test.csv",
        raw_dir=project_root / "data" / "raw",
        output_image_path=project_root / "poc" / out_name,
    )
