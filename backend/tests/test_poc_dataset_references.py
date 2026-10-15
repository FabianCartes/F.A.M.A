"""Shared PoC readers and prepared-only evaluation admission; no training."""
import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import soundfile as sf
import torch

from poc.train import AudioDataset, build_dataloaders
from training import paths
from training.prepare_data import prepare_dataset, load_prepared_dataset


class PreparedReaders(Exception):
    """Stop before frontend/model construction."""


@pytest.fixture
def source(tmp_path, monkeypatch):
    roots = {stage: tmp_path / stage for stage in ("raw", "processed")}
    rows = []
    for stage, root in roots.items():
        root.mkdir()
        for i in range(20):
            sf.write(root / f"{i:03}.wav", np.full(8000, .25 if stage == "raw" else -.5), 8000)
    for i in range(20):
        rows.append({"file_path": f"{i:03}.wav", "file_stage": "processed", "clase": "Bird",
                     "recordist": f"{i:03}", "xc_id": f"{i:03}", "hash": "00abc"})
    frame = pd.DataFrame(rows)
    index = tmp_path / "metadata.csv"
    frame.to_csv(index, index=False)
    prepared = tmp_path / "prepared"
    monkeypatch.setattr(paths, "get_prepared_data_dir", lambda name: prepared)
    # Also handles a module-level import in train, if present.
    monkeypatch.setattr("poc.train.get_prepared_data_dir", lambda name: prepared, raising=False)
    monkeypatch.setattr("poc.evaluate.get_prepared_data_dir", lambda name: prepared, raising=False)
    return roots, frame, index, prepared




def prepare(source, dataset_name="AvesChilenas"):
    roots, _, index, destination = source
    prepare_dataset(index, roots=roots, dataset_name=dataset_name, output_dir=destination)
    return load_prepared_dataset(destination, roots=roots, dataset_name=dataset_name)












@pytest.mark.parametrize("stage,level", [("raw", .25), ("processed", -.5)])
def test_public_readers_bind_explicit_stage(source, stage, level):
    roots, frame, _, _ = source
    frame = frame.iloc[:1].assign(file_stage=stage)
    dataset = AudioDataset(frame, roots["raw"], {"Bird": 0}, roots=roots,
                           target_sr=8000, duration_seconds=1, return_raw_waveform=True)
    waveform, label = dataset[0]
    assert torch.allclose(waveform, torch.full((8000,), level))
    assert label.item() == 0
    train, val = build_dataloaders(frame, frame, roots["raw"], {"Bird": 0}, roots=roots,
                                  num_workers=0, batch_size=1, return_raw_waveform=True)
    assert len(train.dataset) == 1
    assert next(iter(val))[0].mean().item() == pytest.approx(level / 5, abs=.001)


@pytest.mark.parametrize("defect", ["missing_stage", "unknown_stage", "blank_stage", "missing_path",
                                   "absolute", "traversal", "missing_file", "missing_root", "root_alias", "path_alias"])
def test_poc_rejects_invalid_reference_without_fallback(source, tmp_path, defect):
    roots, frame, _, _ = source
    frame = frame.iloc[:1]
    if defect in ("missing_stage", "missing_path"):
        frame = frame.drop(columns="file_stage" if defect == "missing_stage" else "file_path")
    elif defect in ("unknown_stage", "blank_stage"):
        frame = frame.assign(file_stage="unknown" if defect == "unknown_stage" else "")
    elif defect in ("absolute", "traversal", "missing_file"):
        frame = frame.assign(file_path={"absolute": str(roots["processed"] / "000.wav"),
                                       "traversal": "../processed/000.wav", "missing_file": "absent.wav"}[defect])
    elif defect == "missing_root":
        roots = {"raw": roots["raw"]}
    elif defect == "root_alias":
        alias = tmp_path / "alias"
        alias.symlink_to(roots["processed"], target_is_directory=True)
        roots = {**roots, "processed": alias}
    else:
        (roots["processed"] / "linked.wav").symlink_to(roots["processed"] / "000.wav")
        frame = frame.assign(file_path="linked.wav")
    with pytest.raises(ValueError):
        AudioDataset(frame, roots["raw"], {"Bird": 0}, roots=roots)




@pytest.mark.parametrize("entrypoint,public_name", [
    ("train", "AudioCNN"), ("benchmark", "aggregate_benchmark_metrics"),
])
def test_shared_modules_no_longer_launch_cli_training(tmp_path, monkeypatch, capsys, entrypoint, public_name):
    def unexpected(*args, **kwargs):
        pytest.fail("Retired CLI must not bind datasets or construct training loaders")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "get_dataset_roots", unexpected)
    monkeypatch.setattr(paths, "get_project_root", unexpected)
    monkeypatch.setattr(torch.utils.data, "DataLoader", unexpected)
    monkeypatch.setattr("sys.argv", [entrypoint + ".py"])
    namespace = runpy.run_path(
        str(Path(__file__).parents[1] / "poc" / f"{entrypoint}.py"), run_name="__main__",
    )
    assert callable(namespace[public_name])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("stage,level", [("raw", .25), ("processed", -.5)])
def test_public_evaluation_still_reads_explicit_custom_stage(source, tmp_path, monkeypatch, stage, level):
    from poc import evaluate
    roots, frame, _, _ = source
    frame = frame.iloc[:1].assign(file_stage=stage, recordist="NA")
    index = tmp_path / "test.csv"
    frame.to_csv(index, index=False)
    monkeypatch.setattr(evaluate, "load_checkpoint_model", lambda *args: (
        torch.nn.Identity(), {"classes": ["Bird"], "label_to_idx": {"Bird": 0}}))
    def loader(dataset, **kwargs):
        pd.testing.assert_frame_equal(dataset.df, frame)
        assert dataset[0][0].mean().item() == pytest.approx(level / 5, abs=.001)
        raise PreparedReaders
    monkeypatch.setattr(evaluate, "DataLoader", loader)
    with pytest.raises(PreparedReaders):
        evaluate.run_evaluation(checkpoint_path=tmp_path / "fake.pt", test_csv=index,
                                raw_dir=roots["raw"], roots=roots, device="cpu")


