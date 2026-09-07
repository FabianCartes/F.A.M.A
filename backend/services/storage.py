"""
Módulo de acceso al servicio de almacenamiento Google Cloud Storage.
Re-exporta la implementación de app.services.storage para compatibilidad directa.
"""
from app.services.storage import upload_audio_to_gcp, DEFAULT_BUCKET_NAME

__all__ = ["upload_audio_to_gcp", "DEFAULT_BUCKET_NAME"]
