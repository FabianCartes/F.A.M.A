"""Registry and activation through public interfaces, with temporary SQLite/ML fixtures."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.dataset import ConjuntoDatos
from app.models.training import ModelEvaluation, Modelo
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


def seed_standard_model(db, checkpoints, model_id, *, wrong_config=False, failed_retry=False):
    import hashlib
    import torch
    from app.services.evaluations import EvaluationService
    from app.services.recording_evaluator import EVALUATOR_VERSION
    from app.services.standard_evaluation_guard import (
        ADMITTED_MANIFEST_PAIR_KEY, admitted_manifest_pair_provenance,
    )
    from ml_core.classification_metrics import calculate_classification_report

    dataset = ConjuntoDatos(nombre="engine_diagnostics", ruta_gcp="datasets/engine_diagnostics/")
    db.add(dataset)
    db.flush()
    job_id = f"synthetic-startup-job-{model_id}"
    filename = f"trained_{model_id}.pt"
    checkpoint = checkpoints / filename
    payload = {
        "dataset_id": dataset.id_conjunto_datos, "dataset_name": dataset.nombre,
        "job_id": job_id, "architecture": "AudioCNN", "classes": ["a", "b"],
        "audio_config": None, "windowing_config": None, "state_dict": {},
        "padding": "x" * 11000,
    }
    torch.save(payload, checkpoint)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    model = Modelo(id_modelo=model_id, conjunto_datos=dataset, arquitectura="AudioCNN",
                   epocas=1, tasa_aprendizaje=0.001, tamano_lote=1,
                   ruta_binario_gcp=f"models/{filename}", activo=True,
                   estado="standard_eval_completed", hash_binario=digest)
    db.add(model)
    db.flush()
    training_audio = dict(target_sr=32000, duration_seconds=2.0, n_mels=128,
                          n_fft=1024, hop_length=512, f_min=50.0, f_max=16000.0)
    settings = training_service._evaluation_config(
        {"job_id": job_id, "architecture": "AudioCNN", "windowing_config": None},
        training_audio)
    configs = dict(zip(("predictor_config", "preprocessing_config", "aggregation_config"), settings))
    if wrong_config:
        configs["preprocessing_config"] = {
            **configs["preprocessing_config"], "silence_rms_threshold": 0.75,
        }

    evaluations = EvaluationService(db)
    identity_by_split = {}
    pair_provenance = admitted_manifest_pair_provenance("d" * 64, "e" * 64)
    for split in ("val", "test"):
        split_configs = {**configs, "predictor_config": {
            **configs["predictor_config"], ADMITTED_MANIFEST_PAIR_KEY: pair_provenance,
        }}
        identity = {
            "id_modelo": model_id, "schema_version": 2,
            "evaluator_version": EVALUATOR_VERSION, "checkpoint_sha256": digest,
            "dataset": dataset.nombre, "split": split,
            "manifest_sha256": ("d" if split == "val" else "e") * 64,
            "classes": ["a", "b"], "sample_count": 2,
            **split_configs, "code_revision": None,
        }
        attempt = evaluations.create(identity)
        evaluations.start(attempt["id_evaluation"])
        report = calculate_classification_report(
            ["a", "b"], ["a", "__recording_rejected__"], ["a", "b"],
            rejection_label="__recording_rejected__")
        evaluations.complete(attempt["id_evaluation"], report)
        identity_by_split[split] = identity
    if failed_retry:
        attempt = evaluations.create(identity_by_split["val"])
        evaluations.start(attempt["id_evaluation"])
        evaluations.fail(attempt["id_evaluation"], "synthetic retry failure")
    db.commit()
    return model


@pytest.mark.parametrize("startup", ["register_from_db", "build_default_registry"])
def test_startup_rejects_standard_model_with_coherently_wrong_effective_config(isolated_db, startup):
    db, checkpoints = isolated_db
    model = seed_standard_model(db, checkpoints, 71, wrong_config=True)
    legacy_path = checkpoints / "trained_70.pt"
    legacy_path.write_bytes(b"legacy metadata fixture" * 600)
    db.add(Modelo(id_modelo=70, arquitectura="legacy", epocas=1,
                  tasa_aprendizaje=0.001, tamano_lote=1,
                  ruta_binario_gcp="models/trained_70.pt", activo=False, estado="entrenado"))
    db.commit()
    if startup == "register_from_db":
        registry = ModelRegistry()
        registry.register_from_db(db, checkpoints_root=checkpoints)
    else:
        registry = build_default_registry()

    key = f"fama_trained_model_{model.id_modelo}"
    assert not registry.has_model(key)
    assert registry.get_default_model_id() is None
    assert {item.id for item in registry.list_models()} == {"fama_trained_model_70"}
    assert db.get(Modelo, model.id_modelo).activo is True


@pytest.mark.parametrize("startup", ["register_from_db", "build_default_registry"])
def test_startup_preserves_authorized_active_predictor_after_same_artifact_failed_retry(isolated_db, startup):
    db, checkpoints = isolated_db
    model = seed_standard_model(db, checkpoints, 72, failed_retry=True)
    key = f"fama_trained_model_{model.id_modelo}"
    if startup == "register_from_db":
        registry = ModelRegistry()
        active = registry.register_from_db(db, checkpoints_root=checkpoints)
    else:
        registry = build_default_registry()
        active = registry.get_active_predictor()

    assert active is registry.get(key)
    assert registry.get_default_model_id() == key
    assert registry.get(str(model.id_modelo)) is active
    assert registry.get("trained_72.pt") is active
    assert db.get(Modelo, model.id_modelo).activo is True
    newest = db.query(ModelEvaluation).filter_by(id_modelo=model.id_modelo, split="val").order_by(
        ModelEvaluation.id_evaluation.desc()).first()
    assert newest.status == "failed"


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
