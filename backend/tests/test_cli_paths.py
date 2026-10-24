from pathlib import Path
import inspect
import pytest

from training.paths import get_raw_data_dir, get_project_root
from training.prepare_engine_data import prepare_engine_dataset


def test_prepare_engine_dataset_default_path():
    sig = inspect.signature(prepare_engine_dataset)
    param = sig.parameters["source_dir"]
    # Default is either None (resolving to get_raw_data_dir) or get_raw_data_dir directly
    if param.default is not inspect.Parameter.empty and param.default is not None:
        assert Path(param.default).resolve() == get_raw_data_dir("engine_diagnostics")


def test_poc_scripts_no_hardcoded_root_data_dir():
    root = get_project_root()
    poc_dir = root / "backend" / "poc"
    scripts = [
        poc_dir / "train.py",
        poc_dir / "evaluate.py",
        poc_dir / "benchmark.py",
        poc_dir / "download.py",
        poc_dir / "sanitize.py",
    ]
    for script in scripts:
        assert script.exists(), f"Script {script.name} no existe"
        content = script.read_text(encoding="utf-8")
        assert 'Path("data/' not in content and 'Path("data")' not in content, (
            f"Script {script.name} contiene referencia hardcodeada a Path('data...')"
        )
        assert '"data/raw"' not in content and "'data/raw'" not in content, (
            f"Script {script.name} contiene referencia hardcodeada a 'data/raw'"
        )
        assert '"data/metadata.csv"' not in content and "'data/metadata.csv'" not in content, (
            f"Script {script.name} contiene referencia hardcodeada a 'data/metadata.csv'"
        )
        assert '"data/test.csv"' not in content and "'data/test.csv'" not in content, (
            f"Script {script.name} contiene referencia hardcodeada a 'data/test.csv'"
        )
        assert '"data/processed_wav"' not in content and "'data/processed_wav'" not in content, (
            f"Script {script.name} contiene referencia hardcodeada a 'data/processed_wav'"
        )


def test_root_data_dir_completely_removed():
    root = get_project_root()
    root_data = root / "data"
    assert not root_data.exists(), f"La carpeta raíz {root_data} no debe existir tras la unificación"


def test_aves_chilenas_unified_paths():
    from training.paths import get_raw_data_dir, get_processed_data_dir
    raw = get_raw_data_dir("AvesChilenas")
    processed = get_processed_data_dir("AvesChilenas")
    assert raw.is_absolute() and processed.is_absolute()
    assert raw.name == processed.name == "AvesChilenas"
    assert raw.parent.name == "raw" and processed.parent.name == "processed"
    assert raw != processed


def test_local_inventory_does_not_assert_remote_synchronization(tmp_path):
    from app.services.ingestion import IngestionService
    root = tmp_path/"raw"
    for name in ("AvesChilenas", "engine_diagnostics"):
        directory = root/name/"fixture"
        directory.mkdir(parents=True)
        (directory/"sample.wav").write_bytes(b"synthetic inventory bytes")
    service = IngestionService(local_base_dir=root, bucket_name="synthetic-test-bucket")
    # The external boundary reports unavailability, preserving local visibility.
    from unittest.mock import patch
    with patch("google.cloud.storage.Client", side_effect=RuntimeError("synthetic unavailable")):
        datasets = service.list_datasets()
    assert {d["id"] for d in datasets} == {"AvesChilenas", "engine_diagnostics"}
    assert all(d["is_synced"] is False and d["gcs_available"] is False and d["local_file_count"] == 1 for d in datasets)
