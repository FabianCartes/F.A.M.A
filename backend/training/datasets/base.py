"""
backend/training/datasets/base.py
Contrato abstracto para ingestores de datos bioacústicos y esquema canónico de metadatos.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import pandas as pd


class AudioRecordingMetadata(BaseModel):
    """Esquema canónico normalizado para cualquier registro bioacústico."""
    nombre_archivo: str
    file_path: str
    clase: str
    labels: List[str] = Field(default_factory=list)
    frecuencia_muestreo: Optional[int] = None
    duracion_segundos: Optional[float] = None
    tamano_bytes: Optional[int] = None
    hash_archivo: Optional[str] = None
    source_id: Optional[str] = None
    recordist: str
    licencia: Optional[str] = None
    pais: Optional[str] = None
    localidad: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    calidad: Optional[str] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)


class DatasetIngestor(ABC):
    """
    Módulo profundo para descubrimiento, descarga y estandarización de datasets bioacústicos.
    Garantiza una interfaz unificada: ingest() -> pd.DataFrame con esquema canónico.
    """

    @abstractmethod
    def ingest(self, destination_dir: Optional[Path] = None, force_refresh: bool = False) -> pd.DataFrame:
        """
        Ejecuta la ingesta o escaneo y retorna un DataFrame con columnas canónicas.
        """
        pass
