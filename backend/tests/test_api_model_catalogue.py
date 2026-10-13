"""Catalogue publication through HTTP, with isolated persistence and ML adapter."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

with patch("app.database.Base.metadata.create_all"):
    from app import main
from app.database import Base, get_db
from app.models.training import Modelo
from ml_core.classification_metrics import calculate_classification_report
from app.services.registry import ModelRegistry, get_model_registry
from app.services.predictors.trained_predictor import TrainedModelPredictor
from tests.test_model_registry import FakeAudioPredictor


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    from app.services.predictors import trained_predictor

    class MetadataPredictor(FakeAudioPredictor):
        """Controlled external ML adapter: metadata parsing, no tensor execution."""
        def __init__(self, checkpoint_path, model_id, name, is_default, lazy_load, dataset_name):
            if not lazy_load:
                raise RuntimeError("Catalogue must not initialize tensor inference")
            payload = json.loads(checkpoint_path.read_text())
            super().__init__(model_id, name, is_default)
            self._meta.classes = payload["classes"]
            self._meta.dataset_name = dataset_name
            self._meta.metrics = payload.get("metrics")

    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", MetadataPredictor)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    checkpoints_root = tmp_path / "checkpoints"
    checkpoints_root.mkdir()
    monkeypatch.setattr(main.training_service, "checkpoints_dir", checkpoints_root)
    registry = ModelRegistry(raw_data_root=tmp_path / "data" / "raw")
    selected = FakeAudioPredictor("selected", "Selected")
    registry.register(selected, is_default=True)

    def isolated_db():
        with sessions() as db:
            yield db

    main.app.dependency_overrides[get_db] = isolated_db
    main.app.dependency_overrides[get_model_registry] = lambda: registry
    client = TestClient(main.app, raise_server_exceptions=False)

    def persist(model_id=11, contents=None, route=None, dataset=None, active=True):
        checkpoint = checkpoints_root / f"trained_{model_id}.pt"
        checkpoint.write_text(contents if contents is not None else json.dumps({
            "classes": ["Motor sano", "Falla"], "padding": "x" * 11000,
        }))
        with sessions() as db:
            if dataset is not None:
                db.add(dataset)
            db.add(Modelo(id_modelo=model_id, conjunto_datos=dataset,
                          arquitectura="EfficientNet-B0", epocas=1,
                          tasa_aprendizaje=0.001, tamano_lote=2, activo=active,
                          ruta_binario_gcp=route or checkpoint.as_uri()))
            db.commit()
        return checkpoint

    try:
        yield client, registry, persist, engine
    finally:
        client.close()
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_model_registry, None)
        engine.dispose()


def add_evaluation(engine, model_id, split, status, *, y_true=None, y_pred=None,
                   schema_version=1, rejection_label=None,
                   failure_reason="synthetic internal failure"):
    from app.services.evaluations import EvaluationService

    y_true = y_true or ["a", "a", "b"]
    y_pred = y_pred or ["a", "b", "b"]
    identity = {
        "id_modelo": model_id, "schema_version": schema_version, "evaluator_version": "catalogue-test-v1",
        "checkpoint_sha256": "a" * 64, "dataset": "engine_diagnostics", "split": split,
        "manifest_sha256": "b" * 64, "classes": ["a", "b"], "sample_count": len(y_true),
        "predictor_config": {"name": "synthetic"},
        "preprocessing_config": {"sample_rate": 32000},
        "aggregation_config": {"method": "combined"}, "code_revision": None,
    }
    with Session(engine) as db:
        service = EvaluationService(db)
        attempt = service.create(identity)
        if status == "pending":
            return attempt
        attempt = service.start(attempt["id_evaluation"])
        if status == "running":
            return attempt
        if status == "failed":
            return service.fail(attempt["id_evaluation"], failure_reason)
        assert status == "completed"
        report = calculate_classification_report(
            y_true, y_pred, ["a", "b"], rejection_label=rejection_label)
        return service.complete(attempt["id_evaluation"], report)


def seed_standard_model(catalogue, model_id, *, state="standard_eval_completed", fault=None,
                        active=False, sample_counts=None):
    import hashlib
    import torch
    from app.models.dataset import ConjuntoDatos
    from app.services.recording_evaluator import EVALUATOR_VERSION
    from app.services.standard_evaluation_guard import (
        ADMITTED_MANIFEST_PAIR_KEY, admitted_manifest_pair_provenance,
        build_evaluation_configuration, resolve_training_audio,
    )
    from poc.preprocess import build_gpu_audio_frontend_contract

    client, _, persist, engine = catalogue
    with Session(engine, expire_on_commit=False) as db:
        dataset = ConjuntoDatos(nombre="engine_diagnostics", ruta_gcp="datasets/engine_diagnostics")
        db.add(dataset)
        db.commit()
        dataset_id, dataset_name = dataset.id_conjunto_datos, dataset.nombre
        db.expunge(dataset)
    checkpoint = persist(model_id, dataset=dataset, active=active)
    job_id = f"synthetic-job-{model_id}"
    training_audio = resolve_training_audio(dataset_name, None)
    preprocessing_contract = build_gpu_audio_frontend_contract(
        sample_rate=training_audio["target_sr"],
        duration_seconds=training_audio["duration_seconds"],
        n_mels=training_audio["n_mels"], n_fft=training_audio["n_fft"],
        hop_length=training_audio["hop_length"], f_min=training_audio["f_min"],
        f_max=training_audio["f_max"],
    )
    payload = {
        "dataset_id": dataset_id, "dataset_name": dataset_name,
        "job_id": job_id, "classes": ["a", "b"], "architecture": "EfficientNet-B0",
        "audio_config": None, "windowing_config": None,
        "preprocessing_contract": preprocessing_contract,
        "state_dict": {}, "test_padding": "x" * 11000,
        "source_directory": "/private/synthetic/path", "secret_marker": "synthetic-secret-marker",
    }
    torch.save(payload, checkpoint)
    checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    with Session(engine) as db:
        model = db.get(Modelo, model_id)
        model.estado = state
        model.hash_binario = checkpoint_hash
        db.commit()

    configs = dict(zip(
        ("predictor_config", "preprocessing_config", "aggregation_config"),
        build_evaluation_configuration(
            {"job_id": job_id, "architecture": payload["architecture"], "windowing_config": None},
            training_audio, payload["preprocessing_contract"])))
    if fault == "wrong_architecture":
        configs["predictor_config"] = {**configs["predictor_config"], "architecture": "Other"}
    if fault in ("config", "coherent_wrong_config"):
        configs["preprocessing_config"] = {
            **configs["preprocessing_config"], "silence_rms_threshold": 0.75,
        }
    evaluation_splits = ("val",) if fault == "missing_test" else ("val", "test")
    manifest_hashes = {"val": "d" * 64, "test": "e" * 64}
    sample_counts = sample_counts or {"val": 2, "test": 2}
    for split in evaluation_splits:
        split_configs = dict(configs)
        split_classes = ["a", "b"]
        split_hash = checkpoint_hash
        split_dataset = dataset_name
        schema_version = 2
        evaluator_version = EVALUATOR_VERSION
        manifest_pair = admitted_manifest_pair_provenance(
            manifest_hashes["val"], manifest_hashes["test"])
        if fault == "cross_generation_pair":
            manifest_pair = admitted_manifest_pair_provenance(
                "d" * 64, "f" * 64) if split == "val" else admitted_manifest_pair_provenance(
                    "a" * 64, "e" * 64)
        split_configs["predictor_config"] = {
            **split_configs["predictor_config"], ADMITTED_MANIFEST_PAIR_KEY: manifest_pair,
        }
        if fault == "missing_pair_identity" and split == "val":
            split_configs["predictor_config"].pop(ADMITTED_MANIFEST_PAIR_KEY)
        elif fault == "tampered_pair_identity" and split == "test":
            split_configs["predictor_config"][ADMITTED_MANIFEST_PAIR_KEY] = {
                **manifest_pair, "sha256": "f" * 64,
            }
        if fault == "wrong_hash":
            split_hash = "c" * 64
        elif fault == "wrong_classes":
            split_classes = ["b", "a"]
        elif fault == "wrong_job" and split == "test":
            split_configs["predictor_config"] = {**configs["predictor_config"], "job_id": "other-job"}
        elif fault == "wrong_config" and split == "test":
            split_configs["preprocessing_config"] = {**configs["preprocessing_config"], "crop": "left"}
        elif fault == "wrong_dataset" and split == "test":
            split_dataset = "AvesChilenas"
        elif fault == "wrong_schema":
            schema_version = 1
        elif fault == "wrong_evaluator":
            evaluator_version = "other-evaluator"
        count = sample_counts[split]
        labels = [split_classes[index % len(split_classes)] for index in range(count)]
        predictions = [label if index % 2 == 0 else "__recording_rejected__"
                       for index, label in enumerate(labels)]
        identity = {
            "id_modelo": model_id, "schema_version": schema_version,
            "evaluator_version": evaluator_version, "checkpoint_sha256": split_hash,
            "dataset": split_dataset, "split": split, "manifest_sha256": manifest_hashes[split],
            "classes": split_classes, "sample_count": count,
            **split_configs, "code_revision": None,
        }
        with Session(engine) as db:
            from app.services.evaluations import EvaluationService
            service = EvaluationService(db)
            attempt = service.create(identity)
            service.start(attempt["id_evaluation"])
            if schema_version == 2:
                report = calculate_classification_report(
                    labels, predictions, split_classes, rejection_label="__recording_rejected__")
            else:
                report = calculate_classification_report(labels, labels, split_classes)
            service.complete(attempt["id_evaluation"], report)
    return client, checkpoint, payload, checkpoint_hash


def install_torch_metadata_adapter(monkeypatch):
    import torch
    from app.services.predictors import trained_predictor
    from tests.test_model_registry import FakeAudioPredictor

    class CheckpointMetadataPredictor(FakeAudioPredictor):
        def __init__(self, checkpoint_path, model_id, name, is_default, lazy_load, dataset_name):
            assert lazy_load is True
            payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
            super().__init__(model_id, name, is_default)
            self._meta.classes = payload["classes"]
            self._meta.dataset_name = dataset_name
            self.model = None

        def predict(self, audio_path):
            pytest.fail("Registry guard must not run inference")

    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", CheckpointMetadataPredictor)


@pytest.mark.parametrize("fault", [
    "pending", "failed", "component", "missing_test", "wrong_hash", "wrong_classes",
    "wrong_config", "coherent_wrong_config", "wrong_architecture", "wrong_job", "wrong_dataset",
    "wrong_schema", "wrong_evaluator", "missing_pair_identity", "tampered_pair_identity",
])
def test_catalogue_rejects_unverified_standard_models_before_publication(catalogue, monkeypatch, fault):
    states = {
        "pending": "standard_eval_pending", "failed": "standard_eval_failed",
        "component": "standard_component_evaluated",
    }
    state = states.get(fault, "standard_eval_completed")
    client, _, _, _ = seed_standard_model(
        catalogue, 401, state=state, fault=None if fault in states else fault)
    install_torch_metadata_adapter(monkeypatch)

    response = client.get("/api/models")
    payload = response.json()
    assert response.status_code == 200
    assert all(model["id"] != "fama_trained_model_401" for model in payload["models"])
    assert payload["publication_errors"] == [
        {"model_id": "fama_trained_model_401", "code": "standard_evaluation_invalid"},
    ]
    assert "/private/synthetic/path" not in response.text
    assert "synthetic-secret-marker" not in response.text


def test_catalogue_rejects_val_test_from_different_admitted_manifest_pairs(catalogue, monkeypatch):
    # These split manifests come from separate admissions; individual identities match
    # the current artifact/configuration, but there is no shared pair identity.
    client, _, _, _ = seed_standard_model(catalogue, 400, fault="cross_generation_pair")
    install_torch_metadata_adapter(monkeypatch)

    response = client.get("/api/models")

    assert response.status_code == 200
    assert all(model["id"] != "fama_trained_model_400" for model in response.json()["models"])
    assert response.json()["publication_errors"] == [
        {"model_id": "fama_trained_model_400", "code": "standard_evaluation_invalid"},
    ]


def test_catalogue_accepts_shared_manifest_pair_with_independent_split_manifests_and_counts(
    catalogue, monkeypatch,
):
    import hashlib
    import json

    client, _, _, _ = seed_standard_model(catalogue, 400, sample_counts={"val": 2, "test": 3})
    install_torch_metadata_adapter(monkeypatch)

    response = client.get("/api/models")

    assert response.status_code == 200
    model = next(model for model in response.json()["models"]
                 if model["id"] == "fama_trained_model_400")
    val = model["evaluations"]["val"]["latest_completed"]["provenance"]
    test = model["evaluations"]["test"]["latest_completed"]["provenance"]
    assert val["manifest_sha256"] != test["manifest_sha256"]
    assert val["sample_count"] == 2
    assert test["sample_count"] == 3
    val_pair = val["predictor_config"]["admitted_val_test_manifest_pair"]
    assert test["predictor_config"]["admitted_val_test_manifest_pair"] == val_pair
    canonical = json.dumps({
        "domain": "fama.standard-evaluation.admitted-val-test-manifest-pair",
        "version": 1,
        "val_manifest_sha256": val["manifest_sha256"],
        "test_manifest_sha256": test["manifest_sha256"],
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert val_pair == {"version": 1, "sha256": hashlib.sha256(canonical).hexdigest()}


def test_catalogue_keeps_valid_standard_and_legacy_predictors_lazy(catalogue, monkeypatch):
    import hashlib

    client, registry, _, _ = catalogue
    client, checkpoint, _, _ = seed_standard_model(catalogue, 402)
    install_torch_metadata_adapter(monkeypatch)

    response = client.get("/api/models")
    assert response.status_code == 200
    payload = response.json()
    standard = next(model for model in payload["models"] if model["id"] == "fama_trained_model_402")
    assert standard["has_weights"] is True
    assert standard["evaluations"]["val"]["latest_completed"]["provenance"]["checkpoint_sha256"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert registry.get("402").model is None
    assert registry.get("selected").model_id == "selected"


def test_catalogue_preserves_cached_standard_predictor_after_same_artifact_failed_attempt(catalogue, monkeypatch):
    client, registry, _, engine = catalogue
    client, _, _, _ = seed_standard_model(catalogue, 403)
    install_torch_metadata_adapter(monkeypatch)
    first = client.get("/api/models")
    assert first.status_code == 200
    assert any(model["id"] == "fama_trained_model_403" for model in first.json()["models"]), first.json()
    cached = registry.get("fama_trained_model_403")
    assert registry.get("403") is cached
    default_before = registry.get_default_model_id()

    add_evaluation(engine, 403, "val", "failed")
    response = client.get("/api/models")
    assert response.status_code == 200
    model = next(model for model in response.json()["models"] if model["id"] == "fama_trained_model_403")
    assert model["evaluations"]["val"]["latest_attempt"]["status"] == "failed"
    assert model["evaluations"]["val"]["latest_completed"] is not None
    assert response.json()["publication_errors"] == []
    assert registry.has_model("fama_trained_model_403")
    assert registry.get("fama_trained_model_403") is cached
    assert registry.get("403") is cached
    assert registry.get_default_model_id() == default_before


@pytest.mark.parametrize("retry_status", ["pending", "failed"])
def test_catalogue_preserves_old_coherent_pair_after_new_incomplete_attempt(
    catalogue, monkeypatch, retry_status,
):
    from app.models.training import ModelEvaluation
    from app.schemas.evaluation import EvaluationIdentity
    from app.services.evaluations import EvaluationService
    from app.services.standard_evaluation_guard import (
        ADMITTED_MANIFEST_PAIR_KEY, admitted_manifest_pair_provenance,
    )

    client, registry, _, engine = catalogue
    client, _, _, _ = seed_standard_model(catalogue, 403, active=True)
    install_torch_metadata_adapter(monkeypatch)
    first = client.get("/api/models")
    assert any(model["id"] == "fama_trained_model_403" for model in first.json()["models"])
    cached = registry.get("fama_trained_model_403")
    default_before = registry.get_default_model_id()

    with Session(engine) as db:
        old_val = db.query(ModelEvaluation).filter_by(
            id_modelo=403, split="val", status="completed").one()
        old_manifest = old_val.manifest_sha256
        identity = {field: getattr(old_val, field) for field in EvaluationIdentity.model_fields}
        identity["manifest_sha256"] = "f" * 64
        identity["predictor_config"] = {
            **identity["predictor_config"],
            ADMITTED_MANIFEST_PAIR_KEY: admitted_manifest_pair_provenance("f" * 64, "c" * 64),
        }
        evaluations = EvaluationService(db)
        retry = evaluations.create(identity)
        if retry_status == "failed":
            evaluations.start(retry["id_evaluation"])
            evaluations.fail(retry["id_evaluation"], "synthetic admitted retry failure")

    response = client.get("/api/models")
    model = next(model for model in response.json()["models"] if model["id"] == "fama_trained_model_403")
    val = model["evaluations"]["val"]
    assert response.status_code == 200
    assert val["latest_attempt"]["status"] == retry_status
    assert val["latest_completed"]["provenance"]["manifest_sha256"] == old_manifest
    assert response.json()["publication_errors"] == []
    assert registry.get("fama_trained_model_403") is cached
    assert registry.get("403") is cached
    assert registry.get_default_model_id() == default_before
    with Session(engine) as db:
        assert db.get(Modelo, 403).activo is True


def test_catalogue_evicts_cached_standard_predictor_when_checkpoint_identity_changes(catalogue, monkeypatch):
    from app.services.registry import ModelNotFoundError

    client, registry, _, _ = catalogue
    client, checkpoint, _, _ = seed_standard_model(catalogue, 404, active=True)
    install_torch_metadata_adapter(monkeypatch)
    first = client.get("/api/models")
    assert any(model["id"] == "fama_trained_model_404" for model in first.json()["models"])
    cached = registry.get("fama_trained_model_404")
    assert registry.get("404") is cached

    checkpoint.write_bytes(checkpoint.read_bytes() + b"changed-synthetic-checkpoint")
    response = client.get("/api/models")
    assert response.status_code == 200
    assert all(model["id"] != "fama_trained_model_404" for model in response.json()["models"])
    assert response.json()["publication_errors"] == [
        {"model_id": "fama_trained_model_404", "code": "standard_evaluation_invalid"},
    ]
    assert not registry.has_model("fama_trained_model_404")
    with pytest.raises(ModelNotFoundError):
        registry.get("404")


def test_catalogue_exposes_full_val_test_evaluations_and_distinguishes_zero_from_absence(catalogue):
    client, _, persist, engine = catalogue
    persist(101, active=False, contents=json.dumps({
        "classes": ["Motor sano", "Falla"], "metrics": {"accuracy": 0.81}, "padding": "x" * 11000,
    }))
    persist(102, active=False)
    with Session(engine) as db:
        legacy = db.get(Modelo, 101)
        legacy.precision = 0.9375
        db.commit()
    val = add_evaluation(engine, 101, "val", "completed")
    test = add_evaluation(engine, 101, "test", "completed", y_true=["a"], y_pred=["a"])

    response = client.get("/api/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluation_catalogue_status"] == "available"
    models = {item["id"]: item for item in payload["models"]}
    evaluation = models["fama_trained_model_101"]["evaluations"]
    assert models["fama_trained_model_102"]["evaluations"] is None
    assert models["fama_trained_model_101"]["metrics"] == {"accuracy": 0.81}
    assert "precision_macro" not in models["fama_trained_model_101"]["metrics"]
    assert evaluation["val"]["latest_attempt"]["id_evaluation"] == val["id_evaluation"]
    assert evaluation["val"]["latest_completed"]["id_evaluation"] == val["id_evaluation"]
    assert evaluation["val"]["latest_completed"]["provenance"] == {
        "schema_version": 1, "evaluator_version": "catalogue-test-v1",
        "checkpoint_sha256": "a" * 64, "dataset": "engine_diagnostics", "split": "val",
        "manifest_sha256": "b" * 64, "classes": ["a", "b"],
        "predictor_config": {"name": "synthetic"},
        "preprocessing_config": {"sample_rate": 32000},
        "aggregation_config": {"method": "combined"}, "sample_count": 3,
        "code_revision": None,
    }
    assert evaluation["val"]["latest_completed"]["report"] == calculate_classification_report(
        ["a", "a", "b"], ["a", "b", "b"], ["a", "b"])
    assert evaluation["val"]["latest_completed"]["report"]["metrics"]["accuracy"] == 2 / 3
    assert evaluation["val"]["latest_completed"]["report"]["coverage"] == {
        "absent_classes": [], "complete": True,
    }
    assert evaluation["test"]["latest_attempt"]["id_evaluation"] == test["id_evaluation"]
    test_report = evaluation["test"]["latest_completed"]["report"]
    assert test_report == calculate_classification_report(["a"], ["a"], ["a", "b"])
    assert test_report["metrics"]["accuracy"] == 1.0
    assert test_report["coverage"] == {"absent_classes": ["b"], "complete": False}
    assert test_report["per_class"][1] == {
        "label": "b", "precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0,
        "zero_denominator": {"precision": True, "recall": True, "f1": True},
    }


def test_catalogue_selects_latest_attempt_and_completed_in_one_read_only_batch(catalogue, monkeypatch):
    import torch
    from app.services.evaluations import EvaluationService
    from tests.test_model_registry import FakeAudioPredictor

    client, registry, persist, engine = catalogue
    for model_id in (201, 202, 203):
        persist(model_id, active=False)
    registry.register(FakeAudioPredictor("car-engine-diagnostics-super-ensemble", "Synthetic ensemble"))
    registry.register(FakeAudioPredictor("fama_trained_model_201-alias", "Noncanonical alias"))
    completed = add_evaluation(engine, 201, "val", "completed")
    private_path = "/srv/private-evaluation/checkpoints/secret-weights.pt"
    secret_marker = "SYNTHETIC-SECRET-catalogue-7f82"
    failed = add_evaluation(
        engine, 201, "val", "failed", failure_reason=f"{private_path} token={secret_marker}")
    pending = add_evaluation(engine, 201, "test", "pending")
    running = add_evaluation(engine, 202, "val", "running")

    def forbidden(*args, **kwargs):
        pytest.fail("Catalogue read must not infer, mutate evaluation state, or load weights")
    monkeypatch.setattr(FakeAudioPredictor, "predict", forbidden)
    monkeypatch.setattr(torch, "load", forbidden)
    for method in ("create", "start", "complete", "fail", "read"):
        monkeypatch.setattr(EvaluationService, method, forbidden)

    evaluation_reads = []
    mutations = []
    def observe_sql(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().lower()
        if "model_evaluation" in normalized and normalized.startswith("select"):
            evaluation_reads.append(statement)
        if normalized.startswith(("insert", "update", "delete")):
            mutations.append(statement)
    event.listen(engine, "before_cursor_execute", observe_sql)
    try:
        response = client.get("/api/models")
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)

    assert response.status_code == 200
    assert len(evaluation_reads) == 1
    assert not mutations
    payload = response.json()
    models = {item["id"]: item for item in payload["models"]}
    val = models["fama_trained_model_201"]["evaluations"]["val"]
    assert val["latest_attempt"]["id_evaluation"] == failed["id_evaluation"]
    assert val["latest_attempt"]["status"] == "failed"
    assert val["latest_completed"]["id_evaluation"] == completed["id_evaluation"]
    assert private_path not in response.text
    assert secret_marker not in response.text
    assert "error_reason" not in response.text
    assert val["latest_completed"]["report"]["metrics"]["accuracy"] == 2 / 3
    test = models["fama_trained_model_201"]["evaluations"]["test"]
    assert test["latest_attempt"]["id_evaluation"] == pending["id_evaluation"]
    assert test["latest_attempt"]["status"] == "pending"
    assert test["latest_completed"] is None
    other = models["fama_trained_model_202"]["evaluations"]["val"]
    assert other["latest_attempt"]["id_evaluation"] == running["id_evaluation"]
    assert other["latest_attempt"]["status"] == "running"
    assert other["latest_completed"] is None
    assert models["fama_trained_model_203"]["evaluations"] is None
    assert models["car-engine-diagnostics-super-ensemble"]["evaluations"] is None
    assert models["fama_trained_model_201-alias"]["evaluations"] is None
    assert set(models) == {
        "selected", "fama_trained_model_201", "fama_trained_model_202",
        "fama_trained_model_203", "car-engine-diagnostics-super-ensemble",
        "fama_trained_model_201-alias",
    }
    registered_before = [metadata.id for metadata in registry.list_models()]
    assert client.get("/api/models").status_code == 200
    assert [metadata.id for metadata in registry.list_models()] == registered_before


def test_catalogue_preserves_v2_rejection_report_and_schema_version(catalogue):
    client, _, persist, engine = catalogue
    persist(303, active=False)
    attempt = add_evaluation(
        engine, 303, "test", "completed", schema_version=2,
        y_true=["a", "a", "b"], y_pred=["a", "rejected", "b"],
        rejection_label="rejected",
    )
    response = client.get("/api/models")
    assert response.status_code == 200
    model = next(m for m in response.json()["models"] if m["id"] == "fama_trained_model_303")
    completed = model["evaluations"]["test"]["latest_completed"]
    expected = calculate_classification_report(
        ["a", "a", "b"], ["a", "rejected", "b"], ["a", "b"],
        rejection_label="rejected",
    )
    assert completed["id_evaluation"] == attempt["id_evaluation"]
    assert completed["provenance"]["schema_version"] == 2
    assert completed["report"] == expected
    assert completed["report"]["prediction_columns"] == ["a", "b", "rejected"]
    assert completed["report"]["rejection"] == {"label": "rejected", "count": 1, "rate": 1 / 3}


def test_catalogue_does_not_hide_invalid_completed_records_as_legacy(catalogue):
    from app.models.training import ModelEvaluation

    client, _, persist, engine = catalogue
    persist(302, active=False)
    attempt = add_evaluation(engine, 302, "val", "completed")
    with Session(engine) as db:
        row = db.get(ModelEvaluation, attempt["id_evaluation"])
        row.report = {"metrics": {"accuracy": 0.99}}
        db.commit()

    response = client.get("/api/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluation_catalogue_status"] == "unavailable"
    assert payload["evaluation_catalogue_error"] == "evaluation_records_invalid"
    assert payload["models"][1]["evaluations"] is None
    assert "0.99" not in response.text


def test_catalogue_reports_unavailable_when_evaluation_table_is_missing(catalogue):
    from app.models.training import ModelEvaluation

    client, _, persist, engine = catalogue
    persist(301, active=False)
    ModelEvaluation.__table__.drop(engine)
    response = client.get("/api/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluation_catalogue_status"] == "unavailable"
    assert payload["evaluation_catalogue_error"] == "evaluation_store_unavailable"
    assert payload["models"][0]["id"] == "selected"
    assert payload["models"][1]["evaluations"] is None
    assert str(engine.url) not in response.text


def test_default_catalogue_does_not_enroll_static_or_unpublished_disk_models(catalogue, monkeypatch):
    from app import database
    from app.services import registry as module
    from app.services.predictors import cnn_predictor, ensemble_predictor, engine_ensemble_predictor

    client, _, persist, engine = catalogue
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    # Isolate legacy ML/file discovery: if invoked, it exposes an unpublished model.
    for adapter, name in ((cnn_predictor, "AudioCNNPredictor"),
                          (ensemble_predictor, "ChileanBirdsEnsemblePredictor"),
                          (engine_ensemble_predictor, "EngineEnsemblePredictor")):
        monkeypatch.setattr(adapter, name, lambda **kwargs: FakeAudioPredictor("static", "Static"))
    def disk_discovery(registry):
        registry.register(FakeAudioPredictor("unpublished-disk", "Unpublished"))
        return 1
    monkeypatch.setattr(module, "discover_and_register_bundles", disk_discovery)
    monkeypatch.setattr(module, "discover_and_register_checkpoints", disk_discovery)
    registry = module.build_default_registry()
    main.app.dependency_overrides[get_model_registry] = lambda: registry
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == {
        "models": [], "total": 0, "default_model_id": "", "publication_errors": [],
        "evaluation_catalogue_status": "available", "evaluation_catalogue_error": None,
    }
    # A new valid DB publication remains allowed; there is no permanent ID allowlist.
    persist(73)
    payload = client.get("/api/models").json()
    assert [model["id"] for model in payload["models"]] == ["fama_trained_model_73"]
    assert payload["models"][0]["classes"] == ["Motor sano", "Falla"]
    assert payload["default_model_id"] == ""
    assert registry.get("73") is registry.get("trained_73.pt")


@pytest.mark.parametrize("initial_sync", ["publication", "registration"])
@pytest.mark.parametrize("removed_default", [False, True])
def test_catalogue_reconciles_removed_db_models_without_removing_explicit_entries(
    catalogue, initial_sync, removed_default,
):
    from app.services.registry import ModelNotFoundError

    client, registry, persist, engine = catalogue
    checkpoint = persist(11, active=False)
    persist(74, active=False)
    if initial_sync == "registration":
        with sessionmaker(bind=engine)() as db:
            registry.register_from_db(db, checkpoint.parent)
    original = client.get("/api/models").json()
    assert original["total"] == 3
    survivor = registry.get("74")
    if removed_default:
        registry.set_default_model("fama_trained_model_11")
    # Only temporary SQLite fixture rows are mutated, never deployment persistence.
    with sessionmaker(bind=engine)() as db:
        db.delete(db.get(Modelo, 11))
        db.commit()
    def unavailable(*args):
        raise RuntimeError("Synthetic database outage")
    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        assert client.get("/api/models").status_code == 503
        assert registry.has_model("11")
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)
    payload = client.get("/api/models").json()
    assert [model["id"] for model in payload["models"]] == ["selected", "fama_trained_model_74"]
    assert payload["default_model_id"] == ("" if removed_default else "selected")
    assert registry.get("74") is survivor
    for alias in ("fama_trained_model_11", "11", "trained_11.pt", "trained_11"):
        with pytest.raises(ModelNotFoundError):
            registry.get(alias)
    assert checkpoint.is_file()  # Storage alone must not resurrect the removed row.
    assert client.get("/api/models").json() == payload
    persist(75)
    assert client.get("/api/models").json()["total"] == 3
    assert registry.get("75").metadata.classes == ["Motor sano", "Falla"]


def test_catalogue_discovers_persisted_models_without_changing_selection(catalogue):
    client, registry, persist, _ = catalogue
    assert client.get("/api/models").json()["total"] == 1
    persist()
    response = client.get("/api/models")
    assert response.status_code == 200
    payload = response.json()
    assert [m["id"] for m in payload["models"]] == ["selected", "fama_trained_model_11"]
    trained = payload["models"][1]
    assert trained["classes"] == ["Motor sano", "Falla"]
    assert trained["is_default"] is False
    assert trained["dataset_name"] is None
    assert payload["default_model_id"] == "selected"
    assert payload["publication_errors"] == []
    assert payload["models"][0]["is_default"] is True
    predictor = registry.get("11")
    assert registry.get("trained_11.pt") is predictor
    assert registry.get("trained_11") is predictor
    assert client.get("/api/models").json() == payload
    assert registry.get("11") is predictor
    assert registry.get("selected").predict(None).clase == "Especie A"
    history = client.get("/api/training/history").json()["history"]
    assert next(entry for entry in history if entry["id"] == 11)["active"] is True


def test_publication_preserves_unset_default_and_only_available_filter(catalogue):
    client, registry, persist, _ = catalogue
    registry.unregister("selected")
    persist()
    payload = client.get("/api/models?only_available=true").json()
    assert payload["default_model_id"] == ""
    assert payload["total"] == 1
    assert payload["models"][0]["is_default"] is False
    assert registry.get_default_model_id() is None
    unavailable = FakeAudioPredictor("unavailable", "No weights")
    unavailable.has_weights_override = False
    registry.register(unavailable, is_default=True)
    assert client.get("/api/models").json()["total"] == 2
    payload = client.get("/api/models?only_available=true").json()
    assert [m["id"] for m in payload["models"]] == ["fama_trained_model_11"]
    assert payload["default_model_id"] == "unavailable"


@pytest.mark.parametrize("failure,code", [
    ("missing", "checkpoint_missing"),
    ("small", "checkpoint_too_small"),
    ("corrupt", "checkpoint_invalid"),
    ("unreadable", "checkpoint_unreadable"),
])
def test_publication_errors_are_visible_and_sanitized(catalogue, monkeypatch, failure, code):
    from pathlib import Path
    client, registry, persist, _ = catalogue
    checkpoint = persist(contents="bad binary" * 2000 if failure == "corrupt" else None)
    if failure == "small":
        checkpoint.write_bytes(b"tiny")
    if failure == "missing":
        is_file = Path.is_file
        monkeypatch.setattr(Path, "is_file", lambda path: False if path == checkpoint else is_file(path))
    if failure == "unreadable":
        open_file = Path.open
        def guarded_open(path, *args, **kwargs):
            if path == checkpoint:
                raise PermissionError(f"Private path: {checkpoint}")
            return open_file(path, *args, **kwargs)
        monkeypatch.setattr(Path, "open", guarded_open)
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json()["publication_errors"] == [
        {"model_id": "fama_trained_model_11", "code": code},
    ]
    assert [m["id"] for m in response.json()["models"]] == ["selected"]
    assert response.json()["default_model_id"] == "selected"
    assert str(checkpoint.parent) not in response.text
    assert "Traceback" not in response.text
    assert registry.get_default_model_id() == "selected"
    assert [m.id for m in registry.list_models()] == ["selected"]


def test_database_failure_preserves_existing_catalogue_and_recovers(catalogue):
    client, registry, persist, engine = catalogue
    persist()
    original = client.get("/api/models").json()
    predictor = registry.get("11")

    def unavailable(*args):
        raise RuntimeError("Private database credentials and stack")

    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        response = client.get("/api/models")
        assert response.status_code == 503
        assert response.json()["detail"]["errors"] == [{"code": "database_unavailable"}]
        assert "credentials" not in response.text
        assert registry.get("11") is predictor
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)
    assert client.get("/api/models").json() == original


def test_one_failed_checkpoint_does_not_prevent_other_publications(catalogue):
    client, registry, persist, _ = catalogue
    damaged = persist(12, contents="tiny")
    persist(11)
    response = client.get("/api/models?only_available=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["publication_errors"] == [
        {"model_id": "fama_trained_model_12", "code": "checkpoint_too_small"},
    ]
    assert [m["id"] for m in payload["models"]] == ["selected", "fama_trained_model_11"]
    assert payload["models"][1]["classes"] == ["Motor sano", "Falla"]
    assert payload["default_model_id"] == "selected"
    # Repairing storage makes the complete catalogue observable on the next GET.
    published = registry.get("11")
    damaged.write_text(json.dumps({"classes": ["Repaired"], "padding": "x" * 11000}))
    payload = client.get("/api/models").json()
    assert payload["total"] == 3
    assert payload["default_model_id"] == "selected"
    assert payload["publication_errors"] == []
    assert registry.get("11") is published


@pytest.mark.parametrize("malformed", [False, True])
def test_real_lazy_adapter_reads_only_synthetic_checkpoint(catalogue, monkeypatch, malformed):
    import torch
    from app.services.predictors import trained_predictor
    client, registry, persist, _ = catalogue
    checkpoint = persist()
    torch.save({"architecture": "AudioCNN", "classes": 42 if malformed else ["Synthetic A", "Synthetic B"],
                "best_val_acc": 85.0, "padding": "x" * 12000,
                "state_dict": {"synthetic": torch.zeros(1)}}, checkpoint)
    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", TrainedModelPredictor)
    response = client.get("/api/models")
    if malformed:
        assert response.status_code == 200
        assert response.json()["publication_errors"] == [
            {"model_id": "fama_trained_model_11", "code": "checkpoint_invalid"},
        ]
        assert [m["id"] for m in response.json()["models"]] == ["selected"]
        assert str(checkpoint) not in response.text
    else:
        assert response.status_code == 200
        trained = response.json()["models"][1]
        assert trained["classes"] == ["Synthetic A", "Synthetic B"]
        assert trained["metrics"] == {"accuracy": 0.85}
        assert trained["is_default"] is False
        assert registry.get("11").model is None


@pytest.mark.parametrize("route_kind", ["file_uri", "absolute"])
def test_external_db_path_cannot_publish_checkpoint_outside_root(catalogue, tmp_path, route_kind):
    client, _, persist, _ = catalogue
    external = tmp_path / "external.pt"
    external.write_text(json.dumps({"classes": ["Outside"], "padding": "x" * 11000}))
    persist(route=external.as_uri() if route_kind == "file_uri" else str(external))
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json()["publication_errors"] == [
        {"model_id": "fama_trained_model_11", "code": "checkpoint_missing"},
    ]
    assert [m["id"] for m in response.json()["models"]] == ["selected"]
    assert str(external) not in response.text


def test_symlink_checkpoint_cannot_escape_configured_root(catalogue, tmp_path):
    client, _, persist, _ = catalogue
    external = tmp_path / "external.pt"
    external.write_text(json.dumps({"classes": ["Outside"], "padding": "x" * 11000}))
    checkpoint = persist(route="models/link.pt")
    (checkpoint.parent / "link.pt").symlink_to(external)
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json()["publication_errors"] == [
        {"model_id": "fama_trained_model_11", "code": "checkpoint_outside_root"},
    ]
    assert [m["id"] for m in response.json()["models"]] == ["selected"]
    assert str(external) not in response.text


@pytest.mark.parametrize("route", [
    "models/trained_11.pt",
    "gs://fixture-bucket/models/trained_11.pt",
    "file:///ignored/trained_%31%31.pt",
    "/ignored/trained_11.pt",
])
def test_db_route_basename_uses_physical_configured_root(catalogue, tmp_path, monkeypatch, route):
    client, _, persist, _ = catalogue
    checkpoint = persist(route=route)
    configured = tmp_path / "configured-root"
    configured.symlink_to(checkpoint.parent, target_is_directory=True)
    monkeypatch.setattr(main.training_service, "checkpoints_dir", configured)
    response = client.get("/api/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["publication_errors"] == []
    assert payload["models"][1]["id"] == "fama_trained_model_11"
    assert payload["models"][1]["classes"] == ["Motor sano", "Falla"]
    assert payload["default_model_id"] == "selected"


def test_concurrent_catalogue_requests_keep_one_predictor(catalogue):
    from concurrent.futures import ThreadPoolExecutor
    client, registry, persist, _ = catalogue
    persist()
    def request():
        response = client.get("/api/models")
        assert response.status_code == 200
        return response.json(), registry.get("11")
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: request(), range(8)))
    payload, predictor = results[0]
    assert payload["total"] == 2
    assert all(result == payload and instance is predictor for result, instance in results)


def test_catalogue_exposes_sha256_of_registered_checkpoint_bytes(catalogue, monkeypatch):
    import hashlib
    import torch
    from app.services.predictors import trained_predictor

    client, registry, persist, engine = catalogue
    checkpoint = persist()
    torch.save({
        "architecture": "AudioCNN", "classes": ["Synthetic A", "Synthetic B"],
        "best_val_acc": 99.0, "padding": "x" * 12000,
    }, checkpoint)
    with Session(engine) as db:
        db.get(Modelo, 11).hash_binario = "f" * 64
        db.commit()
    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", TrainedModelPredictor)

    response = client.get("/api/models")

    assert response.status_code == 200
    model = next(item for item in response.json()["models"] if item["id"] == "fama_trained_model_11")
    first_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert model.get("checkpoint_sha256") == first_digest
    assert model["checkpoint_sha256"] != "f" * 64
    assert registry.get("11").model is None

    checkpoint.write_bytes(checkpoint.read_bytes() + b"different synthetic checkpoint bytes")
    changed_response = client.get("/api/models")
    changed_model = next(item for item in changed_response.json()["models"]
                         if item["id"] == "fama_trained_model_11")
    changed_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert changed_model.get("checkpoint_sha256") == changed_digest
    assert changed_digest != first_digest
    assert registry.get("11").model is None


@pytest.mark.parametrize("unavailable", ["missing", "unreadable"])
def test_catalogue_returns_null_checkpoint_hash_when_file_is_unavailable(
    catalogue, monkeypatch, unavailable,
):
    from pathlib import Path
    import torch
    from app.services.predictors import trained_predictor

    client, registry, persist, _ = catalogue
    checkpoint = persist()
    torch.save({
        "architecture": "AudioCNN", "classes": ["Synthetic A", "Synthetic B"],
        "padding": "x" * 12000,
    }, checkpoint)
    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", TrainedModelPredictor)
    assert client.get("/api/models").status_code == 200

    if unavailable == "missing":
        checkpoint.unlink()
    else:
        original_open = Path.open

        def deny_checkpoint(path, *args, **kwargs):
            if path == checkpoint:
                raise PermissionError(f"Private checkpoint path: {checkpoint}")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_checkpoint)

    response = client.get("/api/models")

    assert response.status_code == 200
    model = next(item for item in response.json()["models"] if item["id"] == "fama_trained_model_11")
    assert model["checkpoint_sha256"] is None
    assert str(checkpoint) not in response.text
    assert "Private checkpoint path" not in response.text
    assert registry.get("11").model is None
