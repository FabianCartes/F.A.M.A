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

    bindings = []
    def fake_train(**kwargs):
        bindings.append(kwargs["roots"])
        return fake_train_history
    def fake_evaluate(**kwargs):
        bindings.append(kwargs["roots"])
        return fake_eval_results
    monkeypatch.setattr("poc.benchmark.train_pipeline", fake_train)
    monkeypatch.setattr("poc.benchmark.run_evaluation", fake_evaluate)

    # Crear archivos falsos requeridos
    meta_csv = tmp_path / "metadata.csv"
    meta_csv.write_text("dummy")
    from training.prepare_data import prepare_dataset
    import pandas as pd
    import soundfile as sf
    prepared = tmp_path / "prepared"
    monkeypatch.setattr("poc.train.get_prepared_data_dir", lambda name: prepared)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    roots = {"raw": raw_dir, "processed": processed}
    rows = []
    for i in range(20):
        sf.write(processed / f"{i}.wav", np.zeros(800), 8000)
        rows.append({"file_path": f"{i}.wav", "file_stage": "processed", "clase": "A",
                     "recordist": str(i), "xc_id": str(i)})
    pd.DataFrame(rows).to_csv(meta_csv, index=False)
    prepare_dataset(meta_csv, roots=roots, dataset_name="AvesChilenas", output_dir=prepared)

    summary = run_benchmark(
        dataset_name="AvesChilenas",
        metadata_csv=meta_csv,
        raw_dir=raw_dir,
        test_csv=None,
        output_dir=tmp_path / "benchmark_out",
        roots=roots,
        num_runs=2,
        epochs=1,
        seeds=[10, 20],
    )

    assert summary["num_runs"] == 2
    assert len(bindings) == 4
    assert all(binding == roots for binding in bindings)
    assert all(binding is bindings[0] for binding in bindings)
    assert bindings[0] is not roots
    assert (tmp_path / "benchmark_out" / "benchmark_summary.json").exists()
    assert (tmp_path / "benchmark_out" / "benchmark_confusion_matrix.png").exists()
    assert (tmp_path / "benchmark_out" / "benchmark_report.md").exists()

