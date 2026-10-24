import os
import asyncio
import base64
import hashlib
import io
import tempfile
import google_crc32c
import soundfile as sf
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from google.cloud import storage
from google.api_core.exceptions import PreconditionFailed
from app.configuration import get_configuration, storage_bucket


class IngestionValidationError(ValueError):
    """Invalid ingestion input, distinct from provider/transport errors."""


class IngestionConfigurationError(RuntimeError):
    """Unavailable upload policy; never expose environment values to callers."""


class IngestionPayloadTooLarge(IngestionValidationError):
    """The configured file or aggregate upload limit was exceeded."""


class IngestionAudioError(IngestionValidationError):
    """An upload is not a supported, structurally readable audio recording."""


class IngestionDatasetUnavailable(IngestionValidationError):
    """The requested cloud dataset has no downloadable audio."""

# ============================================================================
# CONFIGURACIÓN DE ENTORNO Y RUTAS BASE
# ============================================================================
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_BUCKET_NAME = get_configuration().bucket_name

try:
    from training.paths import get_raw_data_dir, get_processed_data_dir
    DEFAULT_LOCAL_RAW_DIR = get_raw_data_dir()
    DEFAULT_LOCAL_PROCESSED_DIR = get_processed_data_dir()
except ImportError:
    DEFAULT_LOCAL_RAW_DIR = _BACKEND_DIR / "data" / "raw"
    DEFAULT_LOCAL_PROCESSED_DIR = _BACKEND_DIR / "data" / "processed"


