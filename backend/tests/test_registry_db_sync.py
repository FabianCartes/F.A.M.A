"""Registry and activation through public interfaces, with temporary SQLite/ML fixtures."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.training import Modelo
from app.services import registry as registry_module
from app.services.registry import (
    ModelRegistry, build_default_registry, get_model_registry, set_global_model_registry,
)
from app.services.training import training_service
from tests.test_model_registry import FakeAudioPredictor


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    from app import database
    from app.services.predictors import trained_predictor

    class MetadataPredictor(FakeAudioPredictor):
        """No inference or tensor deserialization at the external ML seam."""
        def __init__(self, checkpoint_path, model_id, name, is_default, lazy_load, dataset_name):
            super().__init__(model_id, name, is_default)
            self.checkpoint_path = checkpoint_path
            self._meta.dataset_name = dataset_name

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", MetadataPredictor)
    # Default registration and the activation caller both resolve this temporary root.
    monkeypatch.setattr(registry_module, "__file__", str(tmp_path / "app/services/registry.py"))
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    monkeypatch.setattr(registry_module, "_global_model_registry", ModelRegistry())
    with sessions() as db:
        yield db, checkpoints
    engine.dispose()


@pytest.fixture
def seeded_models(isolated_db):
    db, checkpoints = isolated_db
    rows = []
    for model_id, active in ((41, True), (42, False)):
        filename = f"trained_{model_id}.pt"
        (checkpoints / filename).write_bytes(b"synthetic metadata fixture" * 500)
        rows.append(Modelo(id_modelo=model_id, arquitectura="fixture", epocas=1,
                           tasa_aprendizaje=0.001, tamano_lote=1,
                           ruta_binario_gcp=f"models/{filename}", activo=active))
    db.add_all(rows)
    db.commit()
    return db, checkpoints, rows[0], rows[1]


def _assert_default(registry, row, checkpoints):
    expected_id = f"fama_trained_model_{row.id_modelo}"
    assert registry.get_default_model_id() == expected_id
    predictor = registry.get()
    assert predictor.model_id == expected_id
    assert predictor.checkpoint_path == checkpoints / f"trained_{row.id_modelo}.pt"
    assert predictor.metadata.is_default is True
    assert registry.get(str(row.id_modelo)) is predictor
    return predictor


def test_registry_resolves_active_trained_model(seeded_models):
    """Construction honors the active row, not descending row order."""
    _, checkpoints, active, inactive = seeded_models
    registry = build_default_registry()
    _assert_default(registry, active, checkpoints)
    assert registry.get(str(inactive.id_modelo)).metadata.is_default is False
    assert {model.id for model in registry.list_models()} == {
        "fama_trained_model_41", "fama_trained_model_42",
    }


def test_registry_register_from_db_explicit(seeded_models):
    db, checkpoints, active, inactive = seeded_models
    registry = ModelRegistry()
    active_predictor = registry.register_from_db(db)
    assert active_predictor is _assert_default(registry, active, checkpoints)
    assert registry.get("trained_41.pt") is active_predictor
    assert registry.get("trained_41") is active_predictor
    assert registry.get(str(inactive.id_modelo)).metadata.is_default is False
    assert len(registry.list_models()) == 2


def test_training_service_set_active_model_refreshes_registry(seeded_models):
    db, checkpoints, previous_active, target = seeded_models
    global_registry = get_model_registry()
    global_registry.register_from_db(db)
    previous_predictor = _assert_default(global_registry, previous_active, checkpoints)
    result = training_service.set_active_model(target.id_modelo, db=db)
    assert result == {"success": True, "active_model_id": target.id_modelo, "architecture": "fixture"}
    assert get_model_registry() is global_registry
    new_predictor = _assert_default(global_registry, target, checkpoints)
    assert new_predictor is not previous_predictor
    assert global_registry.get(str(previous_active.id_modelo)).metadata.is_default is False
    refreshed = ModelRegistry()
    refreshed.register_from_db(db)
    _assert_default(refreshed, target, checkpoints)


def test_registry_register_from_empty_db_has_no_active_model(isolated_db):
    db, _ = isolated_db
    registry = ModelRegistry()
    assert registry.register_from_db(db) is None
    assert registry.get_default_model_id() is None
    assert registry.list_models() == []
