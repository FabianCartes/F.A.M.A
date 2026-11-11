"""Standard checkpoint prewarming and metadata-only registry contracts."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.orm import Session

from app.models.dataset import ConjuntoDatos
from tests.test_api_model_catalogue import catalogue, main


def standard(catalogue, monkeypatch, *, active=False):
    from app.services.predictors import trained_predictor
    client, registry, persist, engine = catalogue
    checkpoint = persist(active=active, dataset=ConjuntoDatos(
        nombre="engine_diagnostics", ruta_gcp="datasets/engine_diagnostics"))
    adapter = trained_predictor.TrainedModelPredictor
    calls = []
    def counted(**kwargs):
        calls.append(kwargs["model_id"])
        return adapter(**kwargs)
    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", counted)
    return client, registry, engine, checkpoint, calls


def test_standard_prewarm_is_cache_only_and_publication_reuses_metadata(catalogue, monkeypatch):
    client, registry, engine, checkpoint, calls = standard(catalogue, monkeypatch)
    with Session(engine) as db:
        assert registry.prewarm_from_db(db, checkpoint.parent) == 0
    assert calls == ["fama_trained_model_11"]
    assert registry.get_default_model_id() == "selected"
    with Session(engine) as db:
        assert registry.publish_from_db(db, checkpoints_root=checkpoint.parent) == []
    assert calls == ["fama_trained_model_11"]
    response = client.get("/api/models")
    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()["models"]} == {"selected", "fama_trained_model_11"}
    assert response.json()["default_model_id"] == "selected"


def test_prewarm_never_bypasses_changed_checkpoint_hash(catalogue, monkeypatch):
    _, registry, engine, checkpoint, calls = standard(catalogue, monkeypatch)
    with Session(engine) as db:
        assert registry.prewarm_from_db(db, checkpoint.parent) == 0
    checkpoint.write_text("synthetic replacement" * 1000)
    with Session(engine) as db:
        errors = registry.publish_from_db(db, checkpoints_root=checkpoint.parent)
    assert errors == [{"model_id": "fama_trained_model_11", "code": "checkpoint_hash_mismatch"}]
    assert calls == ["fama_trained_model_11"]
    assert [item.id for item in registry.list_models()] == ["selected"]


@pytest.mark.parametrize("policy", ["normal", "isolated"])
def test_lifespan_prewarm_precedes_readiness(catalogue, monkeypatch, policy):
    from app import database
    from app.services import auth
    _, registry, _, engine = catalogue
    events = []
    monkeypatch.setattr(main, "_APP_STARTUP_POLICY", policy)
    monkeypatch.setattr(main.ensemble_service, "load_models", lambda: events.append("ensemble"))
    monkeypatch.setattr(auth, "seed_initial_admin", lambda db: events.append("seed"))
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(main, "initialize_model_registry", lambda **kwargs: registry, raising=False)
    monkeypatch.setattr(main, "get_model_registry", lambda: registry)
    monkeypatch.setattr(registry, "prewarm_from_db", lambda db, checkpoints_root: events.append("warm") or 0)
    class Worker:
        def __init__(self, *args): pass
        @asynccontextmanager
        async def running(self):
            events.append("worker")
            yield
            events.append("stop")
    monkeypatch.setattr(main, "FeedbackSyncWorker", Worker)
    async def run():
        async with main.lifespan(main.app):
            events.append("ready")
    asyncio.run(run())
    assert events == (["warm", "ready"] if policy == "isolated" else
                      ["ensemble", "warm", "worker", "ready", "stop"])


@pytest.mark.parametrize("metadata_only", [True, False])
def test_standard_active_singleton_respects_metadata_only(catalogue, monkeypatch, metadata_only):
    from app import database
    from app.services import registry as module
    from app.services.predictors import trained_predictor
    adapter = trained_predictor.TrainedModelPredictor
    _, _, engine, checkpoint, _ = standard(catalogue, monkeypatch, active=True)
    loads = []
    class ControlledAdapter(adapter):
        def load_weights(self):
            loads.append(self.model_id)
    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", ControlledAdapter)
    monkeypatch.setattr(module, "get_checkpoints_dir", lambda: checkpoint.parent)
    monkeypatch.setattr(module, "_global_model_registry", None)
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr("app.configuration.declared_ensembles", lambda values: ([], None))
    registry = module.initialize_model_registry(metadata_only=metadata_only)
    assert module.get_model_registry() is registry
    assert registry.get_default_model_id() == "fama_trained_model_11"
    assert [item.id for item in registry.list_models()] == ["fama_trained_model_11"]
    assert loads == ([] if metadata_only else ["fama_trained_model_11"])


@pytest.mark.parametrize("policy", ["normal", "isolated"])
@pytest.mark.parametrize("broken", ["database", "model"])
def test_prewarm_failure_is_sanitized_and_readiness_continues(catalogue, monkeypatch, capsys, policy, broken):
    from app import database
    _, registry, _, engine = catalogue
    monkeypatch.setattr(main, "_APP_STARTUP_POLICY", policy)
    monkeypatch.setattr(main.ensemble_service, "load_models", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(main, "initialize_model_registry", lambda **kwargs: registry, raising=False)
    monkeypatch.setattr(main, "get_model_registry", lambda: registry)
    def warm(*args, **kwargs):
        if broken == "database":
            raise RuntimeError("/private/checkpoint secret-token owner-name")
        return 2
    monkeypatch.setattr(registry, "prewarm_from_db", warm)
    class Worker:
        def __init__(self, *args): pass
        @asynccontextmanager
        async def running(self):
            yield
    monkeypatch.setattr(main, "FeedbackSyncWorker", Worker)
    async def run():
        async with main.lifespan(main.app):
            assert registry.get().model_id == "selected"
    asyncio.run(run())
    output = capsys.readouterr().out
    assert "[Startup Warning] Metadata prewarm" in output
    assert all(secret not in output for secret in ("/private", "secret-token", "owner-name"))


def test_concurrent_initializers_share_isolated_first_singleton(monkeypatch):
    from threading import Event, Thread
    from app.services import registry as module
    entered, release, second_started = Event(), Event(), Event()
    created, results, errors = [], [], []
    monkeypatch.setattr(module, "_global_model_registry", None)
    def factory(*, metadata_only=False):
        candidate = module.ModelRegistry()
        created.append((candidate, metadata_only))
        entered.set()
        assert release.wait(5)
        return candidate
    monkeypatch.setattr(module, "build_default_registry", factory)
    def invoke(isolated):
        try:
            if not isolated:
                second_started.set()
            results.append(module.initialize_model_registry(metadata_only=True)
                           if isolated else module.get_model_registry())
        except BaseException as error:
            errors.append(error)
    first, second = Thread(target=invoke, args=(True,)), Thread(target=invoke, args=(False,))
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert second_started.wait(5)
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not errors and len(created) == 1 and created[0][1] is True
    assert len(results) == 2 and results[0] is results[1]
    assert module.get_model_registry() is results[0]
