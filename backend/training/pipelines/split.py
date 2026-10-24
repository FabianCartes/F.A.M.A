"""Partición reproducible por grupos completos, con cobertura estricta de clases."""
from typing import Tuple

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


def grouped_stratified_split_dataset(
    df: pd.DataFrame,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    group_col: str = "recordist",
    target_col: str = "clase",
    random_state: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Devuelve train/val/test sin cruces ni pérdida de filas.

    Todas las clases observadas son obligatorias en cada partición. Minimiza
    desviaciones absolutas normalizadas de filas totales y filas por clase;
    los ratios son objetivos aproximados, subordinados a grupos y cobertura.
    La semilla desempata asignaciones equivalentes. No modifica el DataFrame.
    Un error de cobertura indica imposibilidad demostrada, no fallo heurístico;
    una interrupción del solver se informa separadamente como RuntimeError.
    """
    try:
        ratios = np.asarray([train_ratio, val_ratio, test_ratio], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Split ratios must be positive finite numbers summing to 1") from exc
    if (not np.isfinite(ratios).all() or (ratios <= 0).any()
            or not np.isclose(ratios.sum(), 1, rtol=0, atol=1e-9)):
        raise ValueError("Split ratios must be positive finite numbers summing to 1")
    for column in (group_col, target_col):
        if column not in df.columns:
            raise ValueError(f"Missing required column: {column}")
        invalid = df[column].isna() | df[column].map(
            lambda value: isinstance(value, str) and not value.strip())
        if invalid.any():
            raise ValueError(f"Missing/null/blank values in {column}: {int(invalid.sum())} rows")

    groups, group_names = pd.factorize(df[group_col], sort=False)
    classes, class_names = pd.factorize(df[target_col], sort=False)
    n_groups, n_classes = len(group_names), len(class_names)
    if n_groups < 3:
        raise ValueError("At least three groups are required for nonempty train/val/test")
    counts = np.zeros((n_classes, n_groups))
    np.add.at(counts, (classes, groups), 1)
    scarce = {str(class_names[c]): int((counts[c] > 0).sum())
              for c in range(n_classes) if (counts[c] > 0).sum() < 3}
    if scarce:
        raise ValueError(f"Class coverage infeasible: each class needs three groups; {scarce}")

    # Binary x[split, group], then continuous absolute deviations for each
    # split's total rows and class counts. Sparse constraints keep storage linear
    # in observed class/group pairs rather than enumerating 3**n assignments.
    metrics = np.vstack([counts.sum(axis=0), counts])
    n_metrics = len(metrics)
    n_binary = 3 * n_groups
    n_variables = n_binary + 3 * n_metrics
    n_constraints = n_groups + 3 * n_classes + 6 * n_metrics
    matrix = lil_matrix((n_constraints, n_variables), dtype=float)
    lower = np.full(n_constraints, -np.inf)
    upper = np.full(n_constraints, np.inf)
    row = 0
    for g in range(n_groups):
        matrix[row, [g, n_groups + g, 2 * n_groups + g]] = 1
        lower[row] = upper[row] = 1
        row += 1
    for split in range(3):
        start = split * n_groups
        for c in range(n_classes):
            matrix[row, start:start + n_groups] = (counts[c] > 0).astype(float)
            lower[row] = 1
            row += 1
        for m, weights in enumerate(metrics):
            deviation = n_binary + split * n_metrics + m
            target = ratios[split] * weights.sum()
            matrix[row, start:start + n_groups] = weights
            matrix[row, deviation] = -1
            upper[row] = target
            row += 1
            matrix[row, start:start + n_groups] = -weights
            matrix[row, deviation] = -1
            upper[row] = -target
            row += 1

    objective = np.zeros(n_variables)
    # Small seeded tie cost; coverage remains a hard constraint.
    objective[:n_binary] = np.random.RandomState(random_state).uniform(
        0, 1e-7 / n_groups, n_binary)
    objective[n_binary:] = np.tile(1 / metrics.sum(axis=1), 3)
    result = milp(
        objective,
        integrality=np.r_[np.ones(n_binary), np.zeros(3 * n_metrics)],
        bounds=Bounds(np.zeros(n_variables),
                      np.r_[np.ones(n_binary), np.full(3 * n_metrics, np.inf)]),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"time_limit": 30, "mip_rel_gap": 0},
    )
    if result.status == 2:
        raise ValueError(f"Joint group assignment infeasible for class coverage: {list(class_names)}")
    if result.x is None:
        raise RuntimeError(f"Grouped split solver could not establish feasibility: {result.message}")
    assignment = result.x[:n_binary].reshape(3, n_groups) > .5
    if (not (assignment.sum(axis=0) == 1).all()
            or not all(((counts > 0) @ assignment[s].astype(int) >= 1).all()
                       for s in range(3))):
        raise RuntimeError("Grouped split solver returned an invalid coverage assignment")
    # A feasible incumbent at the time limit is safe: approximation, not proof
    # of ratio optimality, is the interface contract.
    return tuple(df.iloc[np.flatnonzero(assignment[s, groups])].copy().reset_index(drop=True)
                 for s in range(3))
