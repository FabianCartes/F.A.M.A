"""
backend/training/paths.py
Módulo canónico de resolución de rutas del proyecto (PathResolver).
Proporciona rutas absolutas e independientes del directorio de trabajo actual (cwd).
"""
from pathlib import Path
from typing import Optional


def get_project_root() -> Path:
    """
    Retorna la raíz canónica del repositorio de forma agnóstica a cwd.
    Busca de forma determinista la carpeta raíz del proyecto basándose
    en la ubicación de este archivo y marcadores del repositorio.
    """
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists() or ((parent / "backend").exists() and (parent / "docs").exists()):
            return parent
    return Path(__file__).resolve().parent.parent.parent


def get_raw_data_dir(dataset_name: Optional[str] = None) -> Path:
    """
    Declara la ruta absoluta a backend/data/raw/[dataset_name], sin resolver enlaces.
    Conserva la escritura de la raíz seleccionada desde la ubicación del código
    o el fallback del proyecto, también al añadir dataset_name. No garantiza
    existencia ni seguridad física: resolve_reference valida la etapa elegida.
    Las raíces con alias no están soportadas para la asociación canónica de datasets.
    """
    backend_raw = Path(__file__).absolute().parent.parent / "data" / "raw"
    if backend_raw.exists():
        raw_dir = backend_raw
    else:
        raw_dir = get_project_root() / "backend" / "data" / "raw"
    if dataset_name:
        return raw_dir / dataset_name
    return raw_dir


def get_processed_data_dir(dataset_name: Optional[str] = None) -> Path:
    """
    Declara la ruta absoluta a backend/data/processed/[dataset_name], sin resolver enlaces.
    Conserva la escritura de la raíz seleccionada desde la ubicación del código
    o el fallback del proyecto, también al añadir dataset_name. No garantiza
    existencia ni seguridad física; la raíz de audio derivado añade processed_wav
    y debe validarse con resolve_reference. Los alias no están soportados para
    la asociación canónica de datasets.
    """
    backend_proc = Path(__file__).absolute().parent.parent / "data" / "processed"
    if backend_proc.exists():
        proc_dir = backend_proc
    else:
        proc_dir = get_project_root() / "backend" / "data" / "processed"
    if dataset_name:
        return proc_dir / dataset_name
    return proc_dir


def get_prepared_data_dir(dataset_name: str) -> Path:
    """Declare the separate prepared destination; never create directories."""
    if (not isinstance(dataset_name, str) or not dataset_name
            or dataset_name in (".", "..") or "/" in dataset_name
            or "\\" in dataset_name):
        raise ValueError("dataset_name must be a single directory name")
    return Path(__file__).absolute().parent.parent / "data" / "prepared" / dataset_name


def get_dataset_roots(dataset_name: str) -> dict[str, Path]:
    """Declare audio roots with the same unresolved spelling as the public getters.

    Raw maps to the dataset directory; processed maps to its processed_wav
    directory. These declarations prove neither existence nor physical safety.
    resolve_reference validates only the selected stage and rejects root aliases;
    aliases are unsupported for canonical dataset association. Custom sources
    must instead supply their own explicit physical root mapping.
    """
    return {"raw": get_raw_data_dir(dataset_name),
            "processed": get_processed_data_dir(dataset_name) / "processed_wav"}


def get_checkpoints_dir(subpath: Optional[str] = None) -> Path:
    """
    Retorna la ruta absoluta a backend/checkpoints/[subpath].
    Resuelve de forma robusta tanto en host local como dentro de contenedor Docker (/app).
    """
    backend_ckpts = (Path(__file__).resolve().parent.parent / "checkpoints").resolve()
    if backend_ckpts.exists():
        ckpts_dir = backend_ckpts
    else:
        ckpts_dir = (get_project_root() / "backend" / "checkpoints").resolve()
    if subpath:
        return (ckpts_dir / subpath).resolve()
    return ckpts_dir


class PathResolver:
    """
    Fachada estática para los localizadores públicos del sistema.
    raw_data_dir y processed_data_dir conservan la escritura declarada, sin
    resolver enlaces ni validar seguridad física. project_root y checkpoints_dir
    mantienen su resolución previa; no comparten el contrato de raíces de audio.
    """

    @staticmethod
    def project_root() -> Path:
        return get_project_root()

    @staticmethod
    def raw_data_dir(dataset_name: Optional[str] = None) -> Path:
        return get_raw_data_dir(dataset_name)

    @staticmethod
    def processed_data_dir(dataset_name: Optional[str] = None) -> Path:
        return get_processed_data_dir(dataset_name)

    @staticmethod
    def checkpoints_dir(subpath: Optional[str] = None) -> Path:
        return get_checkpoints_dir(subpath)

