import pytest
import numpy as np
from pathlib import Path
from poc.benchmark import aggregate_benchmark_metrics

def test_aggregate_benchmark_metrics():
    classes = ["ClaseA", "ClaseB"]
    runs = [
        {
            "run_id": 1,
            "seed": 42,
            "accuracy": 0.50,
            "precision_macro": 0.60,
            "recall_macro": 0.50,
            "f1_macro": 0.54,
            "confusion_matrix": [[2, 1], [0, 3]],
            "classification_report": {
                "ClaseA": {"f1-score": 0.60},
                "ClaseB": {"f1-score": 0.48},
            },
        },
        {
            "run_id": 2,
            "seed": 43,
            "accuracy": 0.60,
            "precision_macro": 0.70,
            "recall_macro": 0.60,
            "f1_macro": 0.64,
            "confusion_matrix": [[3, 0], [1, 2]],
            "classification_report": {
                "ClaseA": {"f1-score": 0.70},
                "ClaseB": {"f1-score": 0.58},
            },
        },
    ]

    summary = aggregate_benchmark_metrics(runs, classes)

    assert "accuracy" in summary
    assert np.isclose(summary["accuracy"]["mean"], 0.55)
    assert np.isclose(summary["accuracy"]["std"], 0.05)

    assert "f1_macro" in summary
    assert np.isclose(summary["f1_macro"]["mean"], 0.59)
    assert np.isclose(summary["f1_macro"]["std"], 0.05)

    assert "confusion_matrix_mean" in summary
    expected_cm_mean = np.array([[2.5, 0.5], [0.5, 2.5]])
    np.testing.assert_allclose(summary["confusion_matrix_mean"], expected_cm_mean)

    assert "per_class_f1" in summary
    assert np.isclose(summary["per_class_f1"]["ClaseA"]["mean"], 0.65)
    assert np.isclose(summary["per_class_f1"]["ClaseB"]["mean"], 0.53)


def test_plot_benchmark_confusion_matrix(tmp_path):
    from poc.benchmark import plot_benchmark_confusion_matrix
    classes = ["ClaseA", "ClaseB"]
    cm_mean = np.array([[2.5, 0.5], [0.5, 2.5]])
    cm_std = np.array([[0.5, 0.5], [0.5, 0.5]])
    out_img = tmp_path / "test_benchmark_cm.png"

    plot_benchmark_confusion_matrix(cm_mean, cm_std, classes, out_img)
    assert out_img.exists()
    assert out_img.stat().st_size > 0


def test_format_benchmark_markdown_table():
    from poc.benchmark import format_benchmark_markdown_table
    classes = ["ClaseA", "ClaseB"]
    runs = [
        {
            "run_id": 1,
            "seed": 42,
            "accuracy": 0.50,
            "precision_macro": 0.60,
            "recall_macro": 0.50,
            "f1_macro": 0.54,
            "confusion_matrix": [[2, 1], [0, 3]],
            "classification_report": {
                "ClaseA": {"f1-score": 0.60},
                "ClaseB": {"f1-score": 0.48},
            },
        },
    ]
    summary = aggregate_benchmark_metrics(runs, classes)
    md = format_benchmark_markdown_table(summary, classes)

    assert "## Resultados Consolidados del Benchmark" in md
    assert "Accuracy" in md
    assert "F1-Score (macro)" in md
    assert "ClaseA" in md


def test_run_benchmark(tmp_path, monkeypatch):
    from poc.benchmark import run_benchmark

    fake_train_history = {"history": {}, "classes": ["A", "B"]}
    fake_eval_results = {
        "accuracy": 0.60,
        "precision_macro": 0.60,
        "recall_macro": 0.60,
        "f1_macro": 0.60,
        "confusion_matrix": [[3, 0], [1, 2]],
        "classification_report": {"A": {"f1-score": 0.70}, "B": {"f1-score": 0.50}},
        "confusion_matrix_path": str(tmp_path / "cm.png"),
    }

    monkeypatch.setattr("poc.benchmark.train_pipeline", lambda **kwargs: fake_train_history)
    monkeypatch.setattr("poc.benchmark.run_evaluation", lambda **kwargs: fake_eval_results)

    # Crear archivos falsos requeridos
    meta_csv = tmp_path / "metadata.csv"
    meta_csv.write_text("dummy")
    test_csv = tmp_path / "test.csv"
    test_csv.write_text("dummy")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    summary = run_benchmark(
        metadata_csv=meta_csv,
        raw_dir=raw_dir,
        test_csv=test_csv,
        output_dir=tmp_path / "benchmark_out",
        num_runs=2,
        epochs=1,
        seeds=[10, 20],
    )

    assert summary["num_runs"] == 2
    assert (tmp_path / "benchmark_out" / "benchmark_summary.json").exists()
    assert (tmp_path / "benchmark_out" / "benchmark_confusion_matrix.png").exists()
    assert (tmp_path / "benchmark_out" / "benchmark_report.md").exists()

