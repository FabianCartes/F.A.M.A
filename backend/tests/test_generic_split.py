import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from training.pipelines.split import grouped_stratified_split_dataset


def test_manual_caller_ingestion_and_three_way_split(tmp_path):
    # Execute the actual caller prefix only: no serving imports/model exports.
    import soundfile as sf
    from training.datasets.local_folder import LocalFolderPAMIngestor

    tree = ast.parse((Path(__file__).parents[1] / 'test_manual_pipeline.py').read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == 'main')
    block = next(node for node in main.body if isinstance(node, ast.With))
    stop = next(i for i, node in enumerate(block.body)
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'unique_classes'
                        for t in node.targets))
    namespace = dict(tmpdir=str(tmp_path), Path=Path, np=np, sf=sf,
                     LocalFolderPAMIngestor=LocalFolderPAMIngestor,
                     grouped_stratified_split_dataset=grouped_stratified_split_dataset)
    exec(compile(ast.Module(body=block.body[:stop], type_ignores=[]),
                 'manual_ingestion_split', 'exec'), namespace)
    records = namespace['records']
    parts = [namespace[name] for name in ('train_recs', 'val_recs', 'test_recs')]
    assert len(records) == 8
    assert [len(part) for part in parts] == [4, 2, 2]
    for part in parts:
        assert set(part.clase) == set(records.clase)
        assert set(part.file_stage) == {'raw'}
        assert all((tmp_path / path).is_file() for path in part.file_path)
    assert set(pd.concat(parts).file_path) == set(records.file_path)
    for i in range(3):
        for j in range(i):
            assert set(parts[i].recordist).isdisjoint(parts[j].recordist)


def test_scipy_milp_is_a_direct_supported_dependency():
    from packaging.requirements import Requirement
    requirements = [Requirement(line) for line in
                    (Path(__file__).parents[1] / 'requirements.txt').read_text().splitlines()
                    if line.strip() and not line.startswith('#')]
    scipy = next((req for req in requirements if req.name.lower() == 'scipy'), None)
    assert scipy is not None, 'milp requires a direct SciPy dependency'
    assert '1.8.1' not in scipy.specifier
    assert '1.9.0' in scipy.specifier


@pytest.mark.parametrize('has_incumbent', [True, False])
def test_solver_time_limit_preserves_feasible_incumbent_or_reports_runtime(monkeypatch, has_incumbent):
    import training.pipelines.split as split_module
    df = pd.DataFrame({'recordist': ['r1', 'r2', 'r3'], 'clase': ['A'] * 3})

    def time_limited(*args, **kwargs):
        assert kwargs['options']['time_limit'] == 30
        # Three binary group assignments per split, followed by deviations.
        incumbent = np.r_[np.eye(3).ravel(), np.zeros(6)]
        return SimpleNamespace(status=1, message='Time limit reached',
                               x=incumbent if has_incumbent else None)

    monkeypatch.setattr(split_module, 'milp', time_limited)
    if has_incumbent:
        parts = grouped_stratified_split_dataset(df)
        assert [part.recordist.tolist() for part in parts] == [['r1'], ['r2'], ['r3']]
        assert all(part.clase.tolist() == ['A'] for part in parts)
    else:
        with pytest.raises(RuntimeError, match='Time limit reached'):
            grouped_stratified_split_dataset(df)


def test_rejects_fewer_than_three_groups_without_row_fallback():
    df = pd.DataFrame({'recordist': ['r1'] * 6, 'clase': ['A'] * 6})
    with pytest.raises(ValueError, match='three groups'):
        grouped_stratified_split_dataset(df)


@pytest.mark.parametrize('column', ['recordist', 'clase'])
@pytest.mark.parametrize('bad', [None, '', '   ', float('nan')])
def test_rejects_missing_values(column, bad):
    df = pd.DataFrame({'recordist': ['r1', 'r2', 'r3'], 'clase': ['A'] * 3})
    df.loc[0, column] = bad
    with pytest.raises(ValueError, match=column):
        grouped_stratified_split_dataset(df)


@pytest.mark.parametrize('column', ['recordist', 'clase'])
def test_rejects_missing_columns(column):
    with pytest.raises(ValueError, match=column):
        grouped_stratified_split_dataset(pd.DataFrame({'recordist': [], 'clase': []}).drop(columns=column))


@pytest.mark.parametrize('ratios', [(0, .5, .5), (-.1, .5, .6), (.7, .2, .2),
                                   (float('nan'), .15, .15), (float('inf'), .15, .15)])
def test_rejects_invalid_ratios(ratios):
    df = pd.DataFrame({'recordist': ['r1', 'r2', 'r3'], 'clase': ['A'] * 3})
    with pytest.raises(ValueError, match='ratios'):
        grouped_stratified_split_dataset(df, *ratios)


def test_rejects_class_with_only_two_groups():
    df = pd.DataFrame({'recordist': ['r1', 'r2', 'r3'], 'clase': ['rare', 'rare', 'other']})
    with pytest.raises(ValueError, match='coverage.*rare'):
        grouped_stratified_split_dataset(df)


def test_joint_coverage_infeasible_despite_three_groups_per_class():
    # Each class excludes a different group: any paired groups force a missing
    # class in one of the two singleton splits (four groups, three splits).
    df = pd.DataFrame([{'recordist': g, 'clase': c}
                       for c in range(4) for g in range(4) if c != g])
    with pytest.raises(ValueError, match='infeasible.*coverage'):
        grouped_stratified_split_dataset(df)


def test_joint_coverage_feasible_with_overlapping_scarce_classes():
    # Witness: groups (0, 3), (1, 4), (2, 5) form three covers.
    membership = {'A': [0, 1, 2], 'B': [0, 4, 5],
                  'C': [3, 1, 5], 'D': [3, 4, 2]}
    df = pd.DataFrame([{'recordist': g, 'clase': c}
                       for c, gs in membership.items() for g in gs])
    parts = grouped_stratified_split_dataset(df)
    assert sum(map(len, parts)) == len(df)
    for part in parts:
        assert set(part.clase) == set(membership)
    for i in range(3):
        for j in range(i):
            assert set(parts[i].recordist).isdisjoint(parts[j].recordist)


def test_feasible_multiclass_coverage_determinism_and_row_identity():
    df = pd.DataFrame([{'recordist': g, 'clase': c, 'id': f'{g}-{c}',
                        'file_stage': 'processed', 'file_path': f'{g}/{c}.wav'}
                       for g in range(20) for c in ['A', 'B', 'C']])
    df.index = [7] * len(df)  # Index labels must not identify rows.
    before = df.copy(deep=True)
    parts = grouped_stratified_split_dataset(df)
    again = grouped_stratified_split_dataset(df)
    assert [len(p) for p in parts] == [42, 9, 9]
    for p, q in zip(parts, again):
        pd.testing.assert_frame_equal(p, q)
        assert set(p.clase) == {'A', 'B', 'C'}
    pd.testing.assert_frame_equal(df, before)
    combined = pd.concat(parts).sort_values('id').reset_index(drop=True)
    pd.testing.assert_frame_equal(combined, df.sort_values('id').reset_index(drop=True))


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

