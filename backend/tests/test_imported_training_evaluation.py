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


def test_existing_imported_evaluation_rejects_audio_changed_during_inference(
        cohort, training_env, tmp_path, monkeypatch):
    from pathlib import Path
    from app.models.training import Modelo
    from app.services.imported_evaluation import evaluation_recordings
    from app.services.recording_evaluator import RecordingEvaluator
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.services.standard_evaluation_guard import inspect_checkpoint

    runtime, sessions, model_id, identity = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch)
    source = runtime.imported_sources.resolve(1, cohort[5], cohort[1]["id"],
        identity["preparation_version"], architecture="AudioCNN")
    originals = {row["member_id"]: row["sha256"]
                 for row, _ in cohort[0].iter_verified(1, cohort[1]["id"])}
    with sessions() as db:
        before = runtime.get_history(db, owner_id=1)
        model = db.get(Modelo, model_id)
        checkpoint = runtime.checkpoints_dir / Path(model.ruta_binario_gcp).name
        checkpoint_bytes = checkpoint.read_bytes()
        inspection = inspect_checkpoint(runtime.checkpoints_dir, checkpoint, model.hash_binario)
    predictor = TrainedModelPredictor(checkpoint, lazy_load=True)
    real_predict = predictor.predict
    changed = []
    def mutate_private_copy_then_predict(path):
        if not changed:
            path = Path(path)
            assert path.parent.name.startswith("imported-evaluation-")
            assert not path.is_relative_to(cohort[0].root)
            path.chmod(0o600)
            with path.open("ab") as output:
                output.write(b"x")
            changed.append(path)
        return real_predict(path)
    monkeypatch.setattr(predictor, "predict", mutate_private_copy_then_predict)
    with evaluation_recordings(source) as recordings:
        evaluator = RecordingEvaluator(recordings["val"], predictor,
            id_modelo=model_id, dataset="imported:" + cohort[5], split="val",
            checkpoint_sha256=inspection.sha256, predictor_config=inspection.configurations[0],
            preprocessing_config=inspection.configurations[1], aggregation_config=inspection.configurations[2])
        with pytest.raises(ValueError, match="Audio changed during inference"):
            evaluator.evaluate()
    assert len(changed) == 1 and not changed[0].exists()
    assert checkpoint.read_bytes() == checkpoint_bytes
    with sessions() as db:
        assert runtime.get_history(db, owner_id=1) == before
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


def publish_preexisting_imported_checkpoint(runtime, sessions, sources, *, owner_id,
        dataset_id, snapshot_id, prepared_version, filename=None):
    """Seed a historical artifact and real reports; never admit or train a job.

    Sources and preparation must already exist. Returns (model_id, identity), so
    owner-isolation tests can seed a second owner through the same fixture.
    """
    import hashlib
    import uuid
    from poc.train import AudioCNN
    from app.models.training import Modelo
    from app.models.imported_training_source import ImportedModelSource
    from app.services.imported_evaluation import evaluation_recordings
    from app.services.recording_evaluator import RecordingEvaluator
    from app.services.predictors.trained_predictor import TrainedModelPredictor
    from app.services.standard_evaluation_guard import (
        inspect_checkpoint, admitted_manifest_pair_provenance, ADMITTED_MANIFEST_PAIR_KEY)
    from app.services.evaluations import EvaluationService

    source = sources.resolve(owner_id, dataset_id, snapshot_id, prepared_version, architecture="AudioCNN")
    payload = checkpoint_payload()
    payload.update(imported_source=source["identity"], classes=source["classes"],
        dataset_name="imported:" + dataset_id, audio_config=source["identity"]["profile"]["audio"],
        job_id="historical-synthetic-" + uuid.uuid4().hex)
    audio = payload["audio_config"]
    from poc.preprocess import build_gpu_audio_frontend_contract
    payload["preprocessing_contract"] = build_gpu_audio_frontend_contract(
        sample_rate=audio["target_sr"], duration_seconds=audio["duration_seconds"],
        n_mels=audio["n_mels"], n_fft=audio["n_fft"], hop_length=audio["hop_length"],
        f_min=audio["f_min"], f_max=audio["f_max"])
    payload["windowing_config"]["hop_seconds"] = source["identity"]["profile"]["window_hop_seconds"]
    # Random CPU weights are only a valid synthetic historical checkpoint, not
    # evidence of training completion or model quality. Preserve the caller RNG.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(42)
        payload["state_dict"] = AudioCNN(num_classes=len(source["classes"])).state_dict()
    checkpoint = runtime.checkpoints_dir / (filename or ("historical-" + uuid.uuid4().hex + ".pt"))
    torch.save(payload, checkpoint)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    with sessions() as db:
        model = Modelo(arquitectura="AudioCNN", clase_objetivo="Historical imported fixture",
            ruta_binario_gcp=checkpoint.as_uri(), hash_binario=digest,
            tamano_bytes=checkpoint.stat().st_size, id_usuario=owner_id,
            epocas=1, tasa_aprendizaje=0.001, tamano_lote=2,
            activo=False, estado="standard_eval_completed")
        db.add(model)
        db.flush()
        model_id = model.id_modelo
        db.add(ImportedModelSource(model_id=model_id, owner_id=owner_id,
            dataset_id=dataset_id, snapshot_id=snapshot_id, identity=source["identity"]))
        db.commit()
        inspection = inspect_checkpoint(runtime.checkpoints_dir, checkpoint, digest)
        predictor = TrainedModelPredictor(checkpoint, lazy_load=True, expected_checkpoint_sha256=digest)
        with evaluation_recordings(source) as recordings:
            evaluators = [RecordingEvaluator(recordings[split], predictor,
                id_modelo=model_id, dataset=payload["dataset_name"], split=split,
                checkpoint_sha256=digest, predictor_config=inspection.configurations[0],
                preprocessing_config=inspection.configurations[1],
                aggregation_config=inspection.configurations[2]) for split in ("val", "test")]
            pair = admitted_manifest_pair_provenance(*(e.identity.manifest_sha256 for e in evaluators))
            service = EvaluationService(db)
            for evaluator in evaluators:
                identity = evaluator.identity.model_dump()
                identity["predictor_config"] = {
                    **identity["predictor_config"], ADMITTED_MANIFEST_PAIR_KEY: pair}
                evaluator.identity = type(evaluator.identity).model_validate(identity)
                attempt = service.create(evaluator.identity)["id_evaluation"]
                service.start(attempt)
                service.complete(attempt, evaluator.evaluate())
    return model_id, source["identity"]


