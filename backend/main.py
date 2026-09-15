"""
Punto de entrada directo del backend F.A.M.A.
Re-exporta la instancia de FastAPI desde app.main para compatibilidad de comandos.
"""
from app.main import app

__all__ = ["app"]
