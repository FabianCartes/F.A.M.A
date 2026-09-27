"""
backend/train_car_engine_model.py
Script de entrenamiento para el modelo de diagnóstico mecánico de motores.
"""
from pathlib import Path
import yaml
import pandas as pd
from training.paths import get_project_root, get_raw_data_dir
from training.schemas.config import TrainingConfig
from training.trainers.standalone_trainer import GenericModelTrainer


def main():
    project_root = get_project_root()
    recipe_path = project_root / "backend/training/recipes/car_engine_diagnostics_resnet34d.yaml"
    with open(recipe_path, "r", encoding="utf-8") as f:
        cfg = TrainingConfig.model_validate(yaml.safe_load(f))

    data_dir = get_raw_data_dir("engine_diagnostics")
    train_df = pd.read_csv(data_dir / "train_metadata.csv")
    val_df = pd.read_csv(data_dir / "val_metadata.csv")
    test_df = pd.read_csv(data_dir / "test_metadata.csv")

    print(f"[Train] Iniciando entrenamiento con receta: {recipe_path.name}")
    print(f"[Train] Train: {len(train_df)} | Val: {len(val_df)} | Test: {len(test_df)}")
    print(f"[Train] Clases: {sorted(train_df['clase'].unique().tolist())}")

    trainer = GenericModelTrainer(config=cfg, project_root=project_root)
    bundle_path, metrics = trainer.train_and_export(
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        output_checkpoints_dir=project_root / "backend" / "checkpoints",
        verbose=True,
    )

    print("\n" + "=" * 60)
    print(f"[Train] ENTRENAMIENTO COMPLETADO EXITOSAMENTE")
    print(f"[Train] Bundle exportado en: {bundle_path}")
    print(f"[Train] Métricas Finales en Test: {metrics}")
    print("=" * 60)


if __name__ == "__main__":
    main()
