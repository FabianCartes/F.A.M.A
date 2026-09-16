"""
backend/training/pipelines/split.py
Particionamiento de datasets con garantía estricta de Zero Recordist Leakage y estratificación por clase.
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
    no se solapen entre particiones (Zero Recordist Leakage) y preservando el balance de clases.
    """
    df = df.reset_index(drop=True)
    if len(df) == 0:
        return df.copy(), df.copy(), df.copy()

    n_samples = len(df)
    n_groups = df[group_col].nunique()

    # Si hay menos de 3 grupos, fallback determinista
    if n_groups < 3:
        n_train = max(1, int(round(train_ratio * n_samples)))
        train_df = df.iloc[:n_train].copy().reset_index(drop=True)
        rem = df.iloc[n_train:]
        n_val = max(1, len(rem) // 2) if len(rem) > 1 else len(rem)
        val_df = rem.iloc[:n_val].copy().reset_index(drop=True)
        test_df = rem.iloc[n_val:].copy().reset_index(drop=True)
        return train_df, val_df, test_df

    # Número de folds: 20 permite resolución fina para 70% / 15% / 15%
    n_splits = min(20, n_groups)

    class_counts = df[target_col].value_counts()
    min_class_count = class_counts.min() if not class_counts.empty else 1

    # Utilizar StratifiedGroupKFold si cada clase tiene al menos n_splits muestras
    use_stratified = (n_splits <= min_class_count)

    if use_stratified:
        splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
        folds = [test_idx for _, test_idx in splitter.split(df, df[target_col], df[group_col])]
    else:
        actual_splits = min(n_splits, n_groups)
        if actual_splits < 3:
            shuffled_groups = pd.Series(df[group_col].unique()).sample(frac=1.0, random_state=random_state).tolist()
            g_train = set(shuffled_groups[:max(1, int(round(train_ratio * len(shuffled_groups))))])
            rem = [g for g in shuffled_groups if g not in g_train]
            g_val = set(rem[:max(1, len(rem) // 2)]) if rem else set()
            g_test = set([g for g in rem if g not in g_val])

            train_df = df[df[group_col].isin(g_train)].copy().reset_index(drop=True)
            val_df = df[df[group_col].isin(g_val)].copy().reset_index(drop=True)
            test_df = df[df[group_col].isin(g_test)].copy().reset_index(drop=True)
            return train_df, val_df, test_df

        splitter = GroupKFold(n_splits=actual_splits)
        folds = [test_idx for _, test_idx in splitter.split(df, df[target_col], df[group_col])]
        n_splits = actual_splits

    n_train = int(round(train_ratio * n_splits))
    n_val = int(round(val_ratio * n_splits))
    if n_val == 0:
        n_val = 1
    if n_train + n_val >= n_splits:
        n_train = max(1, n_splits - 2)
        n_val = 1

    train_idx = np.concatenate(folds[:n_train])
    val_idx = np.concatenate(folds[n_train : n_train + n_val])
    test_idx = np.concatenate(folds[n_train + n_val :])

    train_df = df.iloc[train_idx].copy().reset_index(drop=True)
    val_df = df.iloc[val_idx].copy().reset_index(drop=True)
    test_df = df.iloc[test_idx].copy().reset_index(drop=True)

    return train_df, val_df, test_df
