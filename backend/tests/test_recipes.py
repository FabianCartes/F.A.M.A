from pathlib import Path
import yaml
import pytest

from training.paths import get_project_root, get_raw_data_dir
from training.schemas.config import TrainingConfig


def test_car_engine_recipes_use_ssot_raw_data_dir():
    recipes_dir = get_project_root() / "backend" / "training" / "recipes"
    recipe_files = list(recipes_dir.glob("car_engine_*.yaml"))
    assert len(recipe_files) > 0, "No se encontraron recetas car_engine_*.yaml"

    expected_raw_dir = "backend/data/raw/engine_diagnostics"
    expected_metadata_csv = "backend/data/raw/engine_diagnostics/train_metadata.csv"

    for recipe_file in recipe_files:
        with open(recipe_file, "r", encoding="utf-8") as f:
            raw_yaml = yaml.safe_load(f)

        assert "dataset" in raw_yaml, f"Receta {recipe_file.name} no contiene bloque 'dataset'"
        assert raw_yaml["dataset"]["raw_dir"] == expected_raw_dir, (
            f"Receta {recipe_file.name} tiene raw_dir={raw_yaml['dataset']['raw_dir']}, se esperaba {expected_raw_dir}"
        )
        assert raw_yaml["dataset"]["metadata_csv"] == expected_metadata_csv, (
            f"Receta {recipe_file.name} tiene metadata_csv={raw_yaml['dataset']['metadata_csv']}, se esperaba {expected_metadata_csv}"
        )

        # Validar además que el schema Pydantic resuelva las rutas canónicas absolutas
        cfg = TrainingConfig.model_validate(raw_yaml)
        assert cfg.dataset.raw_dir == get_raw_data_dir("engine_diagnostics")
        assert cfg.dataset.metadata_csv == get_raw_data_dir("engine_diagnostics") / "train_metadata.csv"
