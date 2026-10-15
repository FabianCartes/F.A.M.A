import sys
from pathlib import Path
from typing import Dict, List, Any
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Asegurar que la raíz del backend esté en sys.path
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))



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
