"""Explicit comparison of one dataset's local audio against its GCS objects.

Method: audios are matched by their path below the dataset root. For each pair
the byte size must agree, and the SHA-256 of the local file must equal the
fingerprint registered in ``audio.hash_archivo``. Rows without a registered
fingerprint are reported as unverified, never as different. Only files whose
size already agrees are hashed, and only when the user asks for the comparison.

Limit: GCS exposes MD5/CRC32C, not SHA-256, so the cloud bytes are never hashed
here; a registered fingerprint vouches for the bytes that were uploaded.
"""
from pathlib import Path
from typing import Any, Dict

from app.models.dataset import Audio, ConjuntoDatos
from app.services.audio_hashing import relative_audio_path, sha256_file

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg"}


def _local_audio(root: Path) -> Dict[str, Path]:
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


def compare_dataset_content(service, dataset_name: str, db) -> Dict[str, Any]:
    """Compare local and cloud audio of ``dataset_name``; raises on an empty or unreachable bucket."""
    from app.services.ingestion import IngestionDatasetUnavailable

    prefix = f"datasets/{dataset_name}/"
    blobs = service._get_client().list_blobs(service.bucket_name, prefix=prefix)
    cloud = {blob.name[len(prefix):]: blob.size or 0 for blob in blobs
             if blob.name.startswith(prefix) and not blob.name.endswith("/")
             and Path(blob.name).suffix.lower() in AUDIO_EXTENSIONS}
    if not cloud:
        raise IngestionDatasetUnavailable("No cloud audio to compare")

    root = service.local_base_dir / dataset_name
    if not root.is_dir():
        slug = service.local_base_dir / dataset_name.lower().replace(" ", "_")
        root = slug if slug.is_dir() else root
    local = _local_audio(root)

    registered: Dict[str, str] = {}
    dataset = db.query(ConjuntoDatos).filter_by(nombre=dataset_name).first()
    if dataset is not None:
        for audio in db.query(Audio).filter(Audio.id_conjunto_datos == dataset.id_conjunto_datos):
            if audio.hash_archivo:
                registered[relative_audio_path(audio, dataset_name)] = audio.hash_archivo

    size_mismatch = hash_mismatch = hash_unverified = hash_verified = 0
    for key in sorted(local.keys() & cloud.keys()):
        if local[key].stat().st_size != cloud[key]:
            size_mismatch += 1
        elif key not in registered:
            hash_unverified += 1
        elif sha256_file(local[key]) == registered[key]:
            hash_verified += 1
        else:
            hash_mismatch += 1

    missing_local = len(cloud.keys() - local.keys())
    missing_gcs = len(local.keys() - cloud.keys())
    return {
        "dataset": dataset_name,
        "status": "differences" if missing_local or missing_gcs or size_mismatch or hash_mismatch else "match",
        "local_count": len(local),
        "gcs_count": len(cloud),
        "missing_local": missing_local,
        "missing_gcs": missing_gcs,
        "size_mismatch": size_mismatch,
        "hash_mismatch": hash_mismatch,
        "hash_unverified": hash_unverified,
        "hash_verified": hash_verified,
    }
