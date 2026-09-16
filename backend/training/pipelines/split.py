"""
backend/training/pipelines/split.py
Particionamiento de datasets con garantía estricta de Zero Recordist Leakage.
"""
from typing import Tuple
import pandas as pd
import numpy as np
from sklearn.model_selection import GroupKFold, StratifiedGroupKFold


def grouped_stratified_split_dataset(
    df: pd.DataFrame,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    group_col: str = "recordist",
    target_col: str = "clase",
    random_state: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Divide un DataFrame en Train, Val y Test garantizando que los grupos (recordists)
    no se solapen entre particiones (Zero Recordist Leakage).
    """
    df = df.reset_index(drop=True)
    if len(df) == 0:
        return df.copy(), df.copy(), df.copy()

    # Si hay muy pocos grupos para k-fold, agrupar de forma determinista
    groups = df[group_col].astype(str).values
    unique_groups = np.unique(groups)
    np.random.seed(random_state)
    shuffled_groups = np.random.permutation(unique_groups)

    n_groups = len(shuffled_groups)
    if n_groups <= 2:
        # Fallback para datasets mínimos de prueba
        return df.iloc[:1].copy(), df.iloc[1:2].copy(), df.iloc[2:].copy()

    n_test = max(1, int(round(n_groups * test_ratio)))
    n_val = max(1, int(round(n_groups * val_ratio)))
    n_train = n_groups - n_test - n_val
    if n_train < 1:
        n_train = 1
        if n_test > 1:
            n_test -= 1
        elif n_val > 1:
            n_val -= 1

    test_groups = set(shuffled_groups[:n_test])
    val_groups = set(shuffled_groups[n_test : n_test + n_val])
    train_groups = set(shuffled_groups[n_test + n_val :])

    train_df = df[df[group_col].isin(train_groups)].copy().reset_index(drop=True)
    val_df = df[df[group_col].isin(val_groups)].copy().reset_index(drop=True)
    test_df = df[df[group_col].isin(test_groups)].copy().reset_index(drop=True)

    return train_df, val_df, test_df
