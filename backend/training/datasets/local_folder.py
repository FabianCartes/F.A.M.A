"""
backend/training/datasets/local_folder.py
Ingestor polimórfico para conjuntos de datos locales (carpetas estructuradas o soundscapes PAM con anotaciones).
"""
from pathlib import Path
from typing import Optional, List, Dict
import pandas as pd
import soundfile as sf

from training.datasets.base import DatasetIngestor, AudioRecordingMetadata

SUPPORTED_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg"}


class LocalFolderPAMIngestor(DatasetIngestor):
    """
    Ingestor para directorios locales.
    Soporta:
    1. Modo Estructurado: 'source_dir/<clase>/<audio_id>.wav'
    2. Modo PAM / Anotaciones: Archivos en 'source_dir/' con 'annotations_csv' mapeando detecciones concurrentes.
    """

    def __init__(
        self,
        source_dir: Path,
        annotations_csv: Optional[Path] = None,
        default_recordist_prefix: str = "rec_local",
    ):
        self.source_dir = Path(source_dir)
        self.annotations_csv = Path(annotations_csv) if annotations_csv else None
        self.default_recordist_prefix = default_recordist_prefix

    def ingest(self, destination_dir: Optional[Path] = None, force_refresh: bool = False) -> pd.DataFrame:
        if not self.source_dir.exists():
            raise FileNotFoundError(f"Directorio de origen no encontrado: {self.source_dir}")

        if self.annotations_csv and self.annotations_csv.exists():
            return self._ingest_with_annotations()
        else:
            return self._ingest_species_directories()

    def _get_audio_info(self, file_path: Path) -> tuple[float, int]:
        try:
            info = sf.info(file_path)
            return float(info.duration), int(info.samplerate)
        except Exception:
            return 0.0, 0

    def _ingest_species_directories(self) -> pd.DataFrame:
        records: List[Dict] = []
        for file_path in self.source_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                clase = file_path.parent.name
                duration, sr = self._get_audio_info(file_path)
                rec = AudioRecordingMetadata(
                    nombre_archivo=file_path.name,
                    file_path=str(file_path.resolve()),
                    clase=clase,
                    labels=[clase],
                    frecuencia_muestreo=sr,
                    duracion_segundos=duration,
                    tamano_bytes=file_path.stat().st_size,
                    recordist=f"{self.default_recordist_prefix}_{clase}",
                    source_id=file_path.stem,
                )
                records.append(rec.model_dump())

        return pd.DataFrame(records)

    def _ingest_with_annotations(self) -> pd.DataFrame:
        ann_df = pd.read_csv(self.annotations_csv)
        # Identificar columnas
        fn_col = "filename" if "filename" in ann_df.columns else "nombre_archivo"
        sp_col = "species" if "species" in ann_df.columns else "clase"
        rec_col = "recordist" if "recordist" in ann_df.columns else "sensor_id"

        records: List[Dict] = []
        # Agrupar por nombre_archivo para consolidar multi-label
        grouped = ann_df.groupby(fn_col)
        for filename, group in grouped:
            # Buscar archivo físico en source_dir
            matches = list(self.source_dir.rglob(str(filename)))
            if not matches:
                continue
            file_path = matches[0]
            duration, sr = self._get_audio_info(file_path)

            species_list = list(group[sp_col].dropna().unique())
            primary_clase = species_list[0] if species_list else "Desconocido"
            recordist_val = str(group[rec_col].iloc[0]) if rec_col in group.columns else f"{self.default_recordist_prefix}_sensor"

            rec = AudioRecordingMetadata(
                nombre_archivo=str(filename),
                file_path=str(file_path.resolve()),
                clase=primary_clase,
                labels=species_list,
                frecuencia_muestreo=sr,
                duracion_segundos=duration,
                tamano_bytes=file_path.stat().st_size,
                recordist=recordist_val,
                source_id=file_path.stem,
            )
            records.append(rec.model_dump())

        return pd.DataFrame(records)
