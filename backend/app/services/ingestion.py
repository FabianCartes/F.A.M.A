import os
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
from google.cloud import storage

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
_cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if _cred_env:
    _cred_path = Path(_cred_env)
    if not _cred_path.is_absolute():
        _resolved_cred = (_BACKEND_DIR / _cred_path).resolve()
        if _resolved_cred.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_resolved_cred)

DEFAULT_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "fama-audio-records-2026")
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

    def list_datasets(self) -> List[Dict[str, Any]]:
        """
        Lista los datasets almacenados en GCS organizados bajo la jerarquía:
        datasets/{dataset_name}/{class_label}/{audio_file.wav}
        Reporta clases/categorías contenidas, conteo de archivos, tamaño y estado de sincronización local.
        """
        client = self._get_client()
        blobs = list(client.list_blobs(self.bucket_name, prefix="datasets/"))

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
            result.append(data)

        return result

    def list_dataset_files(self, dataset_name: str) -> List[Dict[str, Any]]:
        """
        Lista todos los archivos de audio dentro de un dataset específico en GCS,
        incluyendo la etiqueta de clase/categoría.
        """
        client = self._get_client()
        prefix = f"datasets/{dataset_name}/"
        blobs = client.list_blobs(self.bucket_name, prefix=prefix)
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
            })
        return files

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

    def sync_dataset_to_local(
        self,
        dataset_name: str,
        preprocess: bool = False,
        db: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Descarga los archivos de un dataset desde GCS a local manteniendo la estructura
        de carpetas por clase/etiqueta.
        RF_02: SÓLO descarga archivos nuevos o actualizados (compara existencia y tamaño).
        RF_03: Si preprocess=True, extrae tensores matemáticos y espectrogramas Mel.
        Persistencia: Si db es provisto, sincroniza 'conjunto_datos' y 'audio' en PostgreSQL.
        """
        client = self._get_client()
        prefix = f"datasets/{dataset_name}/"
        blobs = list(client.list_blobs(self.bucket_name, prefix=prefix))

        target_base_dir = self.local_base_dir / dataset_name
        if not target_base_dir.is_dir():
            slug_dir = self.local_base_dir / dataset_name.lower().replace(" ", "_")
            if slug_dir.is_dir():
                target_base_dir = slug_dir
            else:
                target_base_dir.mkdir(parents=True, exist_ok=True)

        downloaded = 0
        skipped = 0
        failed = 0
        processed_files = []

        for blob in blobs:
            parts = blob.name.split("/")
            if len(parts) >= 4 and parts[3]:
                class_name = parts[2]
                filename = parts[3]
                rel_path = Path(class_name) / filename
            elif len(parts) == 3 and parts[2]:
                class_name = "General"
                filename = parts[2]
                rel_path = Path(filename)
            else:
                continue

            # Determinar destino respetando estructura jerárquica por dataset y clase
            dest_path = target_base_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            blob_size = blob.size or 0

            # Verificar si ya existe idéntico en disco local (mismo tamaño)
            if dest_path.exists() and dest_path.stat().st_size == blob_size:
                skipped += 1
                processed_files.append({
                    "filename": filename,
                    "class_name": class_name,
                    "status": "skipped",
                    "reason": "already_up_to_date",
                    "size": blob_size,
                })
                continue

            try:
                blob.download_to_filename(str(dest_path))
                downloaded += 1
                processed_files.append({
                    "filename": filename,
                    "class_name": class_name,
                    "status": "downloaded",
                    "size": blob_size,
                })
            except Exception as exc:
                failed += 1
                processed_files.append({
                    "filename": filename,
                    "class_name": class_name,
                    "status": "error",
                    "error": str(exc),
                    "size": blob_size,
                })

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

                gcp_path = f"gs://{self.bucket_name}/datasets/{dataset_name}/"
                ds = db.query(ConjuntoDatos).filter_by(nombre=dataset_name).first()
                new_status = "procesado" if preprocess else "sincronizado"
                total_audios = len(processed_files)
                total_bytes = sum(b.size or 0 for b in blobs)

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

                for f in processed_files:
                    fname = f.get("filename")
                    cname = f.get("class_name", "General")
                    fsize = f.get("size", 0)
                    audio_obj = (
                        db.query(Audio)
                        .filter_by(id_conjunto_datos=ds.id_conjunto_datos, nombre_archivo=fname)
                        .first()
                    )
                    if audio_obj is None:
                        audio_obj = Audio(
                            id_conjunto_datos=ds.id_conjunto_datos,
                            nombre_archivo=fname,
                            ruta_gcp=f"{gcp_path}{cname}/{fname}",
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

                db.commit()
                db_persisted = True
            except Exception as exc:
                db.rollback()
                db_error = str(exc)

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
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)

        uploaded = 0
        uploaded_names = []

        # Sanitizar nombres para evitar barras accidentales
        safe_ds = dataset_name.strip().replace("/", "_")
        safe_class = class_label.strip().replace("/", "_") or "General"

        for filename, content in files:
            safe_file = Path(filename).name
            blob_name = f"datasets/{safe_ds}/{safe_class}/{safe_file}"
            blob = bucket.blob(blob_name)
            content_type = "audio/wav" if safe_file.lower().endswith(".wav") else "application/octet-stream"
            blob.upload_from_string(content, content_type=content_type)
            uploaded += 1
            uploaded_names.append(safe_file)

        # Persistencia en PostgreSQL
        db_persisted = False
        db_error = None
        if db is not None:
            try:
                from app.models.dataset import ConjuntoDatos, Audio

                gcp_path = f"gs://{self.bucket_name}/datasets/{safe_ds}/"
                ds = db.query(ConjuntoDatos).filter_by(nombre=safe_ds).first()
                upload_bytes = sum(len(c) for _, c in files)

                if ds is None:
                    ds = ConjuntoDatos(
                        nombre=safe_ds,
                        ruta_gcp=gcp_path,
                        estado="subido",
                        tamano_total_bytes=upload_bytes,
                        cantidad_audios=uploaded,
                    )
                    db.add(ds)
                    db.flush()
                else:
                    ds.cantidad_audios = (ds.cantidad_audios or 0) + uploaded
                    ds.tamano_total_bytes = (ds.tamano_total_bytes or 0) + upload_bytes
                    db.flush()

                for filename, content in files:
                    safe_file = Path(filename).name
                    audio_obj = (
                        db.query(Audio)
                        .filter_by(id_conjunto_datos=ds.id_conjunto_datos, nombre_archivo=safe_file)
                        .first()
                    )
                    if audio_obj is None:
                        audio_obj = Audio(
                            id_conjunto_datos=ds.id_conjunto_datos,
                            nombre_archivo=safe_file,
                            ruta_gcp=f"{gcp_path}{safe_class}/{safe_file}",
                            clase=safe_class,
                            frecuencia_muestreo=22050,
                            duracion_segundos=5.0,
                            tamano_bytes=len(content),
                        )
                        db.add(audio_obj)

                db.commit()
                db_persisted = True
            except Exception as exc:
                db.rollback()
                db_error = str(exc)

        return {
            "dataset": safe_ds,
            "class_label": safe_class,
            "uploaded": uploaded,
            "files": uploaded_names,
            "db_persisted": db_persisted,
            "db_error": db_error,
        }


# Instancia singleton para uso en controladores y rutas
ingestion_service = IngestionService()
