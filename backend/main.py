"""Entrada soportada: uvicorn main:app, con instalación previa al backend ML."""
from app.entrypoint import create_app

app = create_app()

__all__ = ["app", "ensemble_service", "SPECIES_CLASSES", "ENSEMBLE_WEIGHTS"]


def __getattr__(name):
    if name in __all__[1:]:
        from app import main as operational
        return getattr(operational, name)
    raise AttributeError(name)
