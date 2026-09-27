import os
import sys
from pathlib import Path
import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from backend.training.paths import (
    PathResolver,
    get_project_root,
    get_raw_data_dir,
    get_processed_data_dir,
)
from training.paths import (
    PathResolver as TrainingPathResolver,
    get_project_root as training_get_project_root,
)


def test_get_project_root():
    root = get_project_root()
    assert isinstance(root, Path)
    assert root.is_absolute()
    assert (root / "backend").exists()
    assert (root / "backend" / "training").exists()
    assert training_get_project_root() == root
    assert PathResolver.project_root() == root


def test_get_raw_data_dir_default():
    raw_dir = get_raw_data_dir()
    assert isinstance(raw_dir, Path)
    assert raw_dir.is_absolute()
    assert raw_dir == get_project_root() / "backend" / "data" / "raw"
    assert PathResolver.raw_data_dir() == raw_dir


def test_get_raw_data_dir_with_dataset():
    raw_dataset = get_raw_data_dir("engine_diagnostics")
    assert isinstance(raw_dataset, Path)
    assert raw_dataset.is_absolute()
    assert raw_dataset == get_project_root() / "backend" / "data" / "raw" / "engine_diagnostics"
    assert PathResolver.raw_data_dir("engine_diagnostics") == raw_dataset


def test_get_processed_data_dir_default():
    processed_dir = get_processed_data_dir()
    assert isinstance(processed_dir, Path)
    assert processed_dir.is_absolute()
    assert processed_dir == get_project_root() / "backend" / "data" / "processed"
    assert PathResolver.processed_data_dir() == processed_dir


def test_get_processed_data_dir_with_dataset():
    processed_dataset = get_processed_data_dir("engine_diagnostics")
    assert isinstance(processed_dataset, Path)
    assert processed_dataset.is_absolute()
    assert (
        processed_dataset
        == get_project_root() / "backend" / "data" / "processed" / "engine_diagnostics"
    )
    assert PathResolver.processed_data_dir("engine_diagnostics") == processed_dataset


def test_paths_independent_of_cwd(monkeypatch, tmp_path):
    root_before = get_project_root()
    raw_before = get_raw_data_dir("test_ds")
    processed_before = get_processed_data_dir("test_ds")

    # Change working directory to an arbitrary temporary directory
    monkeypatch.chdir(tmp_path)
    assert Path.cwd() == tmp_path

    assert get_project_root() == root_before
    assert get_raw_data_dir("test_ds") == raw_before
    assert get_processed_data_dir("test_ds") == processed_before
    assert PathResolver.raw_data_dir("test_ds") == raw_before
