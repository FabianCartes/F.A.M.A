"""PoC public readers and split publication, without model construction or training."""
import numpy as np
import pandas as pd
import pytest
import soundfile as sf
import torch

from poc.train import AudioDataset, build_dataloaders, train_pipeline


@pytest.fixture
def source(tmp_path):
    roots = {stage: tmp_path / stage for stage in ("raw", "processed")}
    for stage, root in roots.items():
        (root / "audio").mkdir(parents=True)
        sf.write(root / "audio/001.wav", np.full(8000, .25 if stage == "raw" else -.5), 8000)
    frame = pd.DataFrame([{"file_path": "audio/001.wav", "file_stage": "processed",
                           "clase": "Bird", "recordist": "009", "xc_id": "001",
                           "hash": "00abc", "source_group": "0007", "labels": "['Bird']"}])
    return roots, frame


@pytest.mark.parametrize("stage,level", [("raw", .25), ("processed", -.5)])
def test_poc_reads_declared_stage_with_custom_roots(source, stage, level):
    roots, frame = source
    frame = frame.assign(file_stage=stage)
    dataset = AudioDataset(frame, roots["raw"], {"Bird": 0}, roots=roots,
                           target_sr=8000, duration_seconds=1, return_raw_waveform=True)
    waveform, label = dataset[0]
    assert torch.allclose(waveform, torch.full((8000,), level))
    assert label.item() == 0
    pd.testing.assert_frame_equal(dataset.df, frame)


def test_poc_loader_binds_both_readers_to_custom_stage(source):
    roots, frame = source
    train, val = build_dataloaders(frame, frame, roots["raw"], {"Bird": 0}, roots=roots,
                                  batch_size=1, num_workers=0, pin_memory=False,
                                  return_raw_waveform=True)
    assert len(train.dataset) == 1
    waveform, label = next(iter(val))
    # The loader retains its five-second default, padding this one-second fixture.
    assert waveform.mean().item() == pytest.approx(-.1, abs=.001)
    assert label.item() == 0


@pytest.mark.parametrize("existing", [("train",), ("val",), ("test",),
                                       ("train", "val"), ("train", "test"), ("val", "test")])
def test_pipeline_partial_trio_fails_without_any_writes(source, tmp_path, existing):
    roots, frame = source
    index = tmp_path / "metadata.csv"
    frame.to_csv(index, index=False)
    for split in existing:
        frame.to_csv(tmp_path / f"{split}.csv", index=False)
    before = {p: p.read_bytes() for p in tmp_path.glob("*.csv")}
    with pytest.raises(ValueError, match="partial|incomplete"):
        train_pipeline(index, roots["raw"], tmp_path / "checkpoints", roots=roots, device="cpu")
    assert {p: p.read_bytes() for p in tmp_path.glob("*.csv")} == before
    assert not (tmp_path / "checkpoints").exists()


class PreparedReaders(Exception):
    """Stop at the external execution boundary before frontend/model/optimizer."""


@pytest.fixture
def prepared_readers(monkeypatch):
    prepared = []

    def loader(dataset, **kwargs):
        dataset[0]
        prepared.append(dataset.df.copy(deep=True))
        if len(prepared) == 2:
            raise PreparedReaders
        return []

    monkeypatch.setattr("poc.train.DataLoader", loader)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    return prepared


def test_pipeline_complete_trio_preserves_membership_and_text_identity(source, tmp_path, prepared_readers):
    roots, frame = source
    frames = [frame.assign(xc_id=identifier, recordist=identifier)
              for identifier in ("001", "002", "NA")]
    for split, rows in zip(("train", "val", "test"), frames):
        rows.to_csv(tmp_path / f"{split}.csv", index=False)
    before = {p: p.read_bytes() for p in tmp_path.glob("*.csv")}
    # No metadata index is needed when an authoritative complete trio exists.
    with pytest.raises(PreparedReaders):
        train_pipeline(tmp_path / "absent.csv", roots["raw"], tmp_path / "checkpoints",
                       roots=roots, device="cpu", num_workers=0)
    for actual, expected in zip(prepared_readers, frames):
        pd.testing.assert_frame_equal(actual, expected)
    assert {p: p.read_bytes() for p in tmp_path.glob("*.csv")} == before
    assert not (tmp_path / "checkpoints").exists()


