"""Streaming SHA-256 of local dataset audio and one-time backfill of NULL ``Audio.hash_archivo``."""
import hashlib
from pathlib import Path
from typing import Optional

from app.models.dataset import Audio

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_file(audio: Audio, dataset_name: str, root: Path) -> Optional[Path]:
    marker = f"datasets/{dataset_name}/"
    route = audio.ruta_gcp or ""
    if marker in route:
        relative = route.split(marker, 1)[1]
    else:
        relative = f"{audio.clase}/{audio.nombre_archivo}"
    parts = relative.split("/")
    if not relative or any(part in ("", ".", "..") for part in parts):
        return None
    candidate = root.joinpath(*parts)
    try:
        if not candidate.resolve().is_relative_to(root.resolve()) or not candidate.is_file():
            return None
    except OSError:
        return None
    return candidate


def backfill_null_hashes(db, dataset_id: int, dataset_name: str, root: Path) -> int:
    """Hash local files of rows with NULL ``hash_archivo``; flush, never commit. Returns rows filled."""
    filled = 0
    rows = db.query(Audio).filter(Audio.id_conjunto_datos == dataset_id,
                                  Audio.hash_archivo.is_(None)).all()
    for audio in rows:
        path = _local_file(audio, dataset_name, Path(root))
        if path is None:
            continue
        try:
            audio.hash_archivo = sha256_file(path)
        except OSError:
            continue
        filled += 1
    if filled:
        db.flush()
    return filled
