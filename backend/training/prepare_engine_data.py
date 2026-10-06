"""
backend/training/prepare_engine_data.py
Script de ingesta y particionamiento estratificado para el dataset de diagnóstico de motores.
"""
from pathlib import Path
from typing import Optional
import pandas as pd
from dataset_references import resolve_reference
from training.datasets.local_folder import LocalFolderPAMIngestor
from training.pipelines.split import grouped_stratified_split_dataset


def prepare_engine_dataset(source_dir: Optional[Path] = None, *, output_dir: Optional[Path] = None):
    """Generate NEW splits from a raw import; never convert existing membership."""
    if source_dir is None:
        source_dir = Path(__file__).absolute().parent.parent / "data/raw/engine_diagnostics"
    else:
        source_dir = Path(source_dir)
    output_dir = Path(output_dir) if output_dir is not None else source_dir
    print(f"[Ingestor] Procesando directorio: {source_dir}")
    ingestor = LocalFolderPAMIngestor(source_dir=source_dir)
    df = ingestor.ingest()
    print(f"[Ingestor] Muestras encontradas: {len(df)}")
    print("[Ingestor] Distribución de clases:\n", df["clase"].value_counts())

    train_df, val_df, test_df = grouped_stratified_split_dataset(
        df=df,
        train_ratio=0.70,
        val_ratio=0.15,
        test_ratio=0.15,
        group_col="recordist",
        target_col="clase",
        random_state=42,
    )

    print("\n[Split] Resumen de particiones:")
    print(f"  Train: {len(train_df)} muestras")
    print(f"  Val:   {len(val_df)} muestras")
    print(f"  Test:  {len(test_df)} muestras")

    # Invariantes de calidad
    assert set(test_df["clase"]) == set(df["clase"]), "Error: faltan clases en Test"
    assert set(val_df["clase"]) == set(df["clase"]), "Error: faltan clases en Val"
    assert set(train_df["clase"]) == set(df["clase"]), "Error: faltan clases en Train"

    for frame in (train_df, val_df, test_df):
        for row in frame.to_dict("records"):
            resolve_reference(row["file_path"], row["file_stage"], {"raw": source_dir})
    groups = [set(frame["recordist"]) for frame in (train_df, val_df, test_df)]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]), "Recordist leakage"
    output_dir.mkdir(parents=True, exist_ok=True)
    train_csv = output_dir / "train_metadata.csv"
    val_csv = output_dir / "val_metadata.csv"
    test_csv = output_dir / "test_metadata.csv"

    train_df.to_csv(train_csv, index=False)
    val_df.to_csv(val_csv, index=False)
    test_df.to_csv(test_csv, index=False)

    print(f"[Split] Archivos CSV guardados en {output_dir}:")
    print(f"  - {train_csv}")
    print(f"  - {val_csv}")
    print(f"  - {test_csv}")


if __name__ == "__main__":
    prepare_engine_dataset()
