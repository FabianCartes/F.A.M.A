"""Local raw import: directory discovery, canonical index, or explicit PAM annotations."""
from pathlib import Path
import os
import re
import ast
from typing import Optional
import pandas as pd
import soundfile as sf

from training.datasets.base import DatasetIngestor, AudioRecordingMetadata
from dataset_references import reference_from_path, resolve_reference

SUPPORTED_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg"}


class LocalFolderPAMIngestor(DatasetIngestor):
    """Import under an explicit physical raw root.

    Without annotations, discover class directories. With annotations, default to
    canonical file_path/file_stage rows. Filename-only PAM annotations require
    input_mode='pam_filename': a basename must match exactly one discovered file.
    Discovery excludes linked directories and rejects linked audio files.
    """

    def __init__(self, source_dir: Path, annotations_csv: Optional[Path] = None,
                 default_recordist_prefix: str = "rec_local", *, input_mode: str = "canonical"):
        self.source_dir = Path(source_dir)
        self.annotations_csv = Path(annotations_csv) if annotations_csv else None
        self.default_recordist_prefix = default_recordist_prefix
        if input_mode not in ("canonical", "pam_filename"):
            raise ValueError("input_mode must be canonical or pam_filename")
        self.input_mode = input_mode
        self.roots = {"raw": self.source_dir}

    def ingest(self, destination_dir: Optional[Path] = None, force_refresh: bool = False) -> pd.DataFrame:
        if (not self.source_dir.is_absolute()
                or any(p.is_symlink() for p in (self.source_dir, *self.source_dir.parents))):
            raise ValueError("source_dir must be an absolute physical raw root")
        if not self.source_dir.is_dir():
            raise FileNotFoundError("Source directory not found")
        if self.annotations_csv:
            return self._ingest_with_annotations()
        return self._ingest_species_directories()

    def _get_audio_info(self, file_path: Path) -> tuple[float, int]:
        try:
            info = sf.info(file_path)
            return float(info.duration), int(info.samplerate)
        except Exception:
            return 0.0, 0

    def _discovered_audio(self):
        for directory, folders, files in os.walk(self.source_dir, followlinks=False):
            folders[:] = [name for name in folders if not (Path(directory) / name).is_symlink()]
            for name in files:
                path = Path(directory) / name
                if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    reference_from_path(path, "raw", self.roots)
                    yield path

    def _ingest_species_directories(self) -> pd.DataFrame:
        records = []
        for path in self._discovered_audio():
            clase = path.parent.name
            duration, sr = self._get_audio_info(path)
            source_group = re.sub(r'_\d+$', '', path.stem)
            rec = AudioRecordingMetadata(
                nombre_archivo=path.name, **reference_from_path(path, "raw", self.roots),
                clase=clase, labels=[clase], frecuencia_muestreo=sr,
                duracion_segundos=duration, tamano_bytes=path.stat().st_size,
                recordist=f"{self.default_recordist_prefix}_{clase}_{source_group}",
                source_id=path.stem,
            )
            records.append(rec.model_dump())
        return pd.DataFrame(records)

    def _ingest_with_annotations(self) -> pd.DataFrame:
        ann_df = pd.read_csv(self.annotations_csv, keep_default_na=False,
                             dtype={field: str for field in ("file_path", "file_stage", "nombre_archivo",
                                                            "xc_id", "source_id", "hash_archivo")})
        if self.input_mode == "canonical":
            if not {"file_path", "file_stage"}.issubset(ann_df.columns):
                raise ValueError("Canonical CSV requires file_path and file_stage")
            records = []
            for fields in ann_df.to_dict("records"):
                if fields["file_stage"] != "raw":
                    raise ValueError("Local import index must declare raw stage")
                path = resolve_reference(fields["file_path"], fields["file_stage"], self.roots)
                duration, sr = self._get_audio_info(path)
                # Empty optional CSV cells are null metadata, never absent references.
                for field in ("frecuencia_muestreo", "duracion_segundos", "tamano_bytes", "lat", "lon"):
                    if fields.get(field) == "":
                        fields.pop(field)
                for field in ("labels", "extra_metadata"):
                    if isinstance(fields.get(field), str):
                        try:
                            fields[field] = ast.literal_eval(fields[field])
                        except (ValueError, SyntaxError):
                            raise ValueError("Invalid structured metadata field") from None
                fields.setdefault("recordist", f"{self.default_recordist_prefix}_sensor")
                fields.setdefault("source_id", fields.get("xc_id", path.stem))
                fields.setdefault("labels", [fields["clase"]])
                fields.setdefault("duracion_segundos", duration)
                fields.setdefault("frecuencia_muestreo", sr)
                fields.setdefault("tamano_bytes", path.stat().st_size)
                records.append(AudioRecordingMetadata(**fields).model_dump())
            return pd.DataFrame(records)

        discovered = list(self._discovered_audio())
        fn_col = "filename" if "filename" in ann_df.columns else "nombre_archivo"
        sp_col = "species" if "species" in ann_df.columns else "clase"
        rec_col = "recordist" if "recordist" in ann_df.columns else "sensor_id"
        records = []
        for filename, group in ann_df.groupby(fn_col):
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise ValueError("PAM annotations require a basename")
            matches = [path for path in discovered if path.name == filename]
            if len(matches) != 1:
                raise ValueError("PAM filename must identify exactly one source audio")
            path = matches[0]
            duration, sr = self._get_audio_info(path)
            species = list(group[sp_col].dropna().unique())
            recordist = str(group[rec_col].iloc[0]) if rec_col in group.columns else f"{self.default_recordist_prefix}_sensor"
            rec = AudioRecordingMetadata(
                nombre_archivo=filename, **reference_from_path(path, "raw", self.roots),
                clase=species[0] if species else "Desconocido", labels=species,
                frecuencia_muestreo=sr, duracion_segundos=duration,
                tamano_bytes=path.stat().st_size, recordist=recordist, source_id=path.stem,
            )
            records.append(rec.model_dump())
        return pd.DataFrame(records)
