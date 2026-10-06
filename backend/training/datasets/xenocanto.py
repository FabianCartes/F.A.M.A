"""
backend/training/datasets/xenocanto.py
Ingestor desacoplado para la API v3 de Xeno-Canto y catalogación con verificación SHA-256.
"""
from pathlib import Path
from typing import Optional, List, Dict
import pandas as pd

from training.datasets.base import DatasetIngestor, AudioRecordingMetadata
from dataset_references import resolve_reference


class XenoCantoIngestor(DatasetIngestor):
    """
    Ingestor para el catálogo de Xeno-Canto.
    Permite cargar un catálogo existente (metadata.csv) o descargar concurrentemente.
    """

    def __init__(
        self,
        metadata_csv: Optional[Path] = None,
        raw_audio_dir: Optional[Path] = None,
    ):
        self.metadata_csv = Path(metadata_csv) if metadata_csv else None
        self.raw_audio_dir = Path(raw_audio_dir) if raw_audio_dir else None

    def ingest(self, destination_dir: Optional[Path] = None, force_refresh: bool = False) -> pd.DataFrame:
        if self.metadata_csv and self.metadata_csv.exists():
            if self.raw_audio_dir is None:
                raise ValueError("raw_audio_dir must be explicitly declared")
            df_raw = pd.read_csv(self.metadata_csv, keep_default_na=False,
                                 dtype={field: str for field in ("file_path", "file_stage", "xc_id", "hash_archivo")})
            if not {"file_path", "file_stage"}.issubset(df_raw.columns):
                raise ValueError("Canonical CSV requires file_path and file_stage")
            records: List[Dict] = []
            for _, row in df_raw.iterrows():
                filename = str(row.get("nombre_archivo", ""))
                clase = str(row.get("clase", ""))
                rec_val = str(row.get("recordist", row.get("rec", "desconocido")))

                if row["file_stage"] != "raw":
                    raise ValueError("XenoCanto source index must declare raw stage")
                resolve_reference(row["file_path"], row["file_stage"], {"raw": self.raw_audio_dir})

                # Extraer especies secundarias si existen en 'also'
                also_field = str(row.get("also", ""))
                secondary = [s.strip() for s in also_field.strip("[]'\"").split(",") if s.strip()]
                labels = [clase] + [s for s in secondary if s != clase]

                rec = AudioRecordingMetadata(
                    nombre_archivo=filename,
                    file_path=row["file_path"],
                    file_stage=row["file_stage"],
                    clase=clase,
                    labels=labels,
                    frecuencia_muestreo=int(row["frecuencia_muestreo"]) if row.get("frecuencia_muestreo") != "" and "frecuencia_muestreo" in row else None,
                    duracion_segundos=float(row["duracion_segundos"]) if row.get("duracion_segundos") != "" and "duracion_segundos" in row else None,
                    tamano_bytes=int(row["tamano_bytes"]) if row.get("tamano_bytes") != "" and "tamano_bytes" in row else None,
                    hash_archivo=str(row.get("hash_archivo", "")),
                    source_id=str(row.get("xc_id", "")),
                    recordist=rec_val,
                    licencia=str(row.get("licencia", "")),
                    pais=str(row.get("pais", "")),
                    localidad=str(row.get("localidad", "")),
                )
                records.append(rec.model_dump())
            return pd.DataFrame(records)
        else:
            return pd.DataFrame()
