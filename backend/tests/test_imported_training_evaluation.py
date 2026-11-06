"""T5 at public checkpoint, training, registry and HTTP interfaces; synthetic CPU only."""
from copy import deepcopy
import pytest
import torch


def checkpoint_payload():
    from poc.preprocess import build_gpu_audio_frontend_contract
    audio = dict(target_sr=8000, duration_seconds=1.0, n_mels=32, n_fft=256,
                 hop_length=64, f_min=0.0, f_max=4000.0, use_gpu_frontend=False)
    profile = dict(architecture="audio_cnn", channels=1, preprocessing="mono_mel",
                   windowing="energy_peak_pad", window_hop_seconds=0.5, audio=audio)
    identity = dict(owner_id=1, dataset_id="a"*32, snapshot_id="b"*32,
                    snapshot_manifest_sha256="c"*64, preparation_version="d"*64,
                    profile=profile, classes=["zebra", "ants"],
                    class_to_index={"zebra": 0, "ants": 1}, provenance={"source": "synthetic"})
    contract = build_gpu_audio_frontend_contract(sample_rate=8000, duration_seconds=1.0,
        n_mels=32, n_fft=256, hop_length=64, f_min=0.0, f_max=4000.0)
    return dict(job_id="synthetic-t5", dataset_name="imported:"+"a"*32, dataset_id=None,
                architecture="AudioCNN", classes=["zebra", "ants"], audio_config=audio,
                windowing_config={"hop_seconds": 0.5, "aggregation_mode": "max", "gem_p": 3.0,
                                  "vad_threshold": 0.0}, preprocessing_contract=contract,
                imported_source=identity, state_dict={"synthetic_metadata": torch.zeros(4096)})


