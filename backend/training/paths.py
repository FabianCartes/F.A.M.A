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
    Retorna la ruta absoluta a backend/data/raw/[dataset_name].
    """
    raw_dir = (get_project_root() / "backend" / "data" / "raw").resolve()
    if dataset_name:
        return (raw_dir / dataset_name).resolve()
    return raw_dir


def get_processed_data_dir(dataset_name: Optional[str] = None) -> Path:
    """
    Retorna la ruta absoluta a backend/data/processed/[dataset_name].
    """
    proc_dir = (get_project_root() / "backend" / "data" / "processed").resolve()
    if dataset_name:
        return (proc_dir / dataset_name).resolve()
    return proc_dir


class PathResolver:
    """
    Fachada estática para resolución de rutas canónicas en el sistema.
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
