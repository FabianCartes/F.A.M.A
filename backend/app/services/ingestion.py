import os
import asyncio
import base64
import hashlib
import tempfile
import google_crc32c
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
from google.cloud import storage


class IngestionValidationError(ValueError):
    """Invalid ingestion input, distinct from provider/transport errors."""

# ============================================================================
# CONFIGURACIÓN DE ENTORNO Y RUTAS BASE
# ============================================================================
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()

# Asegurar ruta absoluta a credenciales IAM
_cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GCP_KEY_PATH")
if _cred_env:
    _cred_path = Path(_cred_env)
    if not _cred_path.is_absolute():
        for _candidate in [
            _cred_path,
            _BACKEND_DIR / _cred_path,
            Path("/app") / _cred_path,
            Path.cwd() / _cred_path,
            Path.cwd() / "backend" / _cred_path,
        ]:
            if _candidate.exists():
                _resolved_cred = _candidate.resolve()
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_resolved_cred)
                os.environ["GCP_KEY_PATH"] = str(_resolved_cred)
                break

DEFAULT_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "fama-audio-records-2026")

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
        self.bucket_name = bucket_name or os.getenv("GCS_BUCKET_NAME", DEFAULT_BUCKET_NAME)
        self.local_base_dir = Path(local_base_dir or DEFAULT_LOCAL_RAW_DIR)
        self.local_processed_dir = Path(local_processed_dir or DEFAULT_LOCAL_PROCESSED_DIR)

    def _get_client(self) -> storage.Client:
        return storage.Client()

    def get_storage_status(self) -> Dict[str, Any]:
        """
        Verifica la conectividad con el bucket de GCS y calcula estadísticas globales de objetos.
        """
        try:
            client = self._get_client()
            blobs = list(client.list_blobs(self.bucket_name, max_results=2000))
            total_bytes = sum(b.size or 0 for b in blobs)
            return {
                "connected": True,
                "bucket": self.bucket_name,
                "total_objects": len(blobs),
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

    def list_local_datasets(self, gcs_available: bool = False) -> List[Dict[str, Any]]:
        """
        Escanea self.local_base_dir (DEFAULT_LOCAL_RAW_DIR), agrupa clases por subdirectorio,
        cuenta archivos de audio (.wav, .mp3, .flac, .ogg), calcula el tamaño total en bytes
        y retorna la lista de datasets locales estructurados con metadatos completos.
        """
        if not self.local_base_dir.exists() or not self.local_base_dir.is_dir():
            return []

        SUPPORTED_EXTS = {".wav", ".mp3", ".flac", ".ogg"}
        local_datasets = []

        for entry in sorted(self.local_base_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith(".") or entry.name.startswith("__"):
                continue

            ds_name = entry.name
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
                    "is_synced": True,
                    "source": "local",
                    "gcs_available": gcs_available,
                    "domain": "industrial" if is_ind else "bioacoustic",
                    "domain_label": "Acústica Industrial" if is_ind else "Bioacústica Silvestre",
                })

        return local_datasets

    def list_datasets(self) -> List[Dict[str, Any]]:
        """
        Lista los datasets almacenados en GCS organizados bajo la jerarquía:
        datasets/{dataset_name}/{class_label}/{audio_file.wav}
        Reporta clases/categorías contenidas, conteo de archivos, tamaño y estado de sincronización local.
        Si GCS no está disponible o falla la conexión, degrada grácilmente a los datasets locales (offline-first).
        """
        try:
            client = self._get_client()
            blobs = list(client.list_blobs(self.bucket_name, prefix="datasets/"))
        except Exception:
            return self.list_local_datasets(gcs_available=False)

        # Agrupar por dataset_name
        datasets_map: Dict[str, Dict[str, Any]] = {}

        for blob in blobs:
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

            local_file_count = 0
            if local_ds_dir.is_dir():
                # Conteo recursivo de audios en todas las subclases locales
                local_file_count = len([
                    f for f in local_ds_dir.rglob("*")
                    if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg")
                ])
            else:
                # Si el dataset es AvesChilenas y las especies están directamente en data/raw/
                for c in classes:
                    c_dir = self.local_base_dir / c.lower().replace(" ", "_")
                    if c_dir.is_dir():
                        local_file_count += len([
                            f for f in c_dir.iterdir()
                            if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg")
                        ])

            is_ind = any(k in ds_name.lower() for k in ["engine", "motor", "maquinaria", "industrial"])
            data["domain"] = "industrial" if is_ind else "bioacoustic"
            data["domain_label"] = "Acústica Industrial" if is_ind else "Bioacústica Silvestre"
            is_synced = (local_file_count >= data["file_count"] and data["file_count"] > 0)
            data["local_file_count"] = local_file_count
            data["is_synced"] = is_synced
            data["source"] = "gcs"
            data["gcs_available"] = True
            result.append(data)

        # Si GCS está conectado, fusionar los datasets de GCS con los locales
        local_datasets = self.list_local_datasets(gcs_available=True)
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
                rel_parents = f.relative_to(target_dir).parts[:-1]
                class_name = rel_parents[-1] if rel_parents else "General"

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
                    "path": f"datasets/{dataset_name}/{class_name}/{f.name}",
                    "size_bytes": size_bytes,
                    "updated": mod_iso,
                    "source": "local",
                })
        return files

    def list_dataset_files(self, dataset_name: str) -> List[Dict[str, Any]]:
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
                parts = blob.name.split("/")
                if len(parts) >= 4 and parts[3]:
                    class_name = parts[2]
                    filename = parts[3]
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
        if preprocess:
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
                            frecuencia_muestreo=22050,
                            duracion_segundos=5.0,
                            tamano_bytes=fsize,
                        )
                        db.add(audio_obj)
                    else:
                        audio_obj.clase = cname
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
    ) -> Dict[str, Any]:
        """
        Sube una lista de archivos binarios al bucket de GCS bajo la jerarquía:
        datasets/{dataset_name}/{class_label}/{filename}
        Registra opcionalmente en PostgreSQL las tablas 'conjunto_datos' y 'audio'.
        """
        self.validate_dataset_names([dataset_name])
        if not self._valid_path_component(class_label) or len(class_label) > 100:
            raise IngestionValidationError("Invalid class label")
        for filename, _ in files:
            if not self._valid_path_component(filename) or len(filename) > 255:
                raise IngestionValidationError("Invalid filename")
            if len(f"gs://{self.bucket_name}/datasets/{dataset_name}/{class_label}/{filename}") > 500:
                raise IngestionValidationError("Invalid object URI length")
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)

        uploaded = 0
        uploaded_names = []
        accepted_files = []
        errors = []

        # Keep validated identities instead of silently renaming destinations.
        safe_ds = dataset_name
        safe_class = class_label

        for filename, content in files:
            safe_file = filename
            blob_name = f"datasets/{safe_ds}/{safe_class}/{safe_file}"
            try:
                blob = bucket.blob(blob_name)
                content_type = "audio/wav" if safe_file.lower().endswith(".wav") else "application/octet-stream"
                blob.upload_from_string(content, content_type=content_type)
            except Exception:
                errors.append({"filename": filename, "error": "No se pudo subir el archivo."})
                continue
            uploaded += 1
            uploaded_names.append(safe_file)
            accepted_files.append((filename, content))

        # Persistencia en PostgreSQL
        db_persisted = False
        db_error = None
        if db is not None:
            try:
                from app.models.dataset import ConjuntoDatos, Audio

                gcp_path = f"gs://{self.bucket_name}/datasets/{safe_ds}/"
                ds = db.query(ConjuntoDatos).filter_by(nombre=safe_ds).first()
                upload_status = "subida_parcial" if errors else "subido"

                if ds is None:
                    ds = ConjuntoDatos(
                        nombre=safe_ds,
                        ruta_gcp=gcp_path,
                        estado=upload_status,
                        tamano_total_bytes=0,
                        cantidad_audios=0,
                    )
                    db.add(ds)
                    db.flush()
                else:
                    ds.estado = upload_status
                    db.flush()

                for filename, content in accepted_files:
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
                            frecuencia_muestreo=22050,
                            duracion_segundos=5.0,
                            tamano_bytes=len(content),
                        )
                        db.add(audio_obj)
                    else:
                        audio_obj.tamano_bytes = len(content)

                from sqlalchemy import func
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
            "dataset": safe_ds,
            "status": ("partial" if uploaded else "failed") if (errors or db_error) else "completed",
            "class_label": safe_class,
            "uploaded": uploaded,
            "failed": len(errors),
            "files": uploaded_names,
            "errors": errors,
            "db_persisted": db_persisted,
            "db_error": db_error,
        }


# Instancia singleton para uso en controladores y rutas
ingestion_service = IngestionService()
