"""PostgreSQL integration tests using only test-owned model rows.

Run with an explicit DATABASE_URL pointing to a disposable PostgreSQL database
named oddtest_* on a non-default loopback port. Never use the development DB.
The two existing checkpoints are registration fixtures, not model-quality proof.
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.database import SessionLocal, normalize_database_url
from app.models.training import Modelo
from app.services import registry as registry_module
from app.services.registry import (
    ModelRegistry,
    build_default_registry,
    get_model_registry,
    set_global_model_registry,
)
from app.services.predictors.trained_predictor import TrainedModelPredictor
from app.services.training import training_service


CHECKPOINTS_ROOT = Path(__file__).resolve().parents[1] / "checkpoints"
ACTIVE_CHECKPOINT = "fama_efficientnet_b0_1790539191_efficientnet_b0_best.pt"
ALTERNATE_CHECKPOINT = "fama_efficientnet_b0_1790642923_efficientnet_b0_best.pt"


def _require_isolated_database(database_url):
    """Reject unsafe targets before opening a session or mutating any rows."""
    if not database_url:
        raise ValueError("An explicit isolated DATABASE_URL is required")
    url = make_url(database_url)
    if not (
        url.get_backend_name() == "postgresql"
        and url.host in {"127.0.0.1", "localhost"}
        and url.port is not None
        and url.port != 5432
        and url.database is not None
        and url.database.startswith("oddtest_")
        and not url.query
    ):
        raise ValueError(
            "Registry DB tests require disposable PostgreSQL oddtest_* on a "
            "non-default loopback port, without connection overrides"
        )
    return make_url(normalize_database_url(database_url))


@pytest.mark.parametrize(
    "database_url",
    [
        None,
        "postgresql://postgres@localhost:5432/fama_db",
        "postgresql://postgres@localhost:32769/fama_db",
        "postgresql://postgres@fama-db:32769/oddtest_guard",
        "postgresql://postgres@localhost/oddtest_guard",
        "postgresql://postgres@localhost:5432/oddtest_guard",
        "sqlite:///oddtest_guard",
        "postgresql://postgres@localhost:32769/oddtest_guard?host=fama-db",
    ],
)
def test_registry_db_safety_gate_rejects_unsafe_targets(database_url):
    with pytest.raises(ValueError):
        _require_isolated_database(database_url)


def test_registry_db_safety_gate_accepts_explicit_disposable_target():
    url = _require_isolated_database(
        "postgresql://postgres@127.0.0.1:32769/oddtest_guard"
    )
    assert url.drivername == "postgresql+psycopg2"
    assert url.database == "oddtest_guard"


@pytest.fixture
def isolated_db():
    expected_url = _require_isolated_database(os.environ.get("DATABASE_URL"))
    db = SessionLocal()
    try:
        # A previously imported app.database may have bound a different URL.
        if db.get_bind().url != expected_url:
            pytest.fail("SessionLocal is not bound to the explicitly isolated DB")
        actual_database = db.execute(text("SELECT current_database()")).scalar_one()
        if actual_database != expected_url.database:
            pytest.fail("Connected database does not match the isolated target")
        # set_active_model updates every row: refuse any non-owned model data.
        if db.query(Modelo).count() != 0:
            pytest.fail("Registry tests require an empty model table before seeding")
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def seeded_models(isolated_db):
    db = isolated_db
    for filename in (ACTIVE_CHECKPOINT, ALTERNATE_CHECKPOINT):
        checkpoint = CHECKPOINTS_ROOT / filename
        if not checkpoint.is_file() or checkpoint.stat().st_size <= 10000:
            pytest.skip(f"Explicit registration checkpoint unavailable: {filename}")

    # The active row is deliberately older than the inactive row. Selection must
    # follow the seeded active flag, not row order or newest-on-disk metadata.
    rows = [
        Modelo(
            arquitectura="EfficientNet-B0",
            epocas=1,
            tasa_aprendizaje=0.001,
            tamano_lote=1,
            ruta_binario_gcp=filename,
            activo=is_active,
        )
        for filename, is_active in (
            (ACTIVE_CHECKPOINT, True),
            (ALTERNATE_CHECKPOINT, False),
        )
    ]
    previous_registry = registry_module._global_model_registry
    set_global_model_registry(ModelRegistry())
    try:
        db.add_all(rows)
        db.commit()
        for row in rows:
            db.refresh(row)
        yield db, rows[0], rows[1]
    finally:
        # The service commits, so a rollback alone cannot clean up seeded rows.
        # Delete only these ORM instances; never truncate or reset sequences.
        try:
            db.rollback()
            for row in rows:
                if row.id_modelo is not None:
                    persisted = db.get(Modelo, row.id_modelo)
                    if persisted is not None:
                        db.delete(persisted)
            db.commit()
            assert db.query(Modelo).count() == 0, "Test-owned model rows were not cleaned up"
        finally:
            set_global_model_registry(previous_registry)
            assert registry_module._global_model_registry is previous_registry


def _assert_default(registry, row, expected_filename):
    expected_id = f"fama_trained_model_{row.id_modelo}"
    assert registry.get_default_model_id() == expected_id
    predictor = registry.get()
    assert isinstance(predictor, TrainedModelPredictor)
    assert predictor.model_id == expected_id
    assert predictor.checkpoint_path == CHECKPOINTS_ROOT / expected_filename
    assert predictor.metadata.is_default is True
    assert registry.get(str(row.id_modelo)) is predictor
    return predictor


def test_registry_resolves_active_trained_model(seeded_models):
    """Default construction honors the owned active row, not disk recency."""
    _, active, inactive = seeded_models
    registry = build_default_registry()
    _assert_default(registry, active, ACTIVE_CHECKPOINT)
    assert registry.get(str(inactive.id_modelo)).metadata.is_default is False


def test_registry_register_from_db_explicit(seeded_models):
    """Explicit DB registration selects the active row and preserves aliases."""
    db, active, inactive = seeded_models
    registry = ModelRegistry()
    active_predictor = registry.register_from_db(db)
    assert active_predictor is _assert_default(registry, active, ACTIVE_CHECKPOINT)
    assert registry.get(ACTIVE_CHECKPOINT) is active_predictor
    assert registry.get(Path(ACTIVE_CHECKPOINT).stem) is active_predictor
    assert registry.get(str(inactive.id_modelo)).metadata.is_default is False
    assert {model.id for model in registry.list_models()} == {
        f"fama_trained_model_{active.id_modelo}",
        f"fama_trained_model_{inactive.id_modelo}",
    }


def test_training_service_set_active_model_refreshes_registry(seeded_models):
    """Activating an owned inactive row replaces the existing global default."""
    db, previous_active, target = seeded_models
    global_registry = get_model_registry()
    global_registry.register_from_db(db)
    previous_predictor = _assert_default(
        global_registry, previous_active, ACTIVE_CHECKPOINT
    )

    result = training_service.set_active_model(target.id_modelo, db=db)
    assert result == {
        "success": True,
        "active_model_id": target.id_modelo,
        "architecture": "EfficientNet-B0",
    }
    assert get_model_registry() is global_registry
    new_predictor = _assert_default(global_registry, target, ALTERNATE_CHECKPOINT)
    assert new_predictor is not previous_predictor
    assert global_registry.get(str(previous_active.id_modelo)).metadata.is_default is False

    # Refreshing from the committed DB state must retain the same active choice.
    refreshed = ModelRegistry()
    refreshed.register_from_db(db)
    _assert_default(refreshed, target, ALTERNATE_CHECKPOINT)


def test_registry_register_from_empty_db_has_no_active_model(isolated_db):
    registry = ModelRegistry()
    assert registry.register_from_db(isolated_db) is None
    assert registry.get_default_model_id() is None
    assert registry.list_models() == []
