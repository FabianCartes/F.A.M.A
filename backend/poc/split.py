"""Adaptador PoC de la partición canónica por grupos."""
from typing import Tuple

import pandas as pd
from training.pipelines.split import grouped_stratified_split_dataset


def grouped_stratified_split(
    df: pd.DataFrame,
    group_col: str = "recordist",
    target_col: str = "clase",
    train_size: float = 0.70,
    val_size: float = 0.15,
    test_size: float = 0.15,
    random_state: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Conserva argumentos PoC; aplica validación y cobertura canónicas."""
    return grouped_stratified_split_dataset(
        df=df, train_ratio=train_size, val_ratio=val_size, test_ratio=test_size,
        group_col=group_col, target_col=target_col, random_state=random_state,
    )