class IngestionService:
    """
    Servicio profundo de ingesta bidireccional entre Google Cloud Storage y el entorno local.
    Cumple con el requerimiento funcional RF_02, RF_03 y de seguridad RNF_03:
    - Descarga masiva selectiva (sólo archivos nuevos o actualizados).
    - Mantiene sincronizado el Data Lake en la nube con el almacenamiento local para entrenamiento.
    - Sube nuevos audios y datasets estructurados a GCS.
    - Dispara opcionalmente la extracción de espectrogramas Mel a tensores matemáticos.
    - Persiste metadatos en tablas 'conjunto_datos' y 'audio' en PostgreSQL (Tablas 6.4 y 6.5).
    """

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        local_base_dir: Optional[Path] = None,
        local_processed_dir: Optional[Path] = None,
    ):
        self.bucket_name = bucket_name or get_configuration().bucket_name
        self.local_base_dir = Path(local_base_dir or DEFAULT_LOCAL_RAW_DIR)
        self.local_processed_dir = Path(local_processed_dir or DEFAULT_LOCAL_PROCESSED_DIR)

    def _get_client(self) -> storage.Client:
        storage_bucket(self.bucket_name)
        return storage.Client()

    def get_storage_status(self) -> Dict[str, Any]:
        """
        Verifica la conectividad con el bucket de GCS y calcula estadísticas globales de objetos.
        """
        try:
            client = self._get_client()
            total_objects = total_bytes = 0
            for blob in client.list_blobs(self.bucket_name):
                total_objects += 1
                total_bytes += blob.size or 0
            return {
                "connected": True,
                "bucket": self.bucket_name,
                "total_objects": total_objects,
                "total_bytes": total_bytes,
                "error": None,
            }
        except Exception as exc:
            return {
                "connected": False,
                "bucket": self.bucket_name,
                "total_objects": 0,
                "total_bytes": 0,
                "error": str(exc),
            }

    def list_local_datasets(self, gcs_available: bool = False,
                            dataset_names: Optional[set[str]] = None) -> List[Dict[str, Any]]:
        """
        Escanea self.local_base_dir (DEFAULT_LOCAL_RAW_DIR), agrupa clases por subdirectorio,
        cuenta archivos de audio (.wav, .mp3, .flac, .ogg), calcula el tamaño total en bytes
        y retorna la lista de datasets locales estructurados con metadatos completos.
        """
        if not self.local_base_dir.exists() or not self.local_base_dir.is_dir():
            return []

        SUPPORTED_EXTS = {".wav", ".mp3", ".flac", ".ogg"}
        local_datasets = []

        entries = (sorted(self.local_base_dir.iterdir()) if dataset_names is None
                   else [self.local_base_dir / name for name in sorted(dataset_names)])
        for entry in entries:
            ds_name = entry.name
            if dataset_names is not None and not entry.is_dir():
                entry = self.local_base_dir / ds_name.lower().replace(" ", "_")
            if not entry.is_dir() or entry.name.startswith(".") or entry.name.startswith("__"):
                continue
            if not entry.resolve().is_relative_to(self.local_base_dir.resolve()):
                continue

            classes_set = set()
            file_count = 0
            total_size_bytes = 0
            latest_mtime = 0.0

            for f in sorted(entry.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                    rel_parents = f.relative_to(entry).parts[:-1]
                    if rel_parents:
                        class_name = rel_parents[-1]
                    else:
                        class_name = "General"

                    classes_set.add(class_name)
                    file_count += 1
                    try:
                        stat = f.stat()
                        total_size_bytes += stat.st_size
                        if stat.st_mtime > latest_mtime:
                            latest_mtime = stat.st_mtime
                    except OSError:
                        pass

            if file_count > 0:
                is_ind = any(k in ds_name.lower() for k in ["engine", "motor", "maquinaria", "industrial"])
                classes_list = sorted(list(classes_set))
                last_mod_iso = (
                    datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat()
                    if latest_mtime > 0
                    else None
                )

                local_datasets.append({
                    "id": ds_name,
                    "name": ds_name,
                    "classes": classes_list,
                    "class_count": len(classes_list),
                    "file_count": file_count,
                    "local_file_count": file_count,
                    "total_size_bytes": total_size_bytes,
                    "last_modified": last_mod_iso,
                    "gcs_file_count": 0 if gcs_available else None,
                    "gcs_size_bytes": 0 if gcs_available else None,
                    "local_size_bytes": total_size_bytes,
                    "sync_state": "local_only" if gcs_available else "cloud_unavailable",
                    "is_synced": False,
                    "source": "local",
                    "gcs_available": gcs_available,
                    "domain": "industrial" if is_ind else "bioacoustic",
                    "domain_label": "Acústica Industrial" if is_ind else "Bioacústica Silvestre",
                })

        return local_datasets

    def list_datasets(self, dataset_names: Optional[set[str]] = None) -> List[Dict[str, Any]]:
        """
        Lista los datasets almacenados en GCS organizados bajo la jerarquía:
        datasets/{dataset_name}/{class_label}/{audio_file.wav}
        Reporta clases/categorías contenidas, conteo de archivos, tamaño y estado de sincronización local.
        Si GCS no está disponible o falla la conexión, degrada grácilmente a los datasets locales (offline-first).
        """
        if dataset_names is not None:
            self.validate_dataset_names(list(dataset_names))
            if not dataset_names:
                return []
        try:
            client = self._get_client()
            prefixes = ([f"datasets/{name}/" for name in sorted(dataset_names)]
                        if dataset_names is not None else ["datasets/"])
            blobs = [blob for prefix in prefixes for blob in client.list_blobs(self.bucket_name, prefix=prefix)]
        except Exception:
            return self.list_local_datasets(gcs_available=False, dataset_names=dataset_names)

        # Agrupar por dataset_name
        datasets_map: Dict[str, Dict[str, Any]] = {}

        for blob in blobs:
            if Path(blob.name).suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg"}:
                continue
            parts = blob.name.split("/")
            # Jerarquía recomendada: datasets/{dataset}/{class}/{filename} (len >= 4)
            # Compatibilidad legado: datasets/{dataset}/{filename} (len == 3)
            if len(parts) >= 4 and parts[3]:
                ds_name = parts[1]
                class_name = parts[2]
            elif len(parts) == 3 and parts[2]:
                ds_name = parts[1]
                class_name = "General"
            else:
                continue
            if dataset_names is not None and ds_name not in dataset_names:
                continue

            if ds_name not in datasets_map:
                datasets_map[ds_name] = {
                    "id": ds_name,
                    "name": ds_name,
                    "classes_set": set(),
                    "file_count": 0,
                    "total_size_bytes": 0,
                    "last_modified": None,
                    "latest_dt": None,
                }
            item = datasets_map[ds_name]
            item["classes_set"].add(class_name)
            item["file_count"] += 1
            item["total_size_bytes"] += (blob.size or 0)
            if blob.updated:
                if item["latest_dt"] is None or blob.updated > item["latest_dt"]:
                    item["latest_dt"] = blob.updated
                    item["last_modified"] = blob.updated.isoformat()

        # Enriquecer con información local de sincronización
        result = []
        for ds_name, data in sorted(datasets_map.items()):
            classes = sorted(list(data.pop("classes_set")))
            data["classes"] = classes
            data["class_count"] = len(classes)
            data.pop("latest_dt", None)

            # Buscar directorio local
            local_ds_dir = self.local_base_dir / ds_name
            if not local_ds_dir.is_dir():
                slug_dir = self.local_base_dir / ds_name.lower().replace(" ", "_")
                if slug_dir.is_dir():
                    local_ds_dir = slug_dir

            local_files = []
            if local_ds_dir.is_dir():
                # Conteo recursivo de audios en todas las subclases locales
                local_files = [
                    f for f in local_ds_dir.rglob("*")
                    if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg")
                ]
            else:
                # Si el dataset es AvesChilenas y las especies están directamente en data/raw/
                for c in classes:
                    c_dir = self.local_base_dir / c.lower().replace(" ", "_")
                    if c_dir.is_dir():
                        local_files.extend([
                            f for f in c_dir.iterdir()
                            if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg")
                        ])

            is_ind = any(k in ds_name.lower() for k in ["engine", "motor", "maquinaria", "industrial"])
            data["domain"] = "industrial" if is_ind else "bioacoustic"
            data["domain_label"] = "Acústica Industrial" if is_ind else "Bioacústica Silvestre"
            local_file_count = len(local_files)
            try:
                data["local_size_bytes"] = sum(path.stat().st_size for path in local_files)
            except OSError:
                data["local_size_bytes"] = None
            data["gcs_file_count"] = data["file_count"]
            data["gcs_size_bytes"] = data["total_size_bytes"]
            data["sync_state"] = "comparison_pending" if local_file_count else "cloud_only"
            data["local_file_count"] = local_file_count
            data["is_synced"] = None if local_file_count else False
            data["source"] = "gcs"
            data["gcs_available"] = True
            result.append(data)

        # Si GCS está conectado, fusionar los datasets de GCS con los locales
        local_datasets = self.list_local_datasets(gcs_available=True, dataset_names=dataset_names)
        gcs_names = {d["name"] for d in result}
        for loc_ds in local_datasets:
            if loc_ds["name"] not in gcs_names:
                result.append(loc_ds)

        return result

    def list_local_dataset_files(self, dataset_name: str) -> List[Dict[str, Any]]:
        """
        Lista los archivos locales dentro de un dataset específico en DEFAULT_LOCAL_RAW_DIR.
        """
        SUPPORTED_EXTS = {".wav", ".mp3", ".flac", ".ogg"}
        target_dir = self.local_base_dir / dataset_name
        if not target_dir.is_dir():
            slug_dir = self.local_base_dir / dataset_name.lower().replace(" ", "_")
            if slug_dir.is_dir():
                target_dir = slug_dir

        if not target_dir.is_dir():
            return []

        files = []
        for f in sorted(target_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                relative = f.relative_to(target_dir)
                class_name = relative.parts[0] if len(relative.parts) > 1 else "General"

                try:
                    stat = f.stat()
                    size_bytes = stat.st_size
                    mod_iso = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                except OSError:
                    size_bytes = 0
                    mod_iso = None

                files.append({
                    "name": f.name,
                    "class_name": class_name,
                    "path": f"datasets/{dataset_name}/{relative.as_posix()}",
                    "size_bytes": size_bytes,
                    "updated": mod_iso,
                    "source": "local",
                })
        return files

    def _list_dataset_file_inventory(self, dataset_name: str) -> List[Dict[str, Any]]:
        """
        Lista todos los archivos de audio dentro de un dataset específico.
        Intenta consultar GCS; si GCS no está disponible o falla, degrada grácilmente a los archivos locales.
        """
        try:
            client = self._get_client()
            prefix = f"datasets/{dataset_name}/"
            blobs = list(client.list_blobs(self.bucket_name, prefix=prefix))
            files = []
            for blob in blobs:
                if blob.name.endswith("/"):
                    continue
                parts = blob.name.split("/")
                if len(parts) >= 4 and parts[3]:
                    class_name = parts[2]
                    filename = parts[-1]
                elif len(parts) == 3 and parts[2]:
                    class_name = "General"
                    filename = parts[2]
                else:
                    continue

                files.append({
                    "name": filename,
                    "class_name": class_name,
                    "path": blob.name,
                    "size_bytes": blob.size or 0,
                    "updated": blob.updated.isoformat() if blob.updated else None,
                    "source": "gcs",
                })

            if not files:
                return self.list_local_dataset_files(dataset_name)
            return files
        except Exception:
            return self.list_local_dataset_files(dataset_name)

    def list_dataset_files(self, dataset_name: str, db: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Inventory with optional recorded metadata, not current cloud verification."""
        self.validate_dataset_names([dataset_name])
        files = self._list_dataset_file_inventory(dataset_name)
        if db is None:
            return files
        for item in files:
            item["recorded_metadata"] = None
        try:
            from app.models.dataset import ConjuntoDatos, Audio

            rows = db.query(Audio).join(ConjuntoDatos).filter(ConjuntoDatos.nombre == dataset_name).all()
            by_route = {row.ruta_gcp: row for row in rows}
            for item in files:
                row = by_route.get(f"gs://{self.bucket_name}/{item['path']}") or by_route.get(item['path'])
                if row is not None:
                    item["recorded_metadata"] = {
                        "sample_rate_hz": row.frecuencia_muestreo,
                        "duration_seconds": row.duracion_segundos,
                        "source": "database",
                    }
        except Exception:
            db.rollback()
        return files

    @staticmethod
    def _read_audio_metadata(source) -> Tuple[Optional[int], Optional[float]]:
        """Observe container metadata without decoding/resampling the recording."""
        try:
            info = sf.info(io.BytesIO(source) if isinstance(source, bytes) else str(source))
            if info.format in {"MP3", "MPEG"}:
                import miniaudio

                # Scan MPEG frames instead of trusting a bitrate-based estimate.
                info = (miniaudio.mp3_get_info(source) if isinstance(source, bytes)
                        else miniaudio.mp3_get_file_info(str(source)))
                return int(info.sample_rate), info.num_frames / info.sample_rate
            if info.samplerate > 0 and info.frames >= 0:
                return int(info.samplerate), info.frames / info.samplerate
        except Exception:
            pass
        return None, None

    @staticmethod
    def _validate_mp3_frames(content: bytes) -> None:
        """Check Layer III frame boundaries independently of estimated PCM length."""
        offset = 0
        end = len(content)
        if end >= 128 and content[end - 128:end - 125] == b"TAG":
            end -= 128
        if end >= 32 and content[end - 32:end - 24] == b"APETAGEX":
            footer = content[end - 32:end]
            size = int.from_bytes(footer[12:16], "little")
            if footer[8:12] != (2000).to_bytes(4, "little") or not 32 <= size <= end:
                raise ValueError("Invalid APE tag size")
            end -= size
            if int.from_bytes(footer[20:24], "little") & (1 << 31):
                if (end < 32 or content[end - 32:end - 24] != b"APETAGEX"
                        or content[end - 24:end - 12] != footer[8:20]):
                    raise ValueError("Incomplete APE header")
                end -= 32
        if content.startswith(b"ID3"):
            if len(content) < 10 or content[3] not in (2, 3, 4) or any(b & 128 for b in content[6:10]):
                raise ValueError("Invalid ID3 header")
            size = sum(value << (7 * (3 - index)) for index, value in enumerate(content[6:10]))
            offset = 10 + size + (10 if content[3] == 4 and content[5] & 16 else 0)
        count = 0
        while offset < end:
            if offset + 4 > end:
                raise ValueError("Incomplete MPEG header")
            header = int.from_bytes(content[offset:offset + 4], "big")
            version, layer = (header >> 19) & 3, (header >> 17) & 3
            bitrate_index, rate_index = (header >> 12) & 15, (header >> 10) & 3
            if (header >> 21 != 2047 or version == 1 or layer != 1
                    or bitrate_index in (0, 15) or rate_index == 3):
                raise ValueError("Invalid MPEG Layer III header")
            rate = (44100, 48000, 32000)[rate_index] // {3: 1, 2: 2, 0: 4}[version]
            bitrates = ((0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
                        if version == 3 else (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160))
            size = (144000 if version == 3 else 72000) * bitrates[bitrate_index] // rate
            offset += size + ((header >> 9) & 1)
            if offset > end:
                raise ValueError("Incomplete MPEG frame")
            count += 1
        if not count:
            raise ValueError("Missing MPEG frames")

    @staticmethod
    def _validate_audio_upload(filename: str, content: bytes) -> Tuple[int, float]:
        formats = {".wav": {"WAV", "WAVEX", "RF64"}, ".mp3": {"MP3", "MPEG"},
                   ".flac": {"FLAC"}, ".ogg": {"OGG"}}
        supported = formats.get(Path(filename).suffix.lower(), set())
        try:
            with sf.SoundFile(io.BytesIO(content)) as audio:
                if (audio.format not in supported or audio.frames <= 0
                        or audio.samplerate <= 0 or audio.channels <= 0):
                    raise ValueError("Invalid audio header")
                if audio.format in {"MP3", "MPEG"}:
                    import miniaudio

                    IngestionService._validate_mp3_frames(content)
                    # libsndfile can also stop early when its MPEG estimate is
                    # too small. Decode native-rate blocks independently of it.
                    info = miniaudio.mp3_get_info(content)
                    stream = miniaudio.stream_memory(
                        content, output_format=miniaudio.SampleFormat.FLOAT32,
                        nchannels=info.nchannels, sample_rate=info.sample_rate,
                        frames_to_read=max(1, (1024 * 1024) // (4 * info.nchannels)),
                    )
                    try:
                        decoded_frames = sum(len(block) // info.nchannels for block in stream)
                    finally:
                        stream.close()
                    if decoded_frames <= 0 or decoded_frames != info.num_frames:
                        raise ValueError("Incomplete decoded MPEG audio")
                    return info.sample_rate, decoded_frames / info.sample_rate
                block_frames = max(1, (1024 * 1024) // (4 * audio.channels))
                decoded_frames = 0
                while len(block := audio.read(block_frames, dtype="float32", always_2d=True)):
                    decoded_frames += len(block)
                if decoded_frames <= 0 or decoded_frames != audio.frames:
                    raise ValueError("Incomplete decoded audio")
                return int(audio.samplerate), decoded_frames / audio.samplerate
        except Exception:
            raise IngestionAudioError("Invalid audio content") from None

    def preprocess_dataset_to_tensors(self, dataset_name: str) -> Dict[str, Any]:
        """
        Extrae características matemáticas (espectrogramas Mel y tensores) para los audios
        del dataset (RF_03 y Paso 3 de CU_INV_01).
        Almacena matrices numpy (.npy) en backend/data/processed/{dataset_name}/{class}/.
        """
        import time
        import numpy as np
        from poc.preprocess import load_and_fix_length, extract_mel_spectrogram

        t_start = time.time()
        target_base_dir = self.local_base_dir / dataset_name
        if not target_base_dir.is_dir():
            slug_dir = self.local_base_dir / dataset_name.lower().replace(" ", "_")
            if slug_dir.is_dir():
                target_base_dir = slug_dir

        out_dataset_dir = self.local_processed_dir / dataset_name
        out_dataset_dir.mkdir(parents=True, exist_ok=True)

        audio_files = []
        if target_base_dir.is_dir():
            audio_files = [
                f for f in target_base_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg")
            ]

        processed_count = 0
        failed_count = 0

        for audio_path in audio_files:
            try:
                # Determinar subdirectorio de clase
                try:
                    rel_parent = audio_path.relative_to(target_base_dir).parent
                    target_class_dir = out_dataset_dir / rel_parent
                except ValueError:
                    target_class_dir = out_dataset_dir / "General"

                target_class_dir.mkdir(parents=True, exist_ok=True)
                out_tensor_path = target_class_dir / f"{audio_path.stem}.npy"

                if not out_tensor_path.exists():
                    waveform = load_and_fix_length(audio_path)
                    mel_spec = extract_mel_spectrogram(waveform)
                    np.save(str(out_tensor_path), mel_spec)
                processed_count += 1
            except Exception:
                failed_count += 1

        duration = round(time.time() - t_start, 3)
        return {
            "dataset": dataset_name,
            "processed": processed_count,
            "failed": failed_count,
            "tensors_dir": str(out_dataset_dir),
            "duration_seconds": duration,
        }

    @staticmethod
    def _matches_remote_content(path: Path, blob) -> bool:
        """Size alone is not identity; stream the provider checksum without a cache."""
        expected = getattr(blob, "md5_hash", None)
        if isinstance(expected, str) and expected:
            digest = hashlib.md5(usedforsecurity=False)
        else:
            expected = getattr(blob, "crc32c", None)
            if not isinstance(expected, str) or not expected:
                return False
            digest = google_crc32c.Checksum()
        if not path.is_file():
            return False
        try:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            return base64.b64encode(digest.digest()).decode() == expected
        except OSError:
            return False

    @staticmethod
    def _valid_path_component(value: str) -> bool:
        if not value or value in (".", "..") or value.endswith((".", " ")):
            return False
        if any(ord(char) < 32 or char in '/\\:<>"|?*' for char in value):
            return False
        stem = value.split(".", 1)[0].upper()
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³")
        return stem not in reserved

    def validate_dataset_names(self, names: List[str]) -> None:
        """Validate a complete batch before any dataset can be transferred."""
        if any(not self._valid_path_component(name) or len(name) > 100 for name in names):
            raise IngestionValidationError("Invalid dataset name")

    @staticmethod
    def get_upload_limits() -> Tuple[int, int]:
        """Read file/batch policy without accepting invalid or unbounded limits."""
        try:
            file_limit = int(os.getenv("FAMA_UPLOAD_MAX_FILE_BYTES", str(64 * 1024 * 1024)))
            batch_limit = int(os.getenv("FAMA_UPLOAD_MAX_BATCH_BYTES", str(256 * 1024 * 1024)))
            if not 0 < file_limit <= batch_limit:
                raise ValueError("Invalid limits")
        except ValueError:
            raise IngestionConfigurationError("Upload configuration unavailable") from None
        return file_limit, batch_limit

    @staticmethod
    def _filesystem_path(path: Path) -> Path:
        """Use Windows extended paths only for I/O, not public dataset identity."""
        if os.name != "nt":
            return path
        absolute = str(path.absolute())
        if absolute.startswith("\\\\?\\"):
            return Path(absolute)
        if absolute.startswith("\\\\"):
            return Path("\\\\?\\UNC\\" + absolute[2:])
        return Path("\\\\?\\" + absolute)

    def sync_dataset_to_local(
        self,
        dataset_name: str,
        preprocess: bool = False,
        db: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Descarga los archivos de un dataset desde GCS a local manteniendo la estructura
        de carpetas por clase/etiqueta.
        RF_02: omite únicamente contenido confirmado mediante checksum del proveedor.
        RF_03: Si preprocess=True, extrae tensores matemáticos y espectrogramas Mel.
        Persistencia: Si db es provisto, sincroniza 'conjunto_datos' y 'audio' en PostgreSQL.
        """
        self.validate_dataset_names([dataset_name])
        client = self._get_client()
        prefix = f"datasets/{dataset_name}/"
        blobs = list(client.list_blobs(self.bucket_name, prefix=prefix))

        candidates = [blob for blob in blobs if not blob.name.endswith("/")]
        if not candidates or (
            not any(Path(blob.name).suffix.lower() in {".wav", ".mp3", ".flac", ".ogg"} for blob in candidates)
            and all(blob.name.startswith(prefix) and all(self._valid_path_component(part) for part in blob.name.split("/"))
                    for blob in candidates)
        ):
            raise IngestionDatasetUnavailable("No downloadable cloud audio")

        target_base_dir = self.local_base_dir / dataset_name
        if not self._filesystem_path(target_base_dir).is_dir():
            slug_dir = self.local_base_dir / dataset_name.lower().replace(" ", "_")
            if self._filesystem_path(slug_dir).is_dir():
                target_base_dir = slug_dir
        if not target_base_dir.resolve().is_relative_to(self.local_base_dir.resolve()):
            raise IngestionValidationError("Invalid dataset destination outside raw root")
        self._filesystem_path(target_base_dir).mkdir(parents=True, exist_ok=True)

        downloaded = 0
        skipped = 0
        failed = 0
        processed_files = []

        for blob in blobs:
            if blob.name.startswith(prefix) and blob.name.endswith("/"):
                continue  # GCS directory markers are not files.
            parts = blob.name.split("/")
            if (not blob.name.startswith(prefix)
                    or any(not self._valid_path_component(part) for part in parts)):
                failed += 1
                processed_files.append({"filename": blob.name, "status": "error",
                                        "error": "Invalid object path", "size": blob.size or 0})
                continue
            if len(parts) >= 4 and parts[3]:
                class_name = parts[2]
                filename = parts[-1]
                rel_path = Path(*parts[2:])
            elif len(parts) == 3 and parts[2]:
                class_name = "General"
                filename = parts[2]
                rel_path = Path(filename)
            else:
                continue

            if (len(class_name) > 100 or len(filename) > 255
                    or len(f"gs://{self.bucket_name}/{blob.name}") > 500):
                failed += 1
                processed_files.append({"filename": filename, "status": "error",
                                        "error": "Invalid object metadata length", "size": blob.size or 0})
                continue

            # Determinar destino respetando estructura jerárquica por dataset y clase
            dest_path = target_base_dir / rel_path
            blob_size = blob.size or 0
            temporary = None
            try:
                if not dest_path.resolve().is_relative_to(target_base_dir.resolve()):
                    failed += 1
                    processed_files.append({"filename": filename, "status": "error",
                                            "error": "Destination outside dataset", "size": blob_size})
                    continue
                dest_path = self._filesystem_path(dest_path)
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                # A same-sized replacement can still contain different audio bytes.
                if self._matches_remote_content(dest_path, blob):
                    skipped += 1
                    processed_files.append({
                        "filename": filename,
                        "class_name": class_name,
                        "status": "skipped",
                        "reason": "already_up_to_date",
                        "size": dest_path.stat().st_size,
                        "object_key": blob.name,
                    })
                    continue

                # Publish only a completed transfer; never download over good bytes.
                with tempfile.NamedTemporaryFile(dir=dest_path.parent, prefix=".fama-",
                                                 suffix=".download", delete=False) as staging:
                    temporary = Path(staging.name)
                blob.download_to_filename(str(temporary))
                observed_size = temporary.stat().st_size
                expected_size = getattr(blob, "size", None)
                if type(expected_size) is int and observed_size != expected_size:
                    raise ValueError("Downloaded content does not match provider size")
                checksums = (getattr(blob, "md5_hash", None), getattr(blob, "crc32c", None))
                if (any(isinstance(value, str) and value for value in checksums)
                        and not self._matches_remote_content(temporary, blob)):
                    raise ValueError("Downloaded content does not match provider checksum")
                temporary.replace(dest_path)
                downloaded += 1
                processed_files.append({
                    "filename": filename,
                    "class_name": class_name,
                    "status": "downloaded",
                    "size": observed_size,
                    "object_key": blob.name,
                })
            except Exception:
                failed += 1
                processed_files.append({
                    "filename": filename,
                    "class_name": class_name,
                    "status": "error",
                    "error": "No se pudo sincronizar el archivo.",
                    "size": blob_size,
                })
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        processed_files[-1]["cleanup_pending"] = True

        # Preprocesamiento tensorial opcional (RF_03)
        preprocessed_count = 0
        prep_info = None
        if preprocess and downloaded + skipped > 0:
            prep_info = self.preprocess_dataset_to_tensors(dataset_name)
            preprocessed_count = prep_info.get("processed", 0)

        # Persistencia en base de datos PostgreSQL (Tablas 6.4 y 6.5)
        db_persisted = False
        db_error = None
        if db is not None:
            try:
                from app.models.dataset import ConjuntoDatos, Audio
                from sqlalchemy import func

                gcp_path = f"gs://{self.bucket_name}/datasets/{dataset_name}/"
                ds = db.query(ConjuntoDatos).filter_by(nombre=dataset_name).first()
                preprocessing_failed = (prep_info or {}).get("failed", 0) > 0
                new_status = "sincronizacion_parcial" if failed or preprocessing_failed else "procesado" if preprocess else "sincronizado"
                accepted_files = [item for item in processed_files if item["status"] in ("downloaded", "skipped")]
                total_audios = len(accepted_files)
                total_bytes = sum(item["size"] for item in accepted_files)

                if ds is None:
                    ds = ConjuntoDatos(
                        nombre=dataset_name,
                        ruta_gcp=gcp_path,
                        estado=new_status,
                        tamano_total_bytes=total_bytes,
                        cantidad_audios=total_audios,
                        finalidad="Entrenamiento bioacústico",
                        base_licitud="Investigación académica",
                    )
                    db.add(ds)
                    db.flush()
                else:
                    ds.estado = new_status
                    ds.tamano_total_bytes = total_bytes
                    ds.cantidad_audios = total_audios
                    ds.ruta_gcp = gcp_path
                    db.flush()

                for f in accepted_files:
                    fname = f.get("filename")
                    cname = f.get("class_name", "General")
                    fsize = f.get("size", 0)
                    object_route = f"gs://{self.bucket_name}/{f['object_key']}"
                    local_path = self._filesystem_path(target_base_dir / Path(f["object_key"][len(prefix):]))
                    sample_rate, duration = self._read_audio_metadata(local_path)
                    audio_obj = (
                        db.query(Audio)
                        .filter_by(id_conjunto_datos=ds.id_conjunto_datos, ruta_gcp=object_route)
                        .first()
                    )
                    if audio_obj is None:
                        audio_obj = Audio(
                            id_conjunto_datos=ds.id_conjunto_datos,
                            nombre_archivo=fname,
                            ruta_gcp=object_route,
                            clase=cname,
                            frecuencia_muestreo=sample_rate,
                            duracion_segundos=duration,
                            tamano_bytes=fsize,
                        )
                        db.add(audio_obj)
                    else:
                        audio_obj.clase = cname
                        audio_obj.frecuencia_muestreo = sample_rate
                        audio_obj.duracion_segundos = duration
                        if fsize > 0:
                            audio_obj.tamano_bytes = fsize

                # Failures do not erase previously accepted rows or their counters.
                db.flush()
                count, size = db.query(
                    func.count(Audio.id_audio), func.coalesce(func.sum(Audio.tamano_bytes), 0)
                ).filter(Audio.id_conjunto_datos == ds.id_conjunto_datos).one()
                ds.cantidad_audios = count
                ds.tamano_total_bytes = size
                db.commit()
                db_persisted = True
            except Exception:
                db.rollback()
                db_error = "No se pudieron guardar los registros de ingesta."

        return {
            "dataset": dataset_name,
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "local_dir": str(target_base_dir),
            "files": processed_files,
            "preprocessed": preprocessed_count,
            "preprocess_info": prep_info,
            "db_persisted": db_persisted,
            "db_error": db_error,
        }

    def upload_files_to_gcs(
        self,
        files: List[Tuple[str, bytes]],
        dataset_name: str,
        class_label: str = "General",
        db: Optional[Any] = None,
        actor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Sube una lista de archivos binarios al bucket de GCS bajo la jerarquía:
        datasets/{dataset_name}/{class_label}/{filename}
        Registra opcionalmente en PostgreSQL las tablas 'conjunto_datos' y 'audio'.
        """
        self.validate_dataset_names([dataset_name])
        if not self._valid_path_component(class_label) or len(class_label) > 100:
            raise IngestionValidationError("Invalid class label")
        file_limit, batch_limit = self.get_upload_limits()
        total_bytes = 0
        for filename, content in files:
            if not self._valid_path_component(filename) or len(filename) > 255:
                raise IngestionValidationError("Invalid filename")
            if len(f"gs://{self.bucket_name}/datasets/{dataset_name}/{class_label}/{filename}") > 500:
                raise IngestionValidationError("Invalid object URI length")
            total_bytes += len(content)
            if len(content) > file_limit or total_bytes > batch_limit:
                raise IngestionPayloadTooLarge("Upload exceeds limits")
        metadata = [self._validate_audio_upload(filename, content) for filename, content in files]
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)

        uploaded = 0
        skipped = 0
        uploaded_names = []
        accepted_files = []
        errors = []

        # Keep validated identities instead of silently renaming destinations.
        safe_ds = dataset_name
        safe_class = class_label

        for (filename, content), observed_metadata in zip(files, metadata):
            safe_file = filename
            blob_name = f"datasets/{safe_ds}/{safe_class}/{safe_file}"
            try:
                blob = bucket.blob(blob_name)
                content_type = "audio/wav" if safe_file.lower().endswith(".wav") else "application/octet-stream"
                blob.upload_from_string(content, content_type=content_type, if_generation_match=0)
            except PreconditionFailed:
                identical = False
                try:
                    blob.reload()
                    expected = getattr(blob, "md5_hash", None)
                    if isinstance(expected, str) and expected:
                        observed = hashlib.md5(content, usedforsecurity=False).digest()
                        identical = base64.b64encode(observed).decode() == expected
                    else:
                        expected = getattr(blob, "crc32c", None)
                        if isinstance(expected, str) and expected:
                            identical = base64.b64encode(google_crc32c.Checksum(content).digest()).decode() == expected
                except Exception:
                    pass
                if identical:
                    skipped += 1
                    uploaded_names.append(safe_file)
                    accepted_files.append((filename, content, observed_metadata))
                    continue
                errors.append({"filename": filename, "code": "already_exists",
                               "error": "Ya existe un audio con ese nombre y clase; no se ha reemplazado."})
                continue
            except Exception:
                errors.append({"filename": filename, "error": "No se pudo subir el archivo."})
                continue
            uploaded += 1
            uploaded_names.append(safe_file)
            accepted_files.append((filename, content, observed_metadata))

        # Persistencia en PostgreSQL
        db_persisted = False
        db_error = None
        if db is not None and accepted_files:
            try:
                from app.models.dataset import ConjuntoDatos, Audio

                gcp_path = f"gs://{self.bucket_name}/datasets/{safe_ds}/"
                ds = db.query(ConjuntoDatos).filter_by(nombre=safe_ds).with_for_update().first()
                upload_status = "subida_parcial" if errors else "subido"

                if ds is None:
                    ds = ConjuntoDatos(
                        nombre=safe_ds,
                        ruta_gcp=gcp_path,
                        estado=upload_status,
                        id_usuario_carga=actor_id,
                        tamano_total_bytes=0,
                        cantidad_audios=0,
                    )
                    db.add(ds)
                    db.flush()
                else:
                    ds.estado = upload_status
                    db.flush()

                for filename, content, (sample_rate, duration) in accepted_files:
                    safe_file = filename
                    object_route = f"{gcp_path}{safe_class}/{safe_file}"
                    audio_obj = (
                        db.query(Audio)
                        .filter_by(id_conjunto_datos=ds.id_conjunto_datos, ruta_gcp=object_route)
                        .first()
                    )
                    if audio_obj is None:
                        audio_obj = Audio(
                            id_conjunto_datos=ds.id_conjunto_datos,
                            nombre_archivo=safe_file,
                            ruta_gcp=object_route,
                            clase=safe_class,
                            frecuencia_muestreo=sample_rate,
                            duracion_segundos=duration,
                            tamano_bytes=len(content),
                        )
                        db.add(audio_obj)
                    else:
                        audio_obj.tamano_bytes = len(content)
                        audio_obj.frecuencia_muestreo = sample_rate
                        audio_obj.duracion_segundos = duration
                    audio_obj.hash_archivo = hashlib.sha256(content).hexdigest()

                from sqlalchemy import func
                db.flush()
                count, size = db.query(
                    func.count(Audio.id_audio), func.coalesce(func.sum(Audio.tamano_bytes), 0)
                ).filter(Audio.id_conjunto_datos == ds.id_conjunto_datos).one()
                ds.cantidad_audios = count
                ds.tamano_total_bytes = size
                if actor_id is not None:
                    from app.services.security_audit import record_event
                    record_event(db, "dataset.audio_uploaded", "success", actor_id=actor_id,
                                 dataset_id=ds.id_conjunto_datos)
                db.commit()
                db_persisted = True
            except Exception:
                db.rollback()
                db_error = "No se pudieron guardar los registros de ingesta."

        return {
            "dataset": safe_ds,
            "status": ("partial" if uploaded + skipped else "failed") if (errors or db_error) else "completed",
            "class_label": safe_class,
            "uploaded": uploaded,
            "skipped": skipped,
            "failed": len(errors),
            "files": uploaded_names,
            "errors": errors,
            "db_persisted": db_persisted,
            "db_error": db_error,
        }


# Instancia singleton para uso en controladores y rutas
ingestion_service = IngestionService()
