"""
backend/training/prepare_engine_data.py
Script de ingesta y particionamiento estratificado para el dataset de diagnóstico de motores.
"""
from pathlib import Path
import pandas as pd
from training.datasets.local_folder import LocalFolderPAMIngestor
from training.pipelines.split import grouped_stratified_split_dataset


def prepare_engine_dataset(source_dir: Path = Path("data/engine_diagnostics")):
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

    train_csv = source_dir / "train_metadata.csv"
    val_csv = source_dir / "val_metadata.csv"
    test_csv = source_dir / "test_metadata.csv"

    train_df.to_csv(train_csv, index=False)
    val_df.to_csv(val_csv, index=False)
    test_df.to_csv(test_csv, index=False)

    print(f"[Split] Archivos CSV guardados en {source_dir}:")
    print(f"  - {train_csv}")
    print(f"  - {val_csv}")
    print(f"  - {test_csv}")


if __name__ == "__main__":
    prepare_engine_dataset()
