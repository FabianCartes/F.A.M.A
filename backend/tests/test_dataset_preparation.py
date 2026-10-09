"""Preparation public seam: synthetic indices/audio only, no application imports."""
import os
import stat

import pandas as pd
import pytest

from training.prepare_data import prepare_dataset, load_prepared_dataset
from training.paths import get_prepared_data_dir


def fixture_index(tmp_path, dataset="AvesChilenas"):
    root = tmp_path / "audio"
    root.mkdir()
    rows = []
    for group in range(6):
        for label in ("A", "B"):
            name = f"{group}-{label}.wav"
            (root / name).write_bytes(b"audio")
            rows.append(dict(file_path=name, file_stage="raw", recordist=f"r{group}",
                             clase=label, xc_id=f"00{group}{label}",
                             source_id=f"00{group}{label}", extra="NA"))
    frame = pd.DataFrame(rows)
    index = tmp_path / "index.csv"
    frame.to_csv(index, index=False)
    return index, {"raw": root}, frame


@pytest.mark.parametrize("dataset,suffix", [("AvesChilenas", ""), ("engine_diagnostics", "_metadata")])
@pytest.mark.parametrize("stage", ["raw", "processed"])
def test_prepare_complete_preserved_reproducible(tmp_path, dataset, suffix, stage):
    index, roots, original = fixture_index(tmp_path)
    roots = {stage: roots["raw"]}
    original["file_stage"] = stage
    original.to_csv(index, index=False)
    destinations = [tmp_path / "one", tmp_path / "two"]
    old = os.umask(0o077)
    try:
        for destination in destinations:
            result = prepare_dataset(index, roots=roots, dataset_name=dataset, output_dir=destination)
            parts = load_prepared_dataset(destination, roots=roots, dataset_name=dataset)
            assert sum(result["counts"].values()) == 12
            assert sum(result["ratios"].values()) == pytest.approx(1)
            merged = pd.concat(parts).sort_values("file_path").reset_index(drop=True)
            pd.testing.assert_frame_equal(merged, original.sort_values("file_path").reset_index(drop=True))
            for i, part in enumerate(parts):
                assert set(part.clase) == {"A", "B"}
                for other in parts[:i]:
                    assert set(part.recordist).isdisjoint(other.recordist)
            assert stat.S_IMODE(destination.stat().st_mode) == 0o755
            for file in destination.iterdir():
                assert stat.S_IMODE(file.stat().st_mode) == 0o644
    finally:
        os.umask(old)
    for split in ("train", "val", "test"):
        name = f"{split}{suffix}.csv"
        assert (destinations[0] / name).read_bytes() == (destinations[1] / name).read_bytes()


@pytest.mark.parametrize("bad", ["missing", "escape", "duplicate_ref", "duplicate_id", "blank_group", "infeasible"])
def test_invalid_input_never_reserves_destination(tmp_path, bad):
    index, roots, frame = fixture_index(tmp_path)
    if bad == "missing":
        frame.loc[0, "file_path"] = "missing.wav"
    elif bad == "escape":
        frame.loc[0, "file_path"] = "../escape.wav"
    elif bad == "duplicate_ref":
        frame.loc[0, "file_path"] = frame.loc[1, "file_path"]
    elif bad == "duplicate_id":
        frame.loc[0, "xc_id"] = frame.loc[1, "xc_id"]
    elif bad == "blank_group":
        frame.loc[0, "recordist"] = " "
    else:
        frame["recordist"] = "one"
    frame.to_csv(index, index=False)
    destination = tmp_path / "prepared"
    with pytest.raises(ValueError):
        prepare_dataset(index, roots=roots, dataset_name="AvesChilenas", output_dir=destination)
    assert not destination.exists()


