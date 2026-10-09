import pandas as pd
import pytest
from poc.split import grouped_stratified_split

def test_grouped_stratified_split_disjoint_recordists():
    # Synthetic dataset with 5 species and 20 recordists
    data = []
    species = ["Especie A", "Especie B", "Especie C", "Especie D", "Especie E"]
    recordists = [f"Rec_{i}" for i in range(20)]
    
    # Distribute recordings
    for i in range(200):
        sp = species[i % len(species)]
        rec = recordists[i % len(recordists)]
        data.append({"xc_id": str(i), "clase": sp, "recordist": rec})
        
    df = pd.DataFrame(data)
    
    train_df, val_df, test_df = grouped_stratified_split(
        df,
        group_col="recordist",
        target_col="clase",
        train_size=0.70,
        val_size=0.15,
        test_size=0.15,
        random_state=42
    )
    
    # 1. Row preservation
    assert len(train_df) + len(val_df) + len(test_df) == len(df)
    
    # 2. Strict group separation (no shared recordist)
    train_recs = set(train_df["recordist"])
    val_recs = set(val_df["recordist"])
    test_recs = set(test_df["recordist"])
    
    assert len(train_recs.intersection(val_recs)) == 0, "Train and Val share recordists!"
    assert len(train_recs.intersection(test_recs)) == 0, "Train and Test share recordists!"
    assert len(val_recs.intersection(test_recs)) == 0, "Val and Test share recordists!"
    
    # Each species has only four exclusive groups. Strict coverage reserves
    # one per species in val and test, so at most 50% can remain in train.
    # The old 55% floor depended on allowing classes to be absent.
    train_pct = len(train_df) / len(df)
    val_pct = len(val_df) / len(df)
    test_pct = len(test_df) / len(df)
    
    assert train_pct == 0.5
    assert val_pct == test_pct == 0.25
    for part in (train_df, val_df, test_df):
        assert set(part.clase) == set(species)

def test_grouped_stratified_split_empty_or_small():
    df = pd.DataFrame([
        {"xc_id": "1", "clase": "A", "recordist": "R1"},
        {"xc_id": "2", "clase": "A", "recordist": "R2"},
        {"xc_id": "3", "clase": "B", "recordist": "R3"},
    ])
    # Deliberate contract change: class B cannot occur in three disjoint splits.
    with pytest.raises(ValueError, match='coverage'):
        grouped_stratified_split(df, random_state=42)


def test_poc_preserves_positional_argument_order_and_matches_shared_split():
    from training.pipelines.split import grouped_stratified_split_dataset
    df = pd.DataFrame([{'group': g, 'label': c} for g in range(20) for c in ['A', 'B']])
    actual = grouped_stratified_split(df, 'group', 'label', .6, .2, .2, 17)
    expected = grouped_stratified_split_dataset(df, .6, .2, .2, 'group', 'label', 17)
    assert isinstance(actual, tuple)
    for a, e in zip(actual, expected):
        pd.testing.assert_frame_equal(a, e)


@pytest.mark.parametrize('rows', [[], [{'recordist': 'r', 'clase': 'A'}] * 6,
                                 [{'recordist': '', 'clase': 'A'}] * 6])
def test_poc_does_not_bypass_strict_validation(rows):
    with pytest.raises(ValueError):
        grouped_stratified_split(pd.DataFrame(rows, columns=['recordist', 'clase']))
