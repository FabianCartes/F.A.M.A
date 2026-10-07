"""Catalogue publication through HTTP, with isolated persistence and ML adapter."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

with patch("app.database.Base.metadata.create_all"):
    from app import main
from app.database import Base, get_db
from app.models.training import Modelo
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
    assert response.json() == {"models": [], "total": 0, "default_model_id": "", "publication_errors": []}
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
