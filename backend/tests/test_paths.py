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
    get_checkpoints_dir,
)
from training.paths import (
    PathResolver as TrainingPathResolver,
    get_project_root as training_get_project_root,
    get_checkpoints_dir as training_get_checkpoints_dir,
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


def test_get_checkpoints_dir_default():
    ckpts_dir = get_checkpoints_dir()
    assert isinstance(ckpts_dir, Path)
    assert ckpts_dir.is_absolute()
    assert ckpts_dir == get_project_root() / "backend" / "checkpoints"
    assert PathResolver.checkpoints_dir() == ckpts_dir
    assert training_get_checkpoints_dir() == ckpts_dir
    assert TrainingPathResolver.checkpoints_dir() == ckpts_dir


def test_get_checkpoints_dir_with_subpath():
    subpath = get_checkpoints_dir("patagonian-birds-resnet34")
    assert isinstance(subpath, Path)
    assert subpath.is_absolute()
    assert (
        subpath
        == get_project_root() / "backend" / "checkpoints" / "patagonian-birds-resnet34"
    )
    assert PathResolver.checkpoints_dir("patagonian-birds-resnet34") == subpath


@pytest.mark.parametrize("stage", ["raw", "processed"])
@pytest.mark.parametrize("alias_location", ["ancestor", "base", "dataset", "code_ancestor"])
def test_configured_root_alias_is_rejected_by_consumer(monkeypatch, tmp_path, stage, alias_location):
    from training import paths
    from dataset_references import resolve_reference

    backend = tmp_path / "backend"
    (backend / "training").mkdir(parents=True)
    monkeypatch.setattr(paths, "__file__", str(backend / "training" / "paths.py"))
    physical = tmp_path / "physical"
    physical.mkdir()
    if alias_location == "code_ancestor":
        backend.rename(tmp_path / "physical-backend")
        backend.symlink_to(tmp_path / "physical-backend", target_is_directory=True)
        (backend / "data" / stage / "Fixture").mkdir(parents=True)
    elif alias_location == "ancestor":
        (backend / "data").symlink_to(physical, target_is_directory=True)
    else:
        (backend / "data").mkdir()
        alias = backend / "data" / stage
        if alias_location == "dataset":
            alias.mkdir()
            alias = alias / "Fixture"
        alias.symlink_to(physical, target_is_directory=True)
    getter = paths.get_raw_data_dir if stage == "raw" else paths.get_processed_data_dir
    root = getter("Fixture")
    if stage == "processed":
        root = root / "processed_wav"
    root.mkdir(parents=True, exist_ok=True)
    (root / "fixture.wav").write_bytes(b"temporary audio")
    with pytest.raises(ValueError, match="symlinks"):
        resolve_reference("fixture.wav", stage, {stage: root})


@pytest.mark.parametrize("stage", ["raw", "processed"])
def test_declared_stage_map_resolves_only_selected_root(monkeypatch, tmp_path, stage):
    from training import paths
    from dataset_references import resolve_reference

    backend = tmp_path / "backend"
    (backend / "training").mkdir(parents=True)
    monkeypatch.setattr(paths, "__file__", str(backend / "training" / "paths.py"))
    selected = backend / "data" / stage / "Fixture"
    if stage == "processed":
        selected = selected / "processed_wav"
    selected.mkdir(parents=True)
    (selected / "fixture.wav").write_bytes(b"temporary audio")
    roots = paths.get_dataset_roots("Fixture")
    assert roots == {"raw": backend / "data" / "raw" / "Fixture",
                     "processed": backend / "data" / "processed" / "Fixture" / "processed_wav"}
    assert not roots["processed" if stage == "raw" else "raw"].exists()
    monkeypatch.chdir(tmp_path)
    assert resolve_reference("fixture.wav", stage, roots) == selected / "fixture.wav"


@pytest.mark.parametrize("module_name", ["backend.training.paths", "training.paths"])
@pytest.mark.parametrize("stage", ["raw", "processed"])
@pytest.mark.parametrize("interface", ["getter", "wrapper"])
@pytest.mark.parametrize("root_kind", ["ancestor", "base", "dataset", "code_ancestor", "physical", "missing"])
def test_public_dataset_locator_preserves_declared_spelling(
    monkeypatch, tmp_path, module_name, stage, interface, root_kind
):
    import importlib

    paths = importlib.import_module(module_name)
    backend = tmp_path / "backend"
    physical = tmp_path / "physical"
    physical.mkdir()
    if root_kind == "code_ancestor":
        (physical / "training").mkdir()
        backend.symlink_to(physical, target_is_directory=True)
    else:
        (backend / "training").mkdir(parents=True)
    monkeypatch.setattr(paths, "__file__", str(backend / "training" / "paths.py"))
    if root_kind == "ancestor":
        (backend / "data").symlink_to(physical, target_is_directory=True)
    elif root_kind in ("base", "dataset"):
        (backend / "data").mkdir()
        alias = backend / "data" / stage
        if root_kind == "dataset":
            alias.mkdir()
            alias = alias / "Fixture"
        alias.symlink_to(physical, target_is_directory=True)
    expected_base = backend / "data" / stage
    expected_dataset = expected_base / "Fixture"
    if root_kind != "missing":
        expected_dataset.mkdir(parents=True, exist_ok=True)
    getter_name = "get_raw_data_dir" if stage == "raw" else "get_processed_data_dir"
    wrapper_name = "raw_data_dir" if stage == "raw" else "processed_data_dir"
    locate = (getattr(paths, getter_name) if interface == "getter"
              else getattr(paths.PathResolver, wrapper_name))
    assert locate() == expected_base
    assert locate("Fixture") == expected_dataset
    monkeypatch.chdir(physical)
    assert locate("Fixture") == expected_dataset
    if root_kind == "missing":
        assert not expected_dataset.exists()  # A declaration is not validation.


def test_paths_independent_of_cwd(monkeypatch, tmp_path):
    root_before = get_project_root()
    raw_before = get_raw_data_dir("test_ds")
    processed_before = get_processed_data_dir("test_ds")
    ckpts_before = get_checkpoints_dir("test_model")

    # Change working directory to an arbitrary temporary directory
    monkeypatch.chdir(tmp_path)
    assert Path.cwd() == tmp_path

    assert get_project_root() == root_before
    assert get_raw_data_dir("test_ds") == raw_before
    assert get_processed_data_dir("test_ds") == processed_before
    assert get_checkpoints_dir("test_model") == ckpts_before
    assert PathResolver.raw_data_dir("test_ds") == raw_before
    assert PathResolver.checkpoints_dir("test_model") == ckpts_before

