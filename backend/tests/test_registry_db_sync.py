import pytest
from pathlib import Path
from unittest.mock import MagicMock
from app.services.registry import ModelRegistry, build_default_registry, get_model_registry
from app.services.predictors.trained_predictor import TrainedModelPredictor
from app.services.training import training_service
from app.models.training import Modelo
from app.database import SessionLocal


CHECKPOINT_NAME = "fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt"


def test_registry_resolves_active_trained_model():
    """
    Verifica que el ModelRegistry descubra e identifique como default
    el modelo marcado como activo en la base de datos PostgreSQL (id_modelo=6).
    """
    registry = build_default_registry()
    default_id = registry.get_default_model_id()
    assert default_id is not None

    db = SessionLocal()
    try:
        active_rec = db.query(Modelo).filter_by(activo=True).first()
        expected_name = Path(active_rec.ruta_binario_gcp).name if (active_rec and active_rec.ruta_binario_gcp) else CHECKPOINT_NAME
    finally:
        db.close()

    default_predictor = registry.get()
    assert isinstance(default_predictor, TrainedModelPredictor)
    assert default_predictor.checkpoint_path.name == expected_name
    assert default_predictor.metadata.is_default is True


def test_registry_register_from_db_explicit():
    """
    Verifica que el método register_from_db sincronice el modelo activo
    a partir de una sesión de base de datos.
    """
    registry = ModelRegistry()
    db = SessionLocal()
    try:
        active_pred = registry.register_from_db(db)
        assert active_pred is not None
        assert isinstance(active_pred, TrainedModelPredictor)
        assert registry.get_default_model_id() == active_pred.model_id
    finally:
        db.close()


def test_training_service_set_active_model_refreshes_registry():
    """
    Verifica que training_service.set_active_model actualice el modelo
    por defecto en el ModelRegistry global.
    """
    db = SessionLocal()
    try:
        res = training_service.set_active_model(6, db=db)
        assert res.get("success") is True

        active_rec = db.query(Modelo).filter_by(id_modelo=6).first()
        expected_name = Path(active_rec.ruta_binario_gcp).name if (active_rec and active_rec.ruta_binario_gcp) else CHECKPOINT_NAME

        global_reg = get_model_registry()
        active_predictor = global_reg.get()
        assert isinstance(active_predictor, TrainedModelPredictor)
        assert active_predictor.checkpoint_path.name == expected_name
    finally:
        db.close()