def _complete_imported_cpu_worker(cohort, training_env, tmp_path, monkeypatch):
    """Compatibility fixture name: prepares existing artifacts, does not run a worker."""
    from app.models.training import Modelo
    from app.services.imported_training_source import ImportedTrainingSource
    from training.imported_dataset_preparation import ImportedDatasetPreparation
    from scripts.migrate_imported_training_source import migrate_imported_sources
    runtime = training_env[0]
    sessions = cohort[0].sessions
    migrate_imported_sources(sessions.kw["bind"], writers_stopped=True)
    preparations = ImportedDatasetPreparation(cohort[0], tmp_path / "imported-prepared")
    prepared = create(preparations, cohort)
    runtime.imported_sources = ImportedTrainingSource(preparations)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with sessions() as db:
        db.add(Modelo(arquitectura="existing", clase_objetivo="Historical",
            ruta_binario_gcp="models/previous.pt", epocas=1, tasa_aprendizaje=0.001,
            tamano_lote=1, activo=True, estado="legacy"))
        db.commit()
    model_id, identity = publish_preexisting_imported_checkpoint(
        runtime, sessions, runtime.imported_sources, owner_id=1,
        dataset_id=cohort[5], snapshot_id=cohort[1]["id"], prepared_version=prepared["version_id"])
    return runtime, sessions, model_id, identity


def test_existing_imported_checkpoint_has_private_coherent_val_test(cohort, training_env, tmp_path, monkeypatch):
    from app.models.training import Modelo
    from app.services.standard_evaluation_guard import select_admitted_standard_pair
    from app.services.evaluations import EvaluationService
    runtime, sessions, model_id, identity = _complete_imported_cpu_worker(
        cohort, training_env, tmp_path, monkeypatch)
    assert runtime.get_progress()["status"] == "idle"
    training_env[3].assert_not_called()
    with sessions() as db:
        pair = select_admitted_standard_pair(db.get(Modelo, model_id), db, runtime.checkpoints_dir)
        assert pair.val_identity.classes == pair.test_identity.classes == ["ants", "zebra"]
        assert pair.val_identity.predictor_config == pair.test_identity.predictor_config
        for split, attempt in (("val", pair.val_id), ("test", pair.test_id)):
            report = EvaluationService(db).read(attempt)
            assert report["status"] == "completed"
            assert report["split"] == split
            assert report["dataset"] == "imported:" + cohort[5]
            assert report["sample_count"] == 2
        owned = next(row for row in runtime.get_history(db, owner_id=1) if row["id"] == model_id)
        assert owned["imported_source"] == identity
        assert not owned["active"]
        assert all(row["id"] != model_id for row in runtime.get_history(db))
        assert all(row["id"] != model_id for row in runtime.get_history(db, owner_id=2))


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
