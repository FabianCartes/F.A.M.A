import sys
import json
import random
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd
import torch
import matplotlib.pyplot as plt
import seaborn as sns

# Asegurar que la raíz del backend esté en sys.path
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from poc.train import train_pipeline
from poc.evaluate import run_evaluation


def aggregate_benchmark_metrics(
    runs: List[Dict[str, Any]],
    classes: List[str],
) -> Dict[str, Any]:
    """
    Agrega y calcula estadísticas (media y desviación estándar) de múltiples corridas:
    - Métricas globales: Accuracy, Precision (macro), Recall (macro), F1-Score (macro).
    - Matriz de confusión promedio y desviación estándar por celda.
    - F1-Score desglosado por clase (media y desviación).
    """
    if not runs:
        raise ValueError("La lista de corridas no puede estar vacía.")

    accs = [r["accuracy"] for r in runs]
    precs = [r["precision_macro"] for r in runs]
    recs = [r["recall_macro"] for r in runs]
    f1s = [r["f1_macro"] for r in runs]

    cms = np.array([r["confusion_matrix"] for r in runs], dtype=np.float64)
    cm_mean = np.mean(cms, axis=0)
    cm_std = np.std(cms, axis=0)

    # F1 por clase
    per_class_f1: Dict[str, Dict[str, float]] = {}
    for c in classes:
        c_f1s = []
        for r in runs:
            rep = r.get("classification_report", {})
            if c in rep and isinstance(rep[c], dict) and "f1-score" in rep[c]:
                c_f1s.append(rep[c]["f1-score"])
            else:
                c_f1s.append(0.0)
        per_class_f1[c] = {
            "mean": float(np.mean(c_f1s)),
            "std": float(np.std(c_f1s)),
        }

    return {
        "num_runs": len(runs),
        "accuracy": {"mean": float(np.mean(accs)), "std": float(np.std(accs))},
        "precision_macro": {"mean": float(np.mean(precs)), "std": float(np.std(precs))},
        "recall_macro": {"mean": float(np.mean(recs)), "std": float(np.std(recs))},
        "f1_macro": {"mean": float(np.mean(f1s)), "std": float(np.std(f1s))},
        "confusion_matrix_mean": cm_mean,
        "confusion_matrix_std": cm_std,
        "per_class_f1": per_class_f1,
        "runs": runs,
    }


