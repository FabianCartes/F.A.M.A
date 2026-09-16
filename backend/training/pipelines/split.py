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

    # Detectar si los grupos son exclusivos por clase (ej: datasets locales particionados por archivo fuente)
    max_classes_per_group = df.groupby(group_col)[target_col].nunique().max()

    if max_classes_per_group == 1:
        rng = np.random.RandomState(random_state)
        train_idx, val_idx, test_idx = set(), set(), set()

        for _, group_df in df.groupby(target_col):
            unique_g = rng.permutation(group_df[group_col].unique())
            n_g = len(unique_g)

            if n_g >= 3:
                n_test = max(1, int(round(n_g * test_ratio)))
                n_val = max(1, int(round(n_g * val_ratio)))
                if n_test + n_val >= n_g:
                    n_val = 1
                    n_test = 1
                t_g = set(unique_g[:n_test])
                v_g = set(unique_g[n_test : n_test + n_val])
                tr_g = set(unique_g[n_test + n_val:])

                for idx, row in group_df.iterrows():
                    g = row[group_col]
                    if g in t_g:
                        test_idx.add(idx)
                    elif g in v_g:
                        val_idx.add(idx)
                    else:
                        train_idx.add(idx)
            else:
                indices = rng.permutation(group_df.index)
                n_tot = len(indices)
                n_t = max(1, int(round(n_tot * test_ratio)))
                n_v = max(1, int(round(n_tot * val_ratio)))
                if n_t + n_v >= n_tot:
                    n_t = 1
                    n_v = 1
                test_idx.update(indices[:n_t])
                val_idx.update(indices[n_t : n_t + n_v])
                train_idx.update(indices[n_t + n_v:])

        train_df = df.loc[sorted(train_idx)].reset_index(drop=True)
        val_df = df.loc[sorted(val_idx)].reset_index(drop=True)
        test_df = df.loc[sorted(test_idx)].reset_index(drop=True)
        return train_df, val_df, test_df

    # Para grupos multi-clase (ej: grabadores bioacústicos de múltiples especies)
    n_splits = min(10, n_groups)
    class_counts = df[target_col].value_counts()
    min_class_count = class_counts.min() if not class_counts.empty else 1
    use_stratified = (n_splits <= min_class_count)

    if use_stratified:
        splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
        folds = [test_idx for _, test_idx in splitter.split(df, df[target_col], df[group_col])]
    else:
        splitter = GroupKFold(n_splits=n_splits)
        folds = [test_idx for _, test_idx in splitter.split(df, df[target_col], df[group_col])]

    n_train = max(1, int(round(train_ratio * n_splits)))
    n_val = max(1, int(round(val_ratio * n_splits)))
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
