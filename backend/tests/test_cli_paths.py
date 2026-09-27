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


def test_training_scripts_no_hardcoded_root_data_dir():
    root = get_project_root()
    scripts = [
        root / "backend" / "train_car_engine_model.py",
        root / "backend" / "train_and_ensemble_engines.py",
        root / "backend" / "train_v2_and_compare.py",
    ]
    for script in scripts:
        if not script.exists():
            continue
        content = script.read_text(encoding="utf-8")
        assert 'Path("data/engine_diagnostics")' not in content, (
            f"Script {script.name} contiene ruta hardcodeada 'data/engine_diagnostics'"
        )
        assert "get_raw_data_dir" in content, (
            f"Script {script.name} no utiliza get_raw_data_dir"
        )


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
    raw_aves = get_raw_data_dir("AvesChilenas")
    assert raw_aves.exists() and raw_aves.is_dir(), f"No existe {raw_aves}"

    for required_file in ["metadata.csv", "train.csv", "val.csv", "test.csv"]:
        fpath = raw_aves / required_file
        assert fpath.exists() and fpath.is_file(), f"Falta {required_file} en {raw_aves}"

    proc_wav = get_processed_data_dir("AvesChilenas") / "processed_wav"
    assert proc_wav.exists() and proc_wav.is_dir(), f"No existe {proc_wav}"

    raw_proc_symlink = raw_aves / "processed_wav"
    assert raw_proc_symlink.exists(), f"No existe el symlink de compatibilidad en {raw_proc_symlink}"
    assert raw_proc_symlink.resolve() == proc_wav.resolve()


def test_ingestion_service_both_datasets_synced():
    from app.services.ingestion import IngestionService
    datasets = IngestionService().list_datasets()
    ds_map = {d["name"]: d for d in datasets}

    assert "engine_diagnostics" in ds_map, "engine_diagnostics debe estar en list_datasets()"
    assert ds_map["engine_diagnostics"]["is_synced"] is True, "engine_diagnostics debe reportar is_synced: True"

    assert "AvesChilenas" in ds_map, "AvesChilenas debe estar en list_datasets()"
    assert ds_map["AvesChilenas"]["is_synced"] is True, "AvesChilenas debe reportar is_synced: True"