def test_lazy_imported_predictor_explicit_weight_load_is_idempotent(tmp_path, monkeypatch):
    import hashlib
    from poc.train import AudioCNN
    from app.services.predictors.trained_predictor import TrainedModelPredictor

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    payload = checkpoint_payload()
    model = AudioCNN(num_classes=2)
    payload["state_dict"] = model.state_dict()
    path = tmp_path / "explicit-load.pt"
    torch.save(payload, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    predictor = TrainedModelPredictor(path, lazy_load=True, expected_checkpoint_sha256=digest)
    assert predictor.model is None
    assert predictor.metadata.loaded_checkpoint_sha256 is None
    assert predictor.metadata.classes == ["zebra", "ants"]
    assert predictor.imported_source == payload["imported_source"]
    predictor.load_weights()
    loaded = predictor.model
    assert loaded is not None
    assert next(loaded.parameters()).device.type == "cpu"
    assert predictor.metadata.loaded_checkpoint_sha256 == digest
    assert predictor.metadata.classes == predictor.classes == ["zebra", "ants"]
    assert predictor.imported_source == payload["imported_source"]
    for name, expected in payload["state_dict"].items():
        assert torch.equal(loaded.state_dict()[name], expected)
    predictor.load_weights()
    assert predictor.model is loaded
    assert predictor.metadata.loaded_checkpoint_sha256 == digest
    assert predictor.metadata.classes == ["zebra", "ants"]


def test_fresh_active_legacy_registry_loads_weights_before_return(training_env):
    import hashlib
    from poc.train import AudioCNN
    from app.models.training import Modelo
    from app.services.registry import ModelRegistry

    runtime, sessions, _, _ = training_env
    payload = checkpoint_payload()
    payload.pop("imported_source")
    payload.pop("job_id")
    payload["dataset_id"] = None
    payload["dataset_name"] = "Historical"
    payload["state_dict"] = AudioCNN(num_classes=2).state_dict()
    runtime.checkpoints_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = runtime.checkpoints_dir / "legacy-active.pt"
    torch.save(payload, checkpoint)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    with sessions() as db:
        row = Modelo(arquitectura="AudioCNN", clase_objetivo="Historical",
            ruta_binario_gcp=checkpoint.as_uri(), hash_binario=digest,
            epocas=1, tasa_aprendizaje=0.001, tamano_lote=1, activo=True, estado="legacy")
        db.add(row)
        db.commit()
        key = f"fama_trained_model_{row.id_modelo}"
        registry = ModelRegistry()
        predictor = registry.register_from_db(db, runtime.checkpoints_dir)
        assert predictor is not None
        assert predictor.model is not None
        assert predictor.metadata.loaded_checkpoint_sha256 == digest
        assert predictor.classes == ["zebra", "ants"]
        assert registry.get() is predictor
        assert registry.get_default_model_id() == key


def test_imported_evaluation_failure_preserves_checkpoint_and_previous_active(cohort, training_env, tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path
    from app.models.training import Modelo, ModelEvaluation
    from app.services import training
    from app.services.evaluations import EvaluationService
    from app.services.imported_training_source import ImportedTrainingSource
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.services.registry import ModelRegistry, ModelNotFoundError
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources

    runtime, _, _, process = training_env
    sessions = cohort[0].sessions
    migrate_imported_sources(sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "failure-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    monkeypatch.setattr(training, "SessionLocal", sessions)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    originals = {row["member_id"]: row["sha256"]
                 for row, _ in cohort[0].iter_verified(1, cohort[1]["id"])}
    with sessions() as db:
        previous = Modelo(arquitectura="existing", clase_objetivo="Historical",
            ruta_binario_gcp="models/previous.pt", epocas=1, tasa_aprendizaje=0.001,
            tamano_lote=1, activo=True, estado="legacy")
        db.add(previous)
        db.commit()
        previous_id = previous.id_modelo
    class Inline:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    process.side_effect = Inline
    real_predict = TrainedModelPredictor.predict
    changed = []
    def mutate_private_copy_then_predict(predictor, path):
        if not changed:
            path = Path(path)
            assert path.parent.name.startswith("imported-evaluation-")
            assert not path.is_relative_to(cohort[0].root)
            path.chmod(0o600)
            with path.open("ab") as output:
                output.write(b"x")
            changed.append(path)
        return real_predict(predictor, path)
    monkeypatch.setattr(TrainedModelPredictor, "predict", mutate_private_copy_then_predict)
    admitted = runtime.start_training("", imported_dataset_id=cohort[5], snapshot_id=cohort[1]["id"],
        imported_prepared_version=prepared["version_id"], owner_id=1,
        architecture="AudioCNN", epochs=1, batch_size=2, early_stopping=False)
    assert admitted["status"] == "started"
    progress = runtime.get_progress(owner_id=1)
    assert progress["status"] == "failed", progress
    assert progress["error_message"] == "Audio changed during inference"
    assert len(changed) == 1
    assert not changed[0].exists()
    with sessions() as db:
        history = runtime.get_history(db, owner_id=1)
        entry, = [row for row in history if row["id"] != previous_id]
        assert entry["status"] == "standard_eval_failed"
        assert entry["active"] is False
        assert next(row for row in history if row["id"] == previous_id)["active"] is True
        checkpoint = runtime.checkpoints_dir / entry["filename"]
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == entry["sha256"]
        association = runtime.imported_sources.model_source(1, entry["id"])
        payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
        assert payload["imported_source"] == association
        assert payload["audio_config"] == association["profile"]["audio"]
        assert association["preparation_version"] == prepared["version_id"]
        assert payload["classes"] == association["classes"] == ["ants", "zebra"]
        # Discover attempt IDs only; report/state observations use the public service.
        ids = [row.id_evaluation for row in db.query(ModelEvaluation).filter_by(id_modelo=entry["id"]).all()]
        reports = [EvaluationService(db).read(attempt_id) for attempt_id in ids]
        assert sorted(report["split"] for report in reports) == ["test", "val"]
        for report in reports:
            assert report["status"] == "failed"
            assert report["report"] is None
            assert report["error_reason"] == "Audio changed during inference"
            assert report["checkpoint_sha256"] == entry["sha256"]
        registry = ModelRegistry()
        key = f"fama_trained_model_{entry['id']}"
        assert key not in [meta.id for meta in registry.list_models()]
        public_errors = registry.publish_from_db(db, runtime.checkpoints_dir)
        assert all(error.get("model_id") != key for error in public_errors)
        errors = registry.publish_from_db(db, runtime.checkpoints_dir, owner_id=1)
        assert any(error.get("model_id") == key and error["code"] == "standard_evaluation_invalid"
                   for error in errors)
        assert key not in [meta.id for meta in registry.list_models(owner_id=1)]
        with pytest.raises(ModelNotFoundError):
            registry.get(key, owner_id=1)
    assert {row["member_id"]: row["sha256"]
            for row, _ in cohort[0].iter_verified(1, cohort[1]["id"])} == originals


def test_imported_checkpoint_restores_explicit_non_alphabetical_classes(tmp_path):
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    path = tmp_path / "explicit.pt"
    torch.save(checkpoint_payload(), path)
    predictor = TrainedModelPredictor(path, lazy_load=True)
    assert predictor.classes == ["zebra", "ants"]


@pytest.mark.parametrize("damage", ["missing_classes", "reordered_classes", "audio_drift",
                                   "missing_source", "dataset_drift"])
def test_imported_checkpoint_rejects_incomplete_or_conflicting_identity(tmp_path, damage):
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.services.predictors.base import ModelWeightsError
    payload = deepcopy(checkpoint_payload())
    if damage == "missing_classes":
        payload.pop("classes")
    elif damage == "reordered_classes":
        payload["classes"].reverse()
    elif damage == "audio_drift":
        payload["audio_config"] = dict(payload["audio_config"], f_min=50.0)
    elif damage == "missing_source":
        payload.pop("imported_source")
    else:
        payload["dataset_name"] = "imported:"+"e"*32
    path = tmp_path / "invalid.pt"
    torch.save(payload, path)
    before = path.read_bytes()
    with pytest.raises(ModelWeightsError, match="importad"):
        TrainedModelPredictor(path, lazy_load=True)
    assert path.read_bytes() == before


def test_legacy_checkpoint_without_classes_keeps_bird_fallback(tmp_path):
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.services.predictors.base import DEFAULT_CHILEAN_BIRD_CLASSES
    path = tmp_path / "legacy.pt"
    torch.save({"architecture": "AudioCNN", "state_dict": {"synthetic": torch.zeros(4096)}}, path)
    assert TrainedModelPredictor(path, lazy_load=True).classes == list(DEFAULT_CHILEAN_BIRD_CLASSES)


def test_standard_inspection_accepts_explicit_imported_identity(tmp_path):
    import hashlib
    from app.services.standard_evaluation_guard import inspect_checkpoint
    path = tmp_path / "standard.pt"
    payload = checkpoint_payload()
    torch.save(payload, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    inspection = inspect_checkpoint(tmp_path, path, digest)
    assert inspection.sha256 == digest
    assert inspection.payload["classes"] == ["zebra", "ants"]
    assert inspection.payload["imported_source"] == payload["imported_source"]
    assert inspection.payload["dataset_id"] is None


from tests.test_dataset_import_api import imports
from tests.test_imported_dataset_preparation import cohort, create
from tests.test_training_flow import training_env


def _complete_imported_cpu_worker(cohort, training_env, tmp_path, monkeypatch):
    from app.services import training
    from app.models.training import Modelo
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    from app.services.standard_evaluation_guard import select_admitted_standard_pair
    from app.services.evaluations import EvaluationService
    runtime, _, _, process = training_env
    sessions = cohort[0].sessions
    migrate_imported_sources(sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    monkeypatch.setattr(training, "SessionLocal", sessions)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with sessions() as db:
        previous = Modelo(arquitectura="existing", clase_objetivo="Historical",
            ruta_binario_gcp="models/previous.pt", epocas=1, tasa_aprendizaje=0.001,
            tamano_lote=1, activo=True, estado="legacy")
        db.add(previous)
        db.commit()
        previous_id = previous.id_modelo
    class Inline:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    process.side_effect = Inline
    result = runtime.start_training("", imported_dataset_id=cohort[5], snapshot_id=cohort[1]["id"],
        imported_prepared_version=prepared["version_id"], owner_id=1,
        architecture="AudioCNN", epochs=1, batch_size=2, early_stopping=False)
    assert result["status"] == "started"
    progress = runtime.get_progress(owner_id=1)
    assert progress["status"] == "completed", (
        f"error_message={progress['error_message']!r}\nlogs={progress['logs']!r}"
    )
    with sessions() as db:
        imported, = [r for r in runtime.get_history(db, owner_id=1) if r["id"] != previous_id]
        assert imported["status"] == "standard_eval_completed"
        assert imported["active"] is False
        assert imported["classes"] == ["ants", "zebra"]
        association = runtime.imported_sources.model_source(1, imported["id"])
        assert association["preparation_version"] == prepared["version_id"]
        pair = select_admitted_standard_pair(db.get(Modelo, imported["id"]), db, runtime.checkpoints_dir)
        assert pair.val_identity.classes == pair.test_identity.classes == ["ants", "zebra"]
        assert pair.val_identity.predictor_config == pair.test_identity.predictor_config
        for split, attempt_id in (("val", pair.val_id), ("test", pair.test_id)):
            report = EvaluationService(db).read(attempt_id)
            assert report["status"] == "completed"
            assert report["split"] == split
            assert report["dataset"] == "imported:" + cohort[5]
            assert report["checkpoint_sha256"] == pair.val_identity.checkpoint_sha256
            assert report["sample_count"] == 2
            assert report["classes"] == ["ants", "zebra"]
        public_history = runtime.get_history(db)
        assert [r["id"] for r in public_history] == [previous_id]
        assert public_history[0]["active"] is True
        assert [r["id"] for r in runtime.get_history(db, owner_id=2)] == [previous_id]
        return runtime, sessions, imported["id"], association


def test_imported_cpu_worker_completes_private_coherent_val_test(cohort, training_env, tmp_path, monkeypatch):
    _complete_imported_cpu_worker(cohort, training_env, tmp_path, monkeypatch)


def test_imported_registry_is_private_to_exact_owner(cohort, training_env, tmp_path, monkeypatch):
    from app.models.training import Modelo
    from app.services.registry import ModelRegistry, ModelNotFoundError

    runtime, sessions, model_id, association = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch
    )
    registry = ModelRegistry()
    key = f"fama_trained_model_{model_id}"
    with sessions() as db:
        row = db.get(Modelo, model_id)
        from pathlib import Path
        checkpoint = runtime.checkpoints_dir / Path(row.ruta_binario_gcp).name
        aliases = (key, str(model_id), checkpoint.name, checkpoint.stem)
        # Anonymous publication must already be safe, before exercising the
        # owner-specific extension of the same public interface.
        errors = registry.publish_from_db(db, runtime.checkpoints_dir)
        assert key not in [meta.id for meta in registry.list_models()]
        assert all(error.get("model_id") != key for error in errors)
        assert registry.get_default_model_id() is None
        for alias in aliases:
            with pytest.raises(ModelNotFoundError):
                registry.get(alias)

        registry.publish_from_db(db, runtime.checkpoints_dir, owner_id=1)
        assert registry.get_default_model_id() is None
        assert key not in [meta.id for meta in registry.list_models()]
        assert key not in [meta.id for meta in registry.list_models(owner_id=2)]
        assert key in [meta.id for meta in registry.list_models(owner_id=1)]
        predictor = registry.get(key, owner_id=1)
        assert predictor.classes == ["ants", "zebra"]
        assert predictor.expected_checkpoint_sha256 == row.hash_binario
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        assert payload["imported_source"] == association
        for alias in aliases:
            assert registry.get(alias, owner_id=1) is predictor
            for owner in (None, 2):
                with pytest.raises(ModelNotFoundError) as denied:
                    registry.get(alias, owner_id=owner)
                assert not any(private_alias in str(denied.value) for private_alias in aliases)
        for owner in (None, 2):
            errors = registry.publish_from_db(db, runtime.checkpoints_dir, owner_id=owner)
            assert all(error.get("model_id") != key for error in errors)
            with pytest.raises(ModelNotFoundError) as missing:
                registry.get("unknown", owner_id=owner)
            assert key not in str(missing.value)
        with pytest.raises((ModelNotFoundError, ValueError)):
            registry.set_default_model(key)
        assert registry.get_default_model_id() is None


def test_imported_registry_missing_association_schema_is_private(cohort, training_env, tmp_path, monkeypatch):
    from app.models.imported_training_source import ImportedModelSource
    from app.services.predictors.base import ModelWeightsError
    from app.services.registry import ModelRegistry
    from tests.test_model_registry import FakeAudioPredictor

    runtime, sessions, model_id, _ = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch
    )
    # Only this disposable in-memory database loses the optional association
    # table; application startup and migration behavior remain untouched.
    ImportedModelSource.__table__.drop(sessions.kw["bind"])
    registry = ModelRegistry()
    legacy = FakeAudioPredictor("legacy-public", "Legacy public")
    registry.register(legacy, is_default=True)
    with sessions() as db:
        errors = registry.publish_from_db(db, runtime.checkpoints_dir)
    key = f"fama_trained_model_{model_id}"
    assert all(error.get("model_id") != key for error in errors)
    assert key not in [meta.id for meta in registry.list_models()]
    assert registry.get("legacy-public") is legacy
    # Schema absence must redact identity, not bypass the helper's active
    # persisted sentinel without a checkpoint hash and silently use a fallback.
    with pytest.raises(ModelWeightsError) as blocked:
        registry.get()
    assert str(blocked.value) == "Modelo persistido no disponible."


def test_registry_unknown_id_preserves_public_legacy_message():
    from app.services.registry import ModelRegistry, ModelNotFoundError
    from tests.test_model_registry import FakeAudioPredictor

    registry = ModelRegistry()
    registry.register(FakeAudioPredictor("legacy-public", "Legacy public"))
    with pytest.raises(ModelNotFoundError) as missing:
        registry.get("unknown")
    assert str(missing.value) == (
        "Modelo 'unknown' no encontrado en el catálogo. Modelos disponibles: ['legacy-public']"
    )


def test_imported_eager_predictor_cannot_register_publicly(cohort, training_env, tmp_path, monkeypatch):
    from pathlib import Path
    from app.models.training import Modelo
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.services.registry import ModelRegistry

    runtime, sessions, model_id, _ = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch
    )
    with sessions() as db:
        row = db.get(Modelo, model_id)
        checkpoint = runtime.checkpoints_dir / Path(row.ruta_binario_gcp).name
        predictor = TrainedModelPredictor(checkpoint_path=checkpoint,
            model_id="eager-imported", lazy_load=False,
            expected_checkpoint_sha256=row.hash_binario)
    registry = ModelRegistry()
    with pytest.raises(ValueError):
        registry.register(predictor, is_default=True)
    assert registry.list_models() == []
    assert registry.get_default_model_id() is None


def test_removing_last_public_default_does_not_activate_imported(cohort, training_env, tmp_path, monkeypatch):
    from app.services.registry import ModelRegistry
    from app.services.predictors.base import ModelWeightsError
    from tests.test_model_registry import FakeAudioPredictor

    runtime, sessions, model_id, _ = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch
    )
    registry = ModelRegistry()
    registry.register(FakeAudioPredictor("legacy-public", "Legacy public"), is_default=True)
    with sessions() as db:
        registry.publish_from_db(db, runtime.checkpoints_dir, owner_id=1)
    key = f"fama_trained_model_{model_id}"
    assert registry.get(key, owner_id=1).classes == ["ants", "zebra"]
    assert registry.unregister("legacy-public") is True
    assert registry.get_default_model_id() is None
    # The cold active sentinel has no FK, association, checkpoint or hash.
    # Its unknown identity stays redacted, without bypassing the default block.
    with pytest.raises(ModelWeightsError) as blocked:
        registry.get()
    assert str(blocked.value) == "Modelo persistido no disponible."
    assert registry.get(key, owner_id=1).classes == ["ants", "zebra"]
