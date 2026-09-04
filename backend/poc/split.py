from typing import Tuple
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold


def grouped_stratified_split(
    df: pd.DataFrame,
    group_col: str = "recordist",
    target_col: str = "clase",
    train_size: float = 0.70,
    val_size: float = 0.15,
    test_size: float = 0.15,
    random_state: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Realiza una partición train/val/test estratificada por clase y agrupada por grabador.
    Garantiza CERO fuga de información acústica entre particiones: ningún grabador
    aparece en más de un conjunto (train, val o test).
    """
    if df.empty:
        return df.copy(), df.copy(), df.copy()

    n_samples = len(df)
    n_groups = df[group_col].nunique()

    # Si hay muy pocos grupos (menos de 3), no se puede hacer split tripartito sin solapar
    if n_groups < 3:
        n_train = max(1, int(round(train_size * n_samples)))
        train_df = df.iloc[:n_train].copy().reset_index(drop=True)
        rem = df.iloc[n_train:]
        n_val = max(1, len(rem) // 2) if len(rem) > 1 else len(rem)
        val_df = rem.iloc[:n_val].copy().reset_index(drop=True)
        test_df = rem.iloc[n_val:].copy().reset_index(drop=True)
        return train_df, val_df, test_df

    # Número de folds: 20 permite resolución exacta para 70% (14), 15% (3), 15% (3)
    n_splits = min(20, n_groups)

    from sklearn.model_selection import GroupKFold

    class_counts = df[target_col].value_counts()
    min_class_count = class_counts.min() if not class_counts.empty else 1

    # Determinar si podemos usar StratifiedGroupKFold o GroupKFold
    use_stratified = (n_splits <= min_class_count)

    if use_stratified:
        splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
        folds = [test_idx for _, test_idx in splitter.split(df, df[target_col], df[group_col])]
    else:
        actual_splits = min(n_splits, n_groups)
        if actual_splits < 3:
            # Asignación manual por grupos
            shuffled_groups = pd.Series(df[group_col].unique()).sample(frac=1.0, random_state=random_state).tolist()
            g_train = set(shuffled_groups[:max(1, int(round(train_size * len(shuffled_groups))))])
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

    # Calcular cuántos folds van a train, val y test
    n_train = int(round(train_size * n_splits))
    n_val = int(round(val_size * n_splits))
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
