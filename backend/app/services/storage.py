import os
import asyncio
from pathlib import Path
from typing import Optional, Union
from dotenv import load_dotenv
from google.cloud import storage

# ============================================================================
# CONFIGURACIÓN DE ENTORNO Y CREDENCIALES IAM (RNF_03)
# ============================================================================
# Cargar variables de entorno desde el .env del backend
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()

# Asegurar que la ruta a las credenciales IAM sea absoluta si se especificó relativa
_cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if _cred_env:
    _cred_path = Path(_cred_env)
    if not _cred_path.is_absolute():
        _resolved_cred = (_BACKEND_DIR / _cred_path).resolve()
        if _resolved_cred.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_resolved_cred)

# Nombre por defecto del bucket en Google Cloud Storage
DEFAULT_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "fama-audio-bucket")


async def upload_audio_to_gcp(
    audio_content: Union[bytes, Path, str],
    filename: str,
    bucket_name: Optional[str] = None,
    destination_folder: str = "raw_audios",
) -> bool:
    """
    Sube un archivo de audio a Google Cloud Storage de forma asíncrona.
    Cumple con el requerimiento de seguridad RNF_03 (lectura de credenciales mediante .env).

    Parámetros:
    - audio_content: Contenido binario (bytes) o ruta local (Path/str) del audio.
    - filename: Nombre que tendrá el objeto en GCS.
    - bucket_name: Nombre del bucket (opcional, por defecto usa GCS_BUCKET_NAME de .env).
    - destination_folder: Prefijo o subcarpeta dentro del bucket (por defecto 'raw_audios').

    Retorna:
    - True si el archivo fue subido exitosamente a GCS.
    """
    target_bucket = bucket_name or os.getenv("GCS_BUCKET_NAME", DEFAULT_BUCKET_NAME)
    destination_blob_name = f"{destination_folder}/{filename}" if destination_folder else filename

    # Obtener bytes del audio según el tipo de entrada
    if isinstance(audio_content, (str, Path)):
        file_path = Path(audio_content)
        data_bytes = file_path.read_bytes()
    elif isinstance(audio_content, bytes):
        data_bytes = audio_content
    else:
        raise TypeError(f"Tipo no soportado para audio_content: {type(audio_content)}")

    def _sync_upload():
        """Operación síncrona con el SDK oficial de Google Cloud Storage."""
        client = storage.Client()
        bucket = client.bucket(target_bucket)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_string(data_bytes, content_type="audio/wav")
        return True

    # Ejecutar en un hilo separado para no bloquear el bucle de eventos de FastAPI
    try:
        success = await asyncio.to_thread(_sync_upload)
        return success
    except Exception as exc:
        # Modo de simulación si está configurado para desarrollo sin conexión
        if os.getenv("GCS_MOCK", "").lower() in ("true", "1", "yes"):
            print(f"[GCS Storage] MOCK: Simulación exitosa de subida para {destination_blob_name}")
            return True

        print(f"[GCS Storage Service] Error al subir '{destination_blob_name}' a '{target_bucket}': {exc}")
        raise exc