def test_poc_revalidates_original_root_even_with_supplied_window_cache(source):
    roots, frame, _, _ = source
    frame = frame.iloc[:1]
    dataset = AudioDataset(frame, roots["raw"], {"Bird": 0}, roots=roots,
                           windows_cache={0: [np.full(8000, -.5, dtype=np.float32)]},
                           target_sr=8000, duration_seconds=1, return_raw_waveform=True)
    assert dataset[0][0].mean().item() == -.5
    selected = roots["processed"]
    physical = selected.with_name("physical")
    selected.rename(physical)
    selected.symlink_to(physical, target_is_directory=True)
    roots["processed"] = physical
    with pytest.raises(ValueError, match="symlink"):
        dataset[0]


@pytest.mark.parametrize("defect", ["missing_stage", "unknown_stage", "missing_root", "alias"])
def test_evaluation_invalid_reference_fails_before_checkpoint_loading(source, tmp_path, monkeypatch, defect):
    from poc import evaluate
    roots, frame, _, _ = source
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


def test_evaluation_cli_binds_configured_aves_roots_once(source, tmp_path, monkeypatch):
    roots, frame, _, _ = source
    prepare(source)
    (roots["raw"] / "test.csv").write_text("raw test must not be read")
    bindings = []
    def configured(name):
        bindings.append(name)
        return dict(roots)
    monkeypatch.setattr(paths, "get_dataset_roots", configured)
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr("sys.argv", ["evaluate.py", "--checkpoint", "fake.pt"])
    monkeypatch.setattr(torch, "load", lambda *a, **k: (_ for _ in ()).throw(PreparedReaders()))
    with pytest.raises(PreparedReaders):
        runpy.run_path(str(Path(__file__).parents[1] / "poc/evaluate.py"), run_name="__main__")
    assert bindings == ["AvesChilenas"]






@pytest.mark.parametrize("mode", ["missing_identity", "unsupported", "exclusive", "absent", "incomplete", "altered"])
def test_evaluation_admission_before_ml(source, tmp_path, monkeypatch, mode):
    from poc import evaluate
    roots, _, index, destination = source
    kwargs = {"dataset_name": "AvesChilenas"}
    if mode == "missing_identity":
        kwargs = {}
    elif mode == "unsupported":
        kwargs = {"dataset_name": "unsupported"}
    elif mode == "exclusive":
        kwargs["test_csv"] = index
    elif mode in ("incomplete", "altered"):
        prepare(source)
        if mode == "incomplete":
            (destination / ".complete").rename(tmp_path / "marker")
        else:
            (destination / "test.csv").write_text("altered")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: pytest.fail("admission before ML"))
    with pytest.raises((ValueError, OSError)):
        evaluate.run_evaluation(roots=roots, output_image_path=tmp_path / "out.png", **kwargs)
    assert not (tmp_path / "out.png").exists()




@pytest.mark.parametrize("dataset_name", ["AvesChilenas", "engine_diagnostics"])
def test_evaluation_reads_only_prepared_test_membership(source, tmp_path, monkeypatch, dataset_name):
    from poc import evaluate
    expected = prepare(source, dataset_name)[2]
    roots = source[0]
    (roots["raw"] / "test.csv").write_text("never adopt raw test")
    monkeypatch.setattr(evaluate, "load_checkpoint_model", lambda *a: (
        torch.nn.Identity(), {"classes": ["Bird"], "label_to_idx": {"Bird": 0}}))
    def loader(dataset, **kwargs):
        pd.testing.assert_frame_equal(dataset.df, expected)
        raise PreparedReaders
    monkeypatch.setattr(evaluate, "DataLoader", loader)
    monkeypatch.setattr(pd, "read_csv", lambda *a, **k: pytest.fail("prepared mode must not use custom reader"))
    with pytest.raises(PreparedReaders):
        evaluate.run_evaluation(checkpoint_path=tmp_path / "fake.pt", roots=roots,
                                dataset_name=dataset_name, device="cpu")






def test_admitted_source_returns_owned_copies_and_revalidates_trio(source):
    from poc.train import AdmittedPreparedSource
    expected = prepare(source)
    admitted = AdmittedPreparedSource(dataset_name="AvesChilenas", roots=source[0])
    frames = admitted.frames(dataset_name="AvesChilenas", roots=source[0])
    frames[0]["recordist"] = "mutated caller copy"
    for actual, wanted in zip(admitted.frames(dataset_name="AvesChilenas", roots=source[0]), expected):
        pd.testing.assert_frame_equal(actual, wanted)
    # Audio references remain live and validated, even though CSV membership is frozen.
    root = source[0]["processed"]
    root.rename(root.with_name("physical"))
    with pytest.raises(ValueError):
        admitted.frames(dataset_name="AvesChilenas", roots=source[0])


def test_public_interfaces_require_roots(source, tmp_path):
    from poc.evaluate import run_evaluation
    roots, frame, index, _ = source
    with pytest.raises(TypeError, match="roots"):
        AudioDataset(frame, roots["raw"], {"Bird": 0})
    with pytest.raises(TypeError, match="roots"):
        build_dataloaders(frame, frame, roots["raw"], {"Bird": 0})
    with pytest.raises(TypeError, match="roots"):
        run_evaluation(checkpoint_path=tmp_path / "fake.pt")
