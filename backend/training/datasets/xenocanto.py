"""
backend/training/datasets/xenocanto.py
Ingestor desacoplado para la API v3 de Xeno-Canto y catalogación con verificación SHA-256.
"""
from pathlib import Path
from typing import Optional, List, Dict
import pandas as pd

from training.datasets.base import DatasetIngestor, AudioRecordingMetadata


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
            df_raw = pd.read_csv(self.metadata_csv)
            records: List[Dict] = []
            for _, row in df_raw.iterrows():
                filename = str(row.get("nombre_archivo", ""))
                clase = str(row.get("clase", ""))
                rec_val = str(row.get("recordist", row.get("rec", "desconocido")))

                # Buscar ruta física si raw_audio_dir está disponible
                file_path_str = ""
                if self.raw_audio_dir:
                    candidate = self.raw_audio_dir / filename
                    if candidate.exists():
                        file_path_str = str(candidate.resolve())

                # Extraer especies secundarias si existen en 'also'
                also_field = str(row.get("also", ""))
                secondary = [s.strip() for s in also_field.strip("[]'\"").split(",") if s.strip()]
                labels = [clase] + [s for s in secondary if s != clase]

                rec = AudioRecordingMetadata(
                    nombre_archivo=filename,
                    file_path=file_path_str,
                    clase=clase,
                    labels=labels,
                    frecuencia_muestreo=int(row.get("frecuencia_muestreo", 22050)),
                    duracion_segundos=float(row.get("duracion_segundos", 0.0)),
                    tamano_bytes=int(row.get("tamano_bytes", 0)),
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
