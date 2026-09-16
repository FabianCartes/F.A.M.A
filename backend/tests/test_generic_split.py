import pandas as pd
import pytest

from training.pipelines.split import grouped_stratified_split_dataset


def test_grouped_stratified_split_strict_recordist_isolation():
    # Crear dataset sintético con 20 grabadores y 3 clases
    rows = []
    for rec_id in range(20):
        rec_name = f"recordist_{rec_id:02d}"
        for c in ["clase_a", "clase_b", "clase_c"]:
            rows.append({"nombre_archivo": f"audio_{rec_id}_{c}.wav", "clase": c, "recordist": rec_name})

    df = pd.DataFrame(rows)

    train_df, val_df, test_df = grouped_stratified_split_dataset(
        df=df,
        train_ratio=0.70,
        val_ratio=0.15,
        test_ratio=0.15,
        group_col="recordist",
        target_col="clase",
        random_state=42,
    )

    # Verificar que no estén vacíos
    assert len(train_df) > 0
    assert len(val_df) > 0
    assert len(test_df) > 0

    # Invariante matemático: intersección vacía de grabadores (Zero Recordist Leakage)
    train_rec = set(train_df["recordist"])
    val_rec = set(val_df["recordist"])
    test_rec = set(test_df["recordist"])

    assert train_rec.isdisjoint(val_rec)
    assert train_rec.isdisjoint(test_rec)
    assert val_rec.isdisjoint(test_rec)
