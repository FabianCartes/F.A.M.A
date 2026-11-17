"""Entrada soportada: uvicorn main:app, con instalación previa al backend ML."""
from app.entrypoint import create_app

app = create_app()

__all__ = ["app"]
