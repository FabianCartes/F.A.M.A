"""
backend/training/upload_dataset_to_gcs.py
Módulo y herramienta CLI para carga masiva y concurrente de datasets jerárquicos a Google Cloud Storage.
Sube automáticamente carpetas de clases a datasets/{dataset_name}/{class_name}/{file.wav}.
"""
import os
import sys
import argparse
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from google.cloud import storage

from training.paths import get_project_root, get_raw_data_dir

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg"}


def setup_credentials():
    """Carga variables de entorno y asegura ruta absoluta de GOOGLE_APPLICATION_CREDENTIALS."""
    root = get_project_root()
    env_file = root / "backend" / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
    else:
        load_dotenv()

    cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_env:
        p = Path(cred_env)
        if not p.is_absolute():
            resolved = (root / "backend" / p).resolve()
            if not resolved.exists():
                resolved = (root / p).resolve()
            if resolved.exists():
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(resolved)


def get_storage_client() -> storage.Client:
    setup_credentials()
    return storage.Client()


def scan_dataset_files(source_dir: Path, dataset_name: str) -> List[Dict[str, Any]]:
    """
    Recorre recursivamente source_dir identificando audios e infiere
    la etiqueta de clase a partir del directorio contenedor inmediato.
    """
    source_path = Path(source_dir).resolve()
    items = []

    for file_path in sorted(source_path.rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
            class_name = file_path.parent.name
            destination_blob = f"datasets/{dataset_name}/{class_name}/{file_path.name}"
            items.append({
                "local_path": file_path,
                "file_name": file_path.name,
                "class_name": class_name,
                "destination_blob": destination_blob,
                "size_bytes": file_path.stat().st_size,
            })

    return items


def upload_dataset_to_gcs(
    dataset_name: str,
    source_dir: Optional[Path] = None,
    bucket_name: Optional[str] = None,
    dry_run: bool = False,
    max_workers: int = 8,
    skip_existing: bool = True,
    max_retries: int = 3,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Sube todos los archivos del dataset local hacia Google Cloud Storage.
    """
    import time
    target_dir = Path(source_dir) if source_dir else get_raw_data_dir(dataset_name)
    if not target_dir.exists():
        raise FileNotFoundError(f"El directorio del dataset no existe: {target_dir}")

    bucket_name = bucket_name or os.getenv("GCS_BUCKET_NAME", "fama-audio-records-2026")
    items = scan_dataset_files(target_dir, dataset_name)

    stats = {
        "dataset_name": dataset_name,
        "bucket_name": bucket_name,
        "source_dir": str(target_dir),
        "total_scanned": len(items),
        "uploaded": 0,
        "skipped": 0,
        "failed": 0,
        "dry_run": dry_run,
        "errors": [],
    }

    if dry_run or len(items) == 0:
        return stats

    client = get_storage_client()
    bucket = client.bucket(bucket_name)

    # Identificar blobs ya existentes si skip_existing está activo
    existing_blobs = set()
    if skip_existing:
        try:
            prefix = f"datasets/{dataset_name}/"
            existing_blobs = {b.name for b in bucket.list_blobs(prefix=prefix)}
        except Exception as e:
            if verbose:
                print(f"  [AVISO] No fue posible precargar blobs existentes: {e}")

    items_to_upload = []
    for item in items:
        if skip_existing and item["destination_blob"] in existing_blobs:
            stats["skipped"] += 1
        else:
            items_to_upload.append(item)

    def _upload_single_item(item: Dict[str, Any]) -> bool:
        blob = bucket.blob(item["destination_blob"])
        ext = item["file_name"].lower()
        if ext.endswith(".wav"):
            content_type = "audio/wav"
        elif ext.endswith(".mp3"):
            content_type = "audio/mpeg"
        elif ext.endswith(".flac"):
            content_type = "audio/flac"
        elif ext.endswith(".ogg"):
            content_type = "audio/ogg"
        else:
            content_type = "application/octet-stream"

        # Para archivos grandes (>20 MB), configurar chunks de subida reanudable y timeout holgado
        if item.get("size_bytes", 0) > 20 * 1024 * 1024:
            blob.chunk_size = 5 * 1024 * 1024
            upload_timeout = 900
        else:
            upload_timeout = 300

        last_exc = None
        for attempt in range(max_retries):
            try:
                blob.upload_from_filename(str(item["local_path"]), content_type=content_type, timeout=upload_timeout)
                return True
            except Exception as exc:
                last_exc = exc
                time.sleep(1.0 * (attempt + 1))
        raise last_exc or RuntimeError("Fallo tras reintentos")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(_upload_single_item, item): item for item in items_to_upload}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                future.result()
                stats["uploaded"] += 1
                if verbose:
                    print(f"  [OK] {item['class_name']}/{item['file_name']} -> gs://{bucket_name}/{item['destination_blob']}")
            except Exception as exc:
                stats["failed"] += 1
                stats["errors"].append({"file": item["file_name"], "error": str(exc)})
                if verbose:
                    print(f"  [ERROR] {item['file_name']}: {exc}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Subida masiva y concurrente de datasets completos a Google Cloud Storage")
    parser.add_argument("--dataset", required=True, help="Nombre del dataset (ej: engine_diagnostics o AvesChilenas)")
    parser.add_argument("--source-dir", default=None, help="Ruta local opcional (por defecto backend/data/raw/<dataset>)")
    parser.add_argument("--bucket", default=None, help="Nombre del bucket GCS")
    parser.add_argument("--workers", type=int, default=8, help="Número de hilos concurrentes")
    parser.add_argument("--dry-run", action="store_true", help="Escanear y simular sin subir datos a GCS")
    parser.add_argument("--verbose", action="store_true", help="Imprimir progreso detallado archivo por archivo")
    args = parser.parse_args()

    setup_credentials()
    print(f"[GCS Upload] Iniciando escaneo para dataset '{args.dataset}'...")
    stats = upload_dataset_to_gcs(
        dataset_name=args.dataset,
        source_dir=Path(args.source_dir) if args.source_dir else None,
        bucket_name=args.bucket,
        dry_run=args.dry_run,
        max_workers=args.workers,
        verbose=args.verbose,
    )

    print("\n" + "=" * 60)
    print(f"Resumen de Carga a GCS: {args.dataset}")
    print(f"  Directorio Local : {stats['source_dir']}")
    print(f"  Bucket Destino   : {stats['bucket_name']}")
    print(f"  Total Escaneado  : {stats['total_scanned']} audios")
    if stats["dry_run"]:
        print("  Modo Simulación  : ACTIVO (--dry-run). No se transfirieron datos.")
    else:
        print(f"  Omitidos (en GCS): {stats['skipped']}")
        print(f"  Subidos con Éxito: {stats['uploaded']}")
        print(f"  Fallidos         : {stats['failed']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