@pytest.mark.parametrize("kind", ["existing", "linked_parent", "absent_parent", "linked_target"])
def test_foreign_destinations_untouched(tmp_path, kind):
    index, roots, _ = fixture_index(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir(mode=0o700)
    sentinel = foreign / "sentinel"
    sentinel.write_text("untouched")
    inode = foreign.stat().st_ino
    if kind == "existing":
        destination = foreign
    elif kind == "linked_parent":
        alias = tmp_path / "alias"
        alias.symlink_to(foreign, target_is_directory=True)
        destination = alias / "prepared"
    elif kind == "linked_target":
        destination = tmp_path / "alias"
        destination.symlink_to(foreign, target_is_directory=True)
    else:
        destination = tmp_path / "absent" / "prepared"
    with pytest.raises((OSError, ValueError)):
        prepare_dataset(index, roots=roots, dataset_name="AvesChilenas", output_dir=destination)
    assert foreign.stat().st_ino == inode
    assert stat.S_IMODE(foreign.stat().st_mode) == 0o700
    assert sentinel.read_text() == "untouched"
    assert list(foreign.iterdir()) == [sentinel]


def test_late_competitor_is_not_adopted(tmp_path, monkeypatch):
    index, roots, _ = fixture_index(tmp_path)
    destination = tmp_path / "prepared"
    mkdir = os.mkdir
    def competitor(path, mode=0o777, *, dir_fd=None):
        mkdir(path, 0o700, dir_fd=dir_fd)
        (destination / "foreign").write_text("competitor")
        return mkdir(path, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "mkdir", competitor)
    with pytest.raises(FileExistsError):
        prepare_dataset(index, roots=roots, dataset_name="AvesChilenas", output_dir=destination)
    assert [p.name for p in destination.iterdir()] == ["foreign"]
    assert (destination / "foreign").read_text() == "competitor"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700


def test_interrupted_write_is_not_loadable(tmp_path, monkeypatch):
    index, roots, _ = fixture_index(tmp_path)
    destination = tmp_path / "prepared"
    # Inject OS durability failure at the filesystem seam, not a private helper.
    def interrupted(fd):
        raise OSError("interrupted")
    monkeypatch.setattr(os, "fsync", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        prepare_dataset(index, roots=roots, dataset_name="AvesChilenas", output_dir=destination)
    assert destination.is_dir()
    assert not (destination / ".complete").exists()
    with pytest.raises((OSError, ValueError)):
        load_prepared_dataset(destination, roots=roots, dataset_name="AvesChilenas")


@pytest.mark.parametrize("corruption", ["missing", "duplicates", "groups", "marker"])
def test_loader_requires_marker_and_valid_trio(tmp_path, corruption):
    index, roots, _ = fixture_index(tmp_path)
    destination = tmp_path / "prepared"
    prepare_dataset(index, roots=roots, dataset_name="AvesChilenas", output_dir=destination)
    if corruption == "missing":
        (destination / "test.csv").rename(destination / "missing.csv")
    elif corruption == "marker":
        (destination / ".complete").write_text("not complete")
    elif corruption == "duplicates":
        (destination / "test.csv").write_bytes((destination / "val.csv").read_bytes())
    else:
        frame = pd.read_csv(destination / "test.csv", dtype=str, keep_default_na=False)
        train = pd.read_csv(destination / "train.csv", dtype=str, keep_default_na=False)
        frame["recordist"] = train.iloc[0].recordist
        frame.to_csv(destination / "test.csv", index=False)
    with pytest.raises((OSError, ValueError)):
        load_prepared_dataset(destination, roots=roots, dataset_name="AvesChilenas")


def test_output_must_be_separate_from_audio(tmp_path):
    index, roots, _ = fixture_index(tmp_path)
    destination = roots["raw"] / "prepared"
    with pytest.raises(ValueError, match="separate"):
        prepare_dataset(index, roots=roots, dataset_name="AvesChilenas", output_dir=destination)
    assert not destination.exists()


def test_engine_adapter_accepts_explicit_roots_without_legacy_source(tmp_path):
    from training.prepare_engine_data import prepare_engine_dataset
    index, roots, _ = fixture_index(tmp_path)
    result = prepare_engine_dataset(tmp_path / "unused", index_csv=index, roots=roots,
                                    output_dir=tmp_path / "prepared")
    assert sum(result["counts"].values()) == 12


@pytest.mark.parametrize("mutation", ["metadata", "reorder"])
def test_loader_rejects_structurally_valid_csv_mutation(tmp_path, mutation):
    index, roots, _ = fixture_index(tmp_path)
    destination = tmp_path / "prepared"
    prepare_dataset(index, roots=roots, dataset_name="AvesChilenas", output_dir=destination)
    path = destination / "train.csv"
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if mutation == "metadata":
        frame.loc[0, "extra"] = "changed"
    else:
        frame = frame.iloc[::-1]
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="integrity"):
        load_prepared_dataset(destination, roots=roots, dataset_name="AvesChilenas")


@pytest.mark.parametrize("corruption", ["absent", "malformed", "schema", "dataset", "names", "extra"])
def test_loader_rejects_unsupported_completion_record(tmp_path, corruption):
    import json
    index, roots, _ = fixture_index(tmp_path)
    destination = tmp_path / "prepared"
    prepare_dataset(index, roots=roots, dataset_name="AvesChilenas", output_dir=destination)
    marker = destination / ".complete"
    record = json.loads(marker.read_bytes())
    if corruption == "absent":
        marker.rename(destination / "missing-marker")
    elif corruption == "malformed":
        marker.write_text("complete\n")
    elif corruption == "extra":
        (destination / "extra.csv").write_text("extra")
    else:
        if corruption == "schema":
            record["schema"] = 2
        elif corruption == "dataset":
            record["dataset"] = "engine_diagnostics"
        else:
            record["sha256"]["extra.csv"] = "0" * 64
        marker.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="marker|layout"):
        load_prepared_dataset(destination, roots=roots, dataset_name="AvesChilenas")


def test_engine_cli_explicit_fixture(tmp_path):
    import subprocess
    import sys
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "."}
    command = [sys.executable, "-m", "training.prepare_engine_data"]
    help_result = subprocess.run(command + ["--help"], env=env, capture_output=True, text=True)
    assert help_result.returncode == 0, help_result.stderr
    assert "--index-csv" in help_result.stdout
    missing = subprocess.run(command, env=env, capture_output=True, text=True)
    assert missing.returncode == 2
    assert "--index-csv" in missing.stderr
    assert not list(tmp_path.iterdir())
    index, roots, original = fixture_index(tmp_path)
    destination = tmp_path / "prepared"
    result = subprocess.run(command + ["--index-csv", str(index), "--raw-root", str(roots["raw"]),
                            "--output-dir", str(destination)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    parts = load_prepared_dataset(destination, roots=roots, dataset_name="engine_diagnostics")
    assert [len(part) for part in parts] == [8, 2, 2]
    assert set(pd.concat(parts).file_path) == set(original.file_path)


def test_prepared_path_declares_without_creating():
    path = get_prepared_data_dir("AvesChilenas")
    assert path.parts[-3:] == ("data", "prepared", "AvesChilenas")
    with pytest.raises(ValueError):
        get_prepared_data_dir("../escape")