def test_pipeline_new_trio_contains_only_indexed_rows_and_preserves_lineage(source, tmp_path, prepared_readers):
    roots, frame = source
    rows = pd.concat([frame.assign(xc_id=f"00{i:02}", recordist=f"00{i:02}", source_group=f"00{i:02}")
                      for i in range(20)], ignore_index=True)
    index = tmp_path / "metadata.csv"
    rows.to_csv(index, index=False)
    original = index.read_bytes()
    sf.write(roots["raw"] / "unindexed.wav", np.zeros(8000), 8000)
    with pytest.raises(PreparedReaders):
        train_pipeline(index, roots["raw"], tmp_path / "checkpoints", roots=roots, device="cpu")
    frames = [pd.read_csv(tmp_path / f"{split}.csv", dtype=str, keep_default_na=False)
              for split in ("train", "val", "test")]
    actual = pd.concat(frames).sort_values("xc_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, rows.sort_values("xc_id").reset_index(drop=True))
    groups = [set(f.recordist) for f in frames]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    assert index.read_bytes() == original
    assert not (tmp_path / "checkpoints").exists()


@pytest.mark.parametrize("defect", ["missing_stage", "unknown_stage", "blank_stage", "missing_path",
                                   "absolute", "traversal", "missing_file", "missing_root", "root_alias", "path_alias"])
def test_poc_rejects_invalid_reference_without_fallback(source, tmp_path, defect):
    roots, frame = source
    if defect.startswith("missing_") and defect in ("missing_stage", "missing_path"):
        frame = frame.drop(columns="file_stage" if defect == "missing_stage" else "file_path")
    elif defect in ("unknown_stage", "blank_stage"):
        frame = frame.assign(file_stage="unknown" if defect == "unknown_stage" else "")
    elif defect in ("absolute", "traversal", "missing_file"):
        frame = frame.assign(file_path={"absolute": str(roots["processed"] / "audio/001.wav"),
                                       "traversal": "audio/../audio/001.wav", "missing_file": "absent.wav"}[defect])
    elif defect == "missing_root":
        roots = {"raw": roots["raw"]}
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(roots["processed"], target_is_directory=True)
        if defect == "root_alias":
            roots = {**roots, "processed": alias}
        else:
            (roots["processed"] / "linked").symlink_to(roots["processed"] / "audio", target_is_directory=True)
            frame = frame.assign(file_path="linked/001.wav")
    with pytest.raises(ValueError):
        AudioDataset(frame, roots["raw"], {"Bird": 0}, roots=roots)


def test_poc_revalidates_original_root_even_with_supplied_window_cache(source):
    roots, frame = source
    dataset = AudioDataset(frame, roots["raw"], {"Bird": 0}, roots=roots,
                           windows_cache={0: [np.full(8000, -.5, dtype=np.float32)]},
                           target_sr=8000, duration_seconds=1, return_raw_waveform=True)
    assert dataset[0][0].mean().item() == -.5
    selected = roots["processed"]
    physical = selected.with_name("physical")
    selected.rename(physical)
    selected.symlink_to(physical, target_is_directory=True)
    roots["processed"] = physical  # External configuration mutation cannot erase the original alias.
    with pytest.raises(ValueError, match="symlink"):
        dataset[0]


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("defect", ["missing_stage", "unknown_stage", "missing_file"])
def test_pipeline_invalid_index_never_publishes_or_regenerates(source, tmp_path, prepared_readers, complete, defect):
    roots, frame = source
    invalid = frame.drop(columns="file_stage") if defect == "missing_stage" else frame.assign(
        **({"file_stage": "unknown"} if defect == "unknown_stage" else {"file_path": "missing.wav"}))
    if complete:
        for split, rows in zip(("train", "val", "test"), (frame, frame, invalid)):
            rows.to_csv(tmp_path / f"{split}.csv", index=False)
    else:
        invalid.to_csv(tmp_path / "metadata.csv", index=False)
    before = {p: p.read_bytes() for p in tmp_path.glob("*.csv")}
    with pytest.raises(ValueError):
        train_pipeline(tmp_path / "metadata.csv", roots["raw"], tmp_path / "checkpoints", roots=roots, device="cpu")
    assert not prepared_readers
    assert {p: p.read_bytes() for p in tmp_path.glob("*.csv")} == before
    assert not (tmp_path / "checkpoints").exists()


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_pipeline_rejects_malformed_complete_output_targets(source, tmp_path, prepared_readers, kind):
    roots, frame = source
    for split in ("train", "val"):
        frame.to_csv(tmp_path / f"{split}.csv", index=False)
    target = tmp_path / "test.csv"
    if kind == "directory":
        target.mkdir()
    else:
        external = tmp_path / "external.csv"
        frame.to_csv(external, index=False)
        target.symlink_to(external)
    before = (tmp_path / "train.csv").read_bytes()
    with pytest.raises(ValueError):
        train_pipeline(tmp_path / "metadata.csv", roots["raw"], tmp_path / "checkpoints", roots=roots, device="cpu")
    assert (tmp_path / "train.csv").read_bytes() == before
    assert not prepared_readers


def test_public_poc_interfaces_require_roots(source, tmp_path):
    roots, frame = source
    with pytest.raises(TypeError, match="roots"):
        AudioDataset(frame, roots["raw"], {"Bird": 0})
    with pytest.raises(TypeError, match="roots"):
        build_dataloaders(frame, frame, roots["raw"], {"Bird": 0})
    with pytest.raises(TypeError, match="roots"):
        train_pipeline(tmp_path / "metadata.csv", roots["raw"], tmp_path / "checkpoints")


def test_pipeline_publication_never_clobbers_concurrent_split(source, tmp_path, prepared_readers, monkeypatch):
    from pathlib import Path

    roots, frame = source
    frame.to_csv(tmp_path / "metadata.csv", index=False)
    open_path = Path.open
    foreign = tmp_path / "val.csv"
    def concurrent_open(path, mode="r", *args, **kwargs):
        if path == tmp_path / "train.csv" and mode == "x":
            foreign.write_bytes(b"foreign split membership")
        return open_path(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", concurrent_open)
    with pytest.raises(ValueError, match="publication failed"):
        train_pipeline(tmp_path / "metadata.csv", roots["raw"], tmp_path / "checkpoints", roots=roots, device="cpu")
    assert foreign.read_bytes() == b"foreign split membership"
    assert not prepared_readers
    assert not (tmp_path / "checkpoints").exists()
    with pytest.raises(ValueError, match="partial"):
        train_pipeline(tmp_path / "metadata.csv", roots["raw"], tmp_path / "checkpoints", roots=roots, device="cpu")
    assert foreign.read_bytes() == b"foreign split membership"


def test_poc_cli_declares_aves_roots_once_and_reads_index_stage(source, tmp_path, monkeypatch):
    import runpy
    from pathlib import Path
    from training import paths

    roots, frame = source
    for split in ("train", "val", "test"):
        frame.to_csv(roots["raw"] / f"{split}.csv", index=False)
    bindings = []
    def configured_roots(name):
        bindings.append(name)
        return dict(roots)
    monkeypatch.setattr(paths, "get_dataset_roots", configured_roots)
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr("sys.argv", ["train.py", "--device", "cpu"])
    observed = []
    def loader(dataset, **kwargs):
        waveform, label = dataset[0]
        pd.testing.assert_frame_equal(dataset.df, frame)
        if not dataset.is_train:
            assert waveform.mean().item() == pytest.approx(-.1, abs=.001)
        observed.append(label.item())
        if len(observed) == 2:
            raise PreparedReaders
        return []
    monkeypatch.setattr(torch.utils.data, "DataLoader", loader)
    with pytest.raises(PreparedReaders):
        runpy.run_path(str(Path(__file__).parents[1] / "poc/train.py"), run_name="__main__")
    assert bindings == ["AvesChilenas"]
    assert observed == [0, 0]
    assert not (tmp_path / "checkpoints").exists()


@pytest.mark.parametrize("stage,level", [("raw", .25), ("processed", -.5)])
def test_public_evaluation_reads_custom_roots_and_preserves_text_index(source, tmp_path, monkeypatch, stage, level):
    from poc import evaluate

    roots, frame = source
    frame = frame.assign(file_stage=stage, recordist="NA")
    index = tmp_path / "test.csv"
    frame.to_csv(index, index=False)
    before = index.read_bytes()
    monkeypatch.setattr(evaluate, "load_checkpoint_model", lambda *args: (
        torch.nn.Identity(), {"classes": ["Bird"], "label_to_idx": {"Bird": 0}}))
    def loader(dataset, **kwargs):
        pd.testing.assert_frame_equal(dataset.df, frame)
        waveform, label = dataset[0]
        assert waveform.mean().item() == pytest.approx(level / 5, abs=.001)
        assert label.item() == 0
        raise PreparedReaders
    monkeypatch.setattr(evaluate, "DataLoader", loader)
    with pytest.raises(PreparedReaders):
        evaluate.run_evaluation(checkpoint_path=tmp_path / "fake.pt", test_csv=index,
                                raw_dir=roots["raw"], roots=roots, device="cpu",
                                output_image_path=tmp_path / "matrix.png")
    assert index.read_bytes() == before
    assert not (tmp_path / "matrix.png").exists()


def test_benchmark_propagates_custom_roots_to_actual_training_readers(source, tmp_path, prepared_readers):
    from poc.benchmark import run_benchmark

    roots, frame = source
    for split in ("train", "val", "test"):
        frame.to_csv(tmp_path / f"{split}.csv", index=False)
    before = {p: p.read_bytes() for p in tmp_path.glob("*.csv")}
    with pytest.raises(PreparedReaders):
        run_benchmark(tmp_path / "metadata.csv", roots["raw"], tmp_path / "test.csv",
                      tmp_path / "output", roots=roots, num_runs=1, device="cpu")
    for actual in prepared_readers:
        pd.testing.assert_frame_equal(actual, frame)
    assert {p: p.read_bytes() for p in tmp_path.glob("*.csv")} == before


def test_benchmark_partial_trio_creates_no_outputs(source, tmp_path, prepared_readers):
    from poc.benchmark import run_benchmark

    roots, frame = source
    frame.to_csv(tmp_path / "train.csv", index=False)
    before = (tmp_path / "train.csv").read_bytes()
    with pytest.raises(ValueError, match="partial"):
        run_benchmark(tmp_path / "metadata.csv", roots["raw"], tmp_path / "test.csv",
                      tmp_path / "output", roots=roots, num_runs=1, device="cpu")
    assert not (tmp_path / "output").exists()
    assert (tmp_path / "train.csv").read_bytes() == before
    assert not prepared_readers


@pytest.mark.parametrize("defect", ["missing_stage", "unknown_stage", "missing_root", "alias"])
def test_evaluation_invalid_reference_fails_before_checkpoint_loading(source, tmp_path, monkeypatch, defect):
    from poc import evaluate

    roots, frame = source
    if defect == "missing_stage":
        frame = frame.drop(columns="file_stage")
    elif defect == "unknown_stage":
        frame = frame.assign(file_stage="unknown")
    elif defect == "missing_root":
        roots = {"raw": roots["raw"]}
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(roots["processed"], target_is_directory=True)
        roots = {**roots, "processed": alias}
    index = tmp_path / "test.csv"
    frame.to_csv(index, index=False)
    def forbidden_checkpoint(*args):
        pytest.fail("invalid index must fail before checkpoint loading")
    monkeypatch.setattr(evaluate, "load_checkpoint_model", forbidden_checkpoint)
    with pytest.raises(ValueError):
        evaluate.run_evaluation(checkpoint_path=tmp_path / "fake.pt", test_csv=index,
                                roots=roots, raw_dir=roots["raw"], device="cpu")


@pytest.mark.parametrize("entrypoint", ["evaluate", "benchmark"])
def test_remaining_cli_entrypoints_bind_configured_aves_roots_once(source, tmp_path, monkeypatch, entrypoint):
    import runpy
    from pathlib import Path
    from training import paths
    from poc import evaluate, train

    roots, frame = source
    for split in ("train", "val", "test"):
        frame.to_csv(roots["raw"] / f"{split}.csv", index=False)
    bindings = []
    def configured(name):
        bindings.append(name)
        return dict(roots)
    monkeypatch.setattr(paths, "get_dataset_roots", configured)
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr("sys.argv", [entrypoint + ".py"] + (
        ["--checkpoint", "fake.pt"] if entrypoint == "evaluate" else ["--device", "cpu"]))
    monkeypatch.setattr(evaluate, "load_checkpoint_model", lambda *args: (
        torch.nn.Identity(), {"classes": ["Bird"], "label_to_idx": {"Bird": 0}}))
    # run_path defines evaluation's checkpoint loader locally. Stop at torch.load
    # when that entrypoint loads metadata; no real checkpoint is opened.
    if entrypoint == "evaluate":
        monkeypatch.setattr(torch, "load", lambda *args, **kwargs: (_ for _ in ()).throw(PreparedReaders()))
    else:
        def loader(dataset, **kwargs):
            pd.testing.assert_frame_equal(dataset.df, frame)
            dataset[0]
            raise PreparedReaders
        monkeypatch.setattr(train, "DataLoader", loader)
    with pytest.raises(PreparedReaders):
        runpy.run_path(str(Path(__file__).parents[1] / "poc" / f"{entrypoint}.py"), run_name="__main__")
    assert bindings == ["AvesChilenas"]
    assert not (tmp_path / "checkpoints").exists()
    assert not (tmp_path / "benchmarks").exists()


def test_remaining_public_entrypoints_require_roots(tmp_path):
    from poc.benchmark import run_benchmark
    from poc.evaluate import run_evaluation

    with pytest.raises(TypeError, match="roots"):
        run_evaluation(checkpoint_path=tmp_path / "fake.pt")
    with pytest.raises(TypeError, match="roots"):
        run_benchmark(tmp_path / "metadata.csv", tmp_path / "raw", tmp_path / "test.csv", tmp_path / "output")
