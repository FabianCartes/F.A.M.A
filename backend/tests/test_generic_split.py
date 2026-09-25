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


def test_grouped_stratified_split_with_scarce_groups_preserves_all_classes():
    # Simular escenario real: clase_a con 4 grupos, clase_b con 6 grupos, clase_c con 10 grupos
    rows = []
    # clase_a: 4 grupos con muchas muestras cada uno (como Train)
    for g in range(4):
        group_name = f"grp_a_{g}"
        for i in range(25):
            rows.append({"nombre_archivo": f"a_{g}_{i}.wav", "clase": "clase_a", "recordist": group_name})

    # clase_b: 6 grupos (como bus)
    for g in range(6):
        group_name = f"grp_b_{g}"
        for i in range(20):
            rows.append({"nombre_archivo": f"b_{g}_{i}.wav", "clase": "clase_b", "recordist": group_name})

    # clase_c: 10 grupos (como Autos/Helicópteros)
    for g in range(10):
        group_name = f"grp_c_{g}"
        for i in range(5):
            rows.append({"nombre_archivo": f"c_{g}_{i}.wav", "clase": "clase_c", "recordist": group_name})

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

    expected_classes = {"clase_a", "clase_b", "clase_c"}
    assert set(train_df["clase"]) == expected_classes
    assert set(val_df["clase"]) == expected_classes
    assert set(test_df["clase"]) == expected_classes

    # Invariante de cero fuga
    train_rec = set(train_df["recordist"])
    val_rec = set(val_df["recordist"])
    test_rec = set(test_df["recordist"])
    assert train_rec.isdisjoint(val_rec)
    assert train_rec.isdisjoint(test_rec)
    assert val_rec.isdisjoint(test_rec)

