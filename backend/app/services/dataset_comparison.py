"""Comparison of one dataset's local audio against its GCS objects.

Audios are matched by their path below the dataset root. Two levels share one
classification (matching, missing in local, only in local, size mismatch,
checksum mismatch, unverified):

* ``count_size``: presence and byte size only. It never reads file content, so
  the inventory can run it on every refresh from the listing it already made.
* ``checksum``: files of equal size are also compared with the provider checksum
  (MD5/CRC32C) through ``IngestionService._matches_remote_content``, the same check
  the download uses to skip or replace a file. An object that exposes no checksum is
  ``unverified``, never different.

``download_content_check`` derives the same summary from a finished download, whose
files were already checksum-verified one by one, so nothing is hashed twice.
"""
from pathlib import Path
from typing import Any, Dict, Optional

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg"}


def local_audio(root: Path) -> Dict[str, Path]:
    """Audio files below ``root`` keyed by relative POSIX path, confined to ``root``."""
    found: Dict[str, Path] = {}
    if not root.is_dir():
        return found
    resolved = root.resolve()
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in AUDIO_EXTENSIONS or not path.is_file():
            continue
        try:
            if not path.resolve().is_relative_to(resolved):
                continue
        except OSError:
            continue
        found[path.relative_to(root).as_posix()] = path
    return found


def compare_content(service, cloud: Dict[str, Any], local: Dict[str, Path], *, checksum: bool) -> Dict[str, Any]:
    """Classify ``cloud`` blobs (by relative path) against ``local`` paths."""
    matching = size_mismatch = checksum_mismatch = unverified = 0
    for key in sorted(cloud.keys() & local.keys()):
        blob = cloud[key]
        if local[key].stat().st_size != (blob.size or 0):
            size_mismatch += 1
        elif not checksum:
            matching += 1
        elif service._matches_remote_content(local[key], blob):
            matching += 1
        elif any(isinstance(getattr(blob, name, None), str) and getattr(blob, name)
                 for name in ("md5_hash", "crc32c")):
            checksum_mismatch += 1
        else:
            unverified += 1
    missing_local = len(cloud.keys() - local.keys())
    only_local = len(local.keys() - cloud.keys())
    return {
        "level": "checksum" if checksum else "count_size",
        "status": "differences" if missing_local or only_local or size_mismatch or checksum_mismatch else "match",
        "local_count": len(local),
        "gcs_count": len(cloud),
        "matching": matching,
        "missing_local": missing_local,
        "only_local": only_local,
        "size_mismatch": size_mismatch,
        "checksum_mismatch": checksum_mismatch,
        "unverified": unverified,
    }


def verify_dataset_content(service, dataset_name: str) -> Dict[str, Any]:
    """Checksum comparison on explicit request; raises when the bucket has no audio."""
    from app.services.ingestion import IngestionDatasetUnavailable

    prefix = f"datasets/{dataset_name}/"
    blobs = service._get_client().list_blobs(service.bucket_name, prefix=prefix)
    cloud = {blob.name[len(prefix):]: blob for blob in blobs
             if blob.name.startswith(prefix) and not blob.name.endswith("/")
             and Path(blob.name).suffix.lower() in AUDIO_EXTENSIONS}
    if not cloud:
        raise IngestionDatasetUnavailable("No cloud audio to compare")

    root = service.local_base_dir / dataset_name
    if not root.is_dir():
        slug = service.local_base_dir / dataset_name.lower().replace(" ", "_")
        root = slug if slug.is_dir() else root
    return {"dataset": dataset_name, **compare_content(service, cloud, local_audio(root), checksum=True)}


def download_content_check(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Summarize a finished download from its per-file outcomes, without rehashing."""
    files = result.get("files")
    if not isinstance(files, list):
        return None
    failed = sum(1 for item in files if item.get("status") == "error")
    unverified = sum(1 for item in files
                     if item.get("status") in ("downloaded", "skipped") and not item.get("verified"))
    matching = sum(1 for item in files
                   if item.get("status") in ("downloaded", "skipped") and item.get("verified"))
    return {
        "level": "download",
        "status": "differences" if failed else "match",
        "local_count": None,
        "gcs_count": len(files),
        "matching": matching,
        "missing_local": 0,
        "only_local": None,
        "size_mismatch": 0,
        "checksum_mismatch": 0,
        "unverified": unverified,
        "failed": failed,
    }
