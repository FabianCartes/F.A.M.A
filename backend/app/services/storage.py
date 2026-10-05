import os
import re
import asyncio
import unicodedata
from pathlib import Path
from typing import Optional, Union
from dotenv import load_dotenv
from google.cloud import storage

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()

# Preserve relative credential resolution used by deployed environments.
_cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GCP_KEY_PATH")
if _cred_env:
    _cred_path = Path(_cred_env)
    if not _cred_path.is_absolute():
        for _candidate in [
            _cred_path, _BACKEND_DIR / _cred_path, Path("/app") / _cred_path,
            Path.cwd() / _cred_path, Path.cwd() / "backend" / _cred_path,
        ]:
            if _candidate.exists():
                _resolved_cred = _candidate.resolve()
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_resolved_cred)
                os.environ["GCP_KEY_PATH"] = str(_resolved_cred)
                break

DEFAULT_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "fama-audio-records-2026")


def validate_path_component(value: str) -> str:
    """Accept a single human-readable directory or filename, never a path."""
    if (not value or value != value.strip() or value in (".", "..")
            or len(value) > 100 or any(c in value for c in '/\\')
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Invalid storage path component")
    return value


def resolve_dataset_class(dataset_name: str, label: str) -> str:
    """Use the real directory catalogue, not the predictor's class inventory.

    New classes use NFC human-readable labels (accents preserved). A successfully
    listed but absent dataset is not an empty catalogue; errors never fall back.
    """
    validate_path_component(dataset_name)
    validate_path_component(label)
    prefix = f"datasets/{dataset_name}/"
    blobs = list(storage.Client().list_blobs(DEFAULT_BUCKET_NAME, prefix=prefix))
    if not blobs:
        raise ValueError("Dataset sin catálogo de almacenamiento verificable")
    directories = set()
    for blob in blobs:
        relative = blob.name.removeprefix(prefix)
        if "/" in relative:
            directory = relative.split("/", 1)[0]
            directories.add(validate_path_component(directory))
    if label in directories:
        return label
    normalized = unicodedata.normalize("NFC", label).casefold()
    matches = [name for name in directories
               if unicodedata.normalize("NFC", name).casefold() == normalized]
    if len(matches) > 1:
        raise ValueError("Clase ambigua en el catálogo de almacenamiento")
    return matches[0] if matches else validate_path_component(unicodedata.normalize("NFC", label))


def _blob(key: str, bucket_name: Optional[str] = None):
    if key.startswith("/") or any(p in ("", ".", "..") for p in key.split("/")):
        raise ValueError("Invalid storage object key")
    return storage.Client().bucket(bucket_name or os.getenv("GCS_BUCKET_NAME", DEFAULT_BUCKET_NAME)).blob(key)


def download_prediction_audio(source_key: str) -> bytes:
    """Resolve only a managed prediction source; never guess by basename."""
    if not re.fullmatch(r"raw_audios/[0-9a-f]{32}\.wav", source_key or ""):
        raise ValueError("Prediction has no managed audio source")
    data = _blob(source_key).download_as_bytes()
    if not data:
        raise ValueError("Prediction audio source is empty")
    return data


def upload_audio_to_gcp_sync(
    audio_content: Union[bytes, Path, str], filename: str,
    bucket_name: Optional[str] = None, destination_folder: str = "raw_audios",
    timeout: Optional[float] = None,
) -> bool:
    """Upload real bytes, propagating failures instead of simulating success."""
    validate_path_component(filename)
    data = Path(audio_content).read_bytes() if isinstance(audio_content, (str, Path)) else audio_content
    if not isinstance(data, bytes):
        raise TypeError("Audio content must be bytes or a file path")
    key = f"{destination_folder}/{filename}" if destination_folder else filename
    options = {} if timeout is None else {"timeout": timeout, "retry": None}
    _blob(key, bucket_name).upload_from_string(data, content_type="audio/wav", **options)
    return True


async def upload_audio_to_gcp(
    audio_content: Union[bytes, Path, str], filename: str,
    bucket_name: Optional[str] = None, destination_folder: str = "raw_audios",
) -> bool:
    return await asyncio.to_thread(
        upload_audio_to_gcp_sync, audio_content, filename, bucket_name, destination_folder
    )