def plot_benchmark_confusion_matrix(
    cm_mean: np.ndarray,
    cm_std: np.ndarray,
    classes: List[str],
    output_path: Path,
) -> None:
    """
    Grafica la matriz de confusión promedio con anotaciones de media ± desviación estándar.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generar texto de anotación por celda
    annotations = np.empty_like(cm_mean, dtype=object)
    for i in range(cm_mean.shape[0]):
        for j in range(cm_mean.shape[1]):
            m = cm_mean[i, j]
            s = cm_std[i, j]
            if s > 0.05:
                annotations[i, j] = f"{m:.1f}\n±{s:.1f}"
            else:
                annotations[i, j] = f"{m:.1f}"

    plt.figure(figsize=(13, 11))
    sns.heatmap(
        cm_mean,
        annot=annotations,
        fmt="",
        cmap="Blues",
        xticklabels=classes,
        yticklabels=classes,
        cbar=True,
        linewidths=0.5,
        linecolor="lightgray",
    )
    plt.title("Matriz de Confusión Promedio (Media ± Desv. Est.) - Benchmark F.A.M.A.", fontsize=14, pad=15)
    plt.xlabel("Clase Predicha", fontsize=12, labelpad=10)
    plt.ylabel("Clase Verdadera", fontsize=12, labelpad=10)
    plt.xticks(rotation=45, ha="right", fontsize=9)
    plt.yticks(rotation=0, fontsize=9)
    plt.tight_layout()
    plt.savefig(output_path, dpi=250)
    plt.close()


def format_benchmark_markdown_table(
    summary: Dict[str, Any],
    classes: List[str],
) -> str:
    """
    Genera un reporte en formato Markdown con tablas consolidadas del benchmark.
    """
    lines = [
        f"## Resultados Consolidados del Benchmark ({summary['num_runs']} Corridas)\n",
        r"### Métricas Globales en Conjunto de Prueba (Test Set)\n",
        r"| Métrica | Media ($\mu$) | Desviación Estándar ($\sigma$) | Rango $[\mu - \sigma, \mu + \sigma]$ |",
        "|:---|:---:|:---:|:---:|",
        f"| **Accuracy** | **{summary['accuracy']['mean'] * 100:.2f}%** | ±{summary['accuracy']['std'] * 100:.2f}% | [{max(0.0, (summary['accuracy']['mean'] - summary['accuracy']['std']) * 100):.2f}%, {min(100.0, (summary['accuracy']['mean'] + summary['accuracy']['std']) * 100):.2f}%] |",
        f"| **Precision (macro)** | **{summary['precision_macro']['mean'] * 100:.2f}%** | ±{summary['precision_macro']['std'] * 100:.2f}% | [{(summary['precision_macro']['mean'] - summary['precision_macro']['std']) * 100:.2f}%, {(summary['precision_macro']['mean'] + summary['precision_macro']['std']) * 100:.2f}%] |",
        f"| **Recall (macro)** | **{summary['recall_macro']['mean'] * 100:.2f}%** | ±{summary['recall_macro']['std'] * 100:.2f}% | [{(summary['recall_macro']['mean'] - summary['recall_macro']['std']) * 100:.2f}%, {(summary['recall_macro']['mean'] + summary['recall_macro']['std']) * 100:.2f}%] |",
        f"| **F1-Score (macro)** | **{summary['f1_macro']['mean'] * 100:.2f}%** | ±{summary['f1_macro']['std'] * 100:.2f}% | [{(summary['f1_macro']['mean'] - summary['f1_macro']['std']) * 100:.2f}%, {(summary['f1_macro']['mean'] + summary['f1_macro']['std']) * 100:.2f}%] |\n",
        "### Desglose por Corrida Individual\n",
        "| Corrida | Semilla | Accuracy | Precision (macro) | Recall (macro) | F1-Score (macro) |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for r in summary["runs"]:
        lines.append(
            f"| Run {r['run_id']:02d} | `{r['seed']}` | {r['accuracy'] * 100:.2f}% | {r['precision_macro'] * 100:.2f}% | {r['recall_macro'] * 100:.2f}% | {r['f1_macro'] * 100:.2f}% |"
        )

    lines.append("\n### F1-Score Promedio por Especie (Diagnóstico de Separabilidad)\n")
    lines.append("| Especie | F1-Score Promedio | Desviación Estándar | Diagnóstico preliminar |")
    lines.append("|:---|:---:|:---:|:---|")

    for c in classes:
        m = summary["per_class_f1"][c]["mean"] * 100
        s = summary["per_class_f1"][c]["std"] * 100
        if m >= 70:
            diag = "Alta separabilidad"
        elif m >= 45:
            diag = "Moderada / Solapamiento parcial"
        else:
            diag = "Baja / Alta confusión"
        lines.append(f"| **{c}** | {m:.2f}% | ±{s:.2f}% | {diag} |")

    return "\n".join(lines)


def run_benchmark(
    metadata_csv: Path,
    raw_dir: Path,
    test_csv: Path,
    output_dir: Path,
    num_runs: int = 10,
    epochs: int = 15,
    batch_size: int = 16,
    lr: float = 1e-3,
    workers: int = 4,
    device: Optional[str] = None,
    seeds: Optional[List[int]] = None,
    checkpoint_dir: Optional[Path] = None,
    model_type: str = "efficientnet_b0",
    loss_type: str = "focal",
    focal_gamma: float = 2.0,
    warmup_epochs: int = 3,
    n_mels: int = 128,
    use_tta: bool = True,
    tta_mode: str = "mean",
) -> Dict[str, Any]:
    """
    Ejecuta el protocolo de benchmark de múltiples entrenamientos consecutivos:
    1. Ejecuta N entrenamientos independientes variando la semilla pseudoaleatoria.
    2. Evalúa cada modelo resultante en el conjunto de prueba (test set).
    3. Agrega las métricas y calcula media y desviación estándar.
    4. Genera la matriz de confusión consolidada y el reporte en Markdown y JSON.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if checkpoint_dir is None:
        checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir = Path(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    if seeds is None:
        seeds = [100 + i * 42 for i in range(num_runs)]
    elif len(seeds) < num_runs:
        raise ValueError(f"Se proporcionaron {len(seeds)} semillas pero se solicitaron {num_runs} corridas.")

    runs: List[Dict[str, Any]] = []
    classes: Optional[List[str]] = None

    print(f"\n=======================================================")
    print(f"INICIANDO BENCHMARK DE {num_runs} ENTRENAMIENTOS CONSECUTIVOS")
    print(f"Modelo: {model_type} | Loss: {loss_type} | Mels: {n_mels}")
    print(f"=======================================================")
    print(f"Épocas por corrida: {epochs} | Batch size: {batch_size} | LR: {lr}")
    print(f"Directorio de salida: {output_dir}\n")

    for i in range(1, num_runs + 1):
        seed = seeds[i - 1]
        ckpt_name = f"benchmark_run_{i:02d}.pt"
        ckpt_path = checkpoint_dir / ckpt_name
        cm_image_path = output_dir / f"cm_run_{i:02d}.png"

        print(f"\n>>> [Corrida {i:02d}/{num_runs:02d}] - Semilla: {seed} <<<")

        train_res = train_pipeline(
            metadata_csv=metadata_csv,
            raw_dir=raw_dir,
            checkpoint_dir=checkpoint_dir,
            epochs=epochs,
            batch_size=batch_size,
            lr=lr,
            num_workers=workers,
            device=device,
            checkpoint_name=ckpt_name,
            seed=seed,
            model_type=model_type,
            loss_type=loss_type,
            focal_gamma=focal_gamma,
            warmup_epochs=warmup_epochs,
            n_mels=n_mels,
        )

        eval_res = run_evaluation(
            checkpoint_path=ckpt_path,
            test_csv=test_csv,
            raw_dir=raw_dir,
            output_image_path=cm_image_path,
            device=device,
            use_tta=use_tta,
            tta_mode=tta_mode,
        )

        if classes is None:
            classes = train_res.get("classes") or [k for k in eval_res["classification_report"].keys() if k not in ("accuracy", "macro avg", "weighted avg")]

        run_entry = {
            "run_id": i,
            "seed": seed,
            "accuracy": eval_res["accuracy"],
            "precision_macro": eval_res["precision_macro"],
            "recall_macro": eval_res["recall_macro"],
            "f1_macro": eval_res["f1_macro"],
            "confusion_matrix": eval_res["confusion_matrix"],
            "classification_report": eval_res["classification_report"],
        }
        runs.append(run_entry)

    summary = aggregate_benchmark_metrics(runs, classes)

    # Exportar matriz de confusión consolidada
    consolidated_cm_path = output_dir / "benchmark_confusion_matrix.png"
    plot_benchmark_confusion_matrix(
        summary["confusion_matrix_mean"],
        summary["confusion_matrix_std"],
        classes,
        consolidated_cm_path,
    )

    # Exportar reporte en Markdown
    report_md_path = output_dir / "benchmark_report.md"
    markdown_content = format_benchmark_markdown_table(summary, classes)
    report_md_path.write_text(markdown_content, encoding="utf-8")

    # Exportar resumen en JSON
    json_summary = {
        "num_runs": summary["num_runs"],
        "accuracy": summary["accuracy"],
        "precision_macro": summary["precision_macro"],
        "recall_macro": summary["recall_macro"],
        "f1_macro": summary["f1_macro"],
        "per_class_f1": summary["per_class_f1"],
        "confusion_matrix_mean": summary["confusion_matrix_mean"].tolist(),
        "confusion_matrix_std": summary["confusion_matrix_std"].tolist(),
        "runs": [
            {
                "run_id": r["run_id"],
                "seed": r["seed"],
                "accuracy": r["accuracy"],
                "precision_macro": r["precision_macro"],
                "recall_macro": r["recall_macro"],
                "f1_macro": r["f1_macro"],
            }
            for r in runs
        ],
    }
    json_path = output_dir / "benchmark_summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_summary, f, indent=2)

    print("\n" + markdown_content)
    print(f"\nReporte guardado en: {report_md_path}")
    print(f"Matriz consolidada guardada en: {consolidated_cm_path}")
    print(f"JSON resumen guardado en: {json_path}\n")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ejecutar benchmark de N entrenamientos para PoC Bioacústica F.A.M.A.")
    parser.add_argument("--runs", type=int, default=10, help="Cantidad de entrenamientos consecutivos (default: 10)")
    parser.add_argument("--epochs", type=int, default=15, help="Número de épocas por corrida (default: 15)")
    parser.add_argument("--batch-size", type=int, default=16, help="Tamaño del lote (default: 16)")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate (default: 1e-3)")
    parser.add_argument("--workers", type=int, default=4, help="Workers DataLoader (default: 4)")
    parser.add_argument("--device", type=str, default=None, help="Dispositivo (cuda o cpu)")
    parser.add_argument("--output-dir", type=str, default="benchmarks", help="Directorio para guardar resultados")
    parser.add_argument("--model-type", type=str, default="efficientnet_b0", help="Arquitectura del modelo (efficientnet_b0 o audiocnn)")
    parser.add_argument("--loss-type", type=str, default="focal", help="Función de pérdida (focal o ce)")
    parser.add_argument("--gamma", type=float, default=2.0, help="Parámetro gamma de Focal Loss")
    parser.add_argument("--warmup-epochs", type=int, default=3, help="Épocas de warmup para EfficientNet")
    parser.add_argument("--n-mels", type=int, default=128, help="Cantidad de bandas Mel")
    parser.add_argument("--no-tta", action="store_true", default=False, help="Deshabilitar TTA en evaluación de benchmark")
    parser.add_argument("--tta-mode", type=str, default="mean", choices=["mean", "max"], help="Estrategia TTA (mean o max, default: mean)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    repo_root = project_root if (project_root / "data").exists() else project_root.parent

    out_path = Path(args.output_dir)
    if not out_path.is_absolute():
        out_path = repo_root / out_path

    run_benchmark(
        metadata_csv=repo_root / "data" / "metadata.csv",
        raw_dir=repo_root / "data" / "raw",
        test_csv=repo_root / "data" / "test.csv",
        output_dir=out_path,
        num_runs=args.runs,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        workers=args.workers,
        device=args.device,
        model_type=args.model_type,
        loss_type=args.loss_type,
        focal_gamma=args.gamma,
        warmup_epochs=args.warmup_epochs,
        n_mels=args.n_mels,
        use_tta=not args.no_tta,
        tta_mode=args.tta_mode,
    )

