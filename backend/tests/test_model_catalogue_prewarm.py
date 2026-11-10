"""Synthetic metadata prewarming at the registry and application lifespan seams."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.orm import Session

from tests.test_api_model_catalogue import catalogue, main
from app.models.imported_training_source import ImportedModelSource
from app.services.registry import ModelNotFoundError


def imported(catalogue, monkeypatch):
    from app.services.predictors import trained_predictor
    client, registry, persist, engine = catalogue
    checkpoint = persist(active=False)
    with Session(engine) as db:
        db.add(ImportedModelSource(model_id=11, owner_id=1, dataset_id="d" * 32,
            snapshot_id="s" * 32, identity={"owner_id": 1, "dataset_id": "d" * 32,
                                         "snapshot_id": "s" * 32}))
        db.commit()
    adapter = trained_predictor.TrainedModelPredictor
    calls = []
    def counted(**kwargs):
        calls.append(kwargs["model_id"])
        return adapter(**kwargs)
    monkeypatch.setattr(trained_predictor, "TrainedModelPredictor", counted)
    return client, registry, engine, checkpoint, calls


def test_prewarm_is_cache_only_and_owner_publication_reuses_metadata(catalogue, monkeypatch):
    client, registry, engine, checkpoint, calls = imported(catalogue, monkeypatch)
    before = client.get('/api/models').json()
    with Session(engine) as db:
        assert registry.prewarm_from_db(db, checkpoint.parent) == 0
    assert calls == ['fama_trained_model_11']
    assert client.get('/api/models').json() == before
    assert registry.get().model_id == 'selected'
    for owner in (None, 1, 2):
        with pytest.raises(ModelNotFoundError):
            registry.get('fama_trained_model_11', owner_id=owner)
    # Non-standard synthetic row uses the existing publication policy.
    with Session(engine) as db:
        errors = registry.publish_from_db(db, checkpoints_root=checkpoint.parent, owner_id=1)
    assert errors == []
    assert calls == ['fama_trained_model_11']
    assert [m.id for m in registry.list_models(owner_id=1, private_only=True)] == ['fama_trained_model_11']
    assert registry.list_models(owner_id=2, private_only=True) == []
    assert registry.get().model_id == 'selected'


@pytest.mark.parametrize("damage", ["sha", "missing", "forged", "other", "evaluation"])
def test_warm_metadata_does_not_bypass_later_admission(catalogue, monkeypatch, damage):
    from app.models.training import Modelo
    _, registry, engine, checkpoint, calls = imported(catalogue, monkeypatch)
    with Session(engine) as db:
        assert registry.prewarm_from_db(db, checkpoint.parent) == 0
    if damage == "sha":
        checkpoint.write_text("changed" * 2000)
    elif damage == "missing":
        # Move only this disposable synthetic fixture; never real checkpoints.
        checkpoint.rename(checkpoint.with_suffix('.unavailable'))
    with Session(engine) as db:
        if damage == "forged":
            source = db.get(ImportedModelSource, 11)
            source.identity = {**source.identity, "owner_id": 2}
            db.commit()
        if damage == "evaluation":
            db.get(Modelo, 11).estado = 'standard_training_completed'
            db.commit()
        registry.publish_from_db(db, checkpoints_root=checkpoint.parent,
                                 owner_id=2 if damage == "other" else 1)
    assert calls == ['fama_trained_model_11']
    assert registry.list_models(owner_id=1, private_only=True) == []
    assert registry.list_models(owner_id=2, private_only=True) == []
    assert registry.get().model_id == 'selected'


@pytest.mark.parametrize("policy", ["normal", "isolated"])
def test_lifespan_prewarms_once_before_readiness_without_changing_worker_order(catalogue, monkeypatch, policy):
    from app import database
    from app.services import auth
    _, registry, _, engine = catalogue
    events = []
    monkeypatch.setattr(main, '_APP_STARTUP_POLICY', policy)
    monkeypatch.setattr(main.ensemble_service, 'load_models', lambda: events.append('ensemble'))
    monkeypatch.setattr(auth, 'seed_initial_admin', lambda db: events.append('seed'))
    monkeypatch.setattr(database, 'SessionLocal', lambda: Session(engine))
    monkeypatch.setattr(main, 'get_model_registry', lambda: registry)
    monkeypatch.setattr(main, 'initialize_model_registry', lambda **kwargs: registry, raising=False)
    monkeypatch.setattr(registry, 'prewarm_from_db', lambda db, checkpoints_root: events.append('warm') or 0)
    class Worker:
        def __init__(self, *args):
            pass
        @asynccontextmanager
        async def running(self):
            events.append('worker')
            yield
            events.append('stop')
    monkeypatch.setattr(main, 'FeedbackSyncWorker', Worker)
    async def run():
        async with main.lifespan(main.app):
            events.append('ready')
    asyncio.run(run())
    assert events == (['warm', 'ready'] if policy == 'isolated' else
                      ['ensemble', 'seed', 'warm', 'worker', 'ready', 'stop'])


@pytest.mark.parametrize("policy", ["normal", "isolated"])
@pytest.mark.parametrize("broken", ["database", "model"])
def test_prewarm_failure_is_sanitized_and_does_not_prevent_readiness(catalogue, monkeypatch, capsys, broken, policy):
    from app import database
    from app.services import auth
    _, registry, _, engine = catalogue
    monkeypatch.setattr(main, '_APP_STARTUP_POLICY', policy)
    monkeypatch.setattr(main.ensemble_service, 'load_models', lambda: None)
    monkeypatch.setattr(auth, 'seed_initial_admin', lambda db: None)
    monkeypatch.setattr(database, 'SessionLocal', lambda: Session(engine))
    monkeypatch.setattr(main, 'get_model_registry', lambda: registry)
    monkeypatch.setattr(main, 'initialize_model_registry', lambda **kwargs: registry, raising=False)
    def warm(*args, **kwargs):
        if broken == 'database':
            raise RuntimeError('/private/checkpoint secret-token owner-name')
        return 2
    monkeypatch.setattr(registry, 'prewarm_from_db', warm)
    class Worker:
        def __init__(self, *args):
            pass
        @asynccontextmanager
        async def running(self):
            yield
    monkeypatch.setattr(main, 'FeedbackSyncWorker', Worker)
    async def run():
        async with main.lifespan(main.app):
            assert registry.get().model_id == 'selected'
    asyncio.run(run())
    output = capsys.readouterr().out
    assert '[Startup Warning] Metadata prewarm' in output
    assert all(secret not in output for secret in ('/private', 'secret-token', 'owner-name'))


def test_invalid_model_does_not_prevent_other_metadata_warming(catalogue, monkeypatch):
    from app.models.training import Modelo
    _, registry, engine, checkpoint, calls = imported(catalogue, monkeypatch)
    # A forged persisted association is rejected independently of the valid row.
    catalogue[2](model_id=12, active=False)
    with Session(engine) as db:
        db.add(ImportedModelSource(model_id=12, owner_id=1, dataset_id='d' * 32,
            snapshot_id='s' * 32, identity={'owner_id': 2}))
        db.commit()
        assert registry.prewarm_from_db(db, checkpoint.parent) == 1
    assert calls == ['fama_trained_model_11']
    assert registry.list_models(owner_id=1, private_only=True) == []
    assert registry.get().model_id == 'selected'


@pytest.mark.parametrize("changed_checkpoint", [True, False])
def test_removed_imported_association_cannot_promote_warm_metadata_to_legacy(
        catalogue, monkeypatch, changed_checkpoint):
    client, registry, engine, checkpoint, calls = imported(catalogue, monkeypatch)
    before = client.get('/api/models').json()
    with Session(engine) as db:
        assert registry.prewarm_from_db(db, checkpoint.parent) == 0
        # Controlled synthetic DB mutation reproduces lost persisted provenance.
        db.delete(db.get(ImportedModelSource, 11))
        db.commit()
    if changed_checkpoint:
        checkpoint.write_text('changed synthetic checkpoint' * 500)
    with Session(engine) as db:
        errors = registry.publish_from_db(db, checkpoints_root=checkpoint.parent)
    # Reject provenance loss explicitly, without exposing a private model ID.
    assert errors == [{'model_id': '', 'code': 'checkpoint_invalid'}]
    assert calls == ['fama_trained_model_11']
    for owner in (None, 1, 2):
        with pytest.raises(ModelNotFoundError):
            registry.get('fama_trained_model_11', owner_id=owner)
        assert registry.list_models(owner_id=owner, private_only=True) == []
    public = client.get('/api/models').json()
    assert public['models'] == before['models']
    assert public['default_model_id'] == before['default_model_id'] == 'selected'
    assert public['publication_errors'] == [{'model_id': '', 'code': 'checkpoint_invalid'}]


@pytest.mark.parametrize("metadata_only", [True, False])
def test_singleton_initialization_preserves_public_default_without_isolated_weight_load(
        catalogue, monkeypatch, metadata_only):
    from app import database
    from app.services import registry as registry_module
    from app.services.predictors import trained_predictor
    _, _, persist, engine = catalogue
    checkpoint = persist(active=True)
    monkeypatch.setattr(registry_module, '__file__', str(checkpoint.parent.parent / 'app/services/registry.py'))
    closed = []
    class ReadOnlySession(Session):
        def commit(self):
            pytest.fail('Startup registry must not commit')
        def close(self):
            closed.append(True)
            super().close()
    monkeypatch.setattr(database, 'SessionLocal', lambda: ReadOnlySession(engine))
    loads = []
    adapter = trained_predictor.TrainedModelPredictor
    class ControlledAdapter(adapter):
        def load_weights(self):
            loads.append(self.model_id)
    monkeypatch.setattr(trained_predictor, 'TrainedModelPredictor', ControlledAdapter)
    monkeypatch.setattr(registry_module, '_global_model_registry', None)
    if metadata_only:
        monkeypatch.setattr(main, '_APP_STARTUP_POLICY', 'isolated')
        def forbidden(*args, **kwargs):
            pytest.fail('Isolated startup enabled an automatic effect')
        from app.services import auth
        monkeypatch.setattr(main.ensemble_service, 'load_models', forbidden)
        monkeypatch.setattr(auth, 'seed_initial_admin', forbidden)
        monkeypatch.setattr(main, 'FeedbackSyncWorker', forbidden)
        async def run():
            async with main.lifespan(main.app):
                return registry_module.get_model_registry()
        registry = asyncio.run(run())
    else:
        registry = registry_module.get_model_registry()
    assert registry_module.get_model_registry() is registry
    assert registry.get_default_model_id() == 'fama_trained_model_11'
    assert [m.id for m in registry.list_models()] == ['fama_trained_model_11']
    assert loads == ([] if metadata_only else ['fama_trained_model_11'])
    assert closed == ([True, True] if metadata_only else [True])


def test_concurrent_initializers_share_isolated_first_singleton(monkeypatch):
    from threading import Event, Thread
    from app.services import registry as module
    entered, second_entered, second_started, release = (Event() for _ in range(4))
    created, loads, results, errors = [], [], [], []
    monkeypatch.setattr(module, '_global_model_registry', None)
    def factory(*, metadata_only=False):
        candidate = module.ModelRegistry()
        created.append(candidate)
        if not metadata_only:
            loads.append('eager')
        if len(created) == 1:
            entered.set()
            assert release.wait(5), 'Controller did not release first factory'
        else:
            second_entered.set()
        return candidate
    monkeypatch.setattr(module, 'build_default_registry', factory)
    def invoke(isolated):
        try:
            if not isolated:
                second_started.set()
            results.append(module.initialize_model_registry(metadata_only=True)
                           if isolated else module.get_model_registry())
        except BaseException as error:
            errors.append(error)
    first = Thread(target=invoke, args=(True,))
    second = Thread(target=invoke, args=(False,))
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert second_started.wait(5)
        # A bounded handshake allows the broken second factory to report entry.
        # With serialization it stays blocked until the controller releases first.
        second_entered.wait(1)
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert len(created) == 1
    assert len(results) == 2 and results[0] is results[1]
    assert module.get_model_registry() is results[0]
    assert loads == []


def test_isolated_lifespan_http_owner_catalogue_reuses_primed_singleton(catalogue, monkeypatch):
    from fastapi.testclient import TestClient
    from app import database
    from app.services import auth, registry as module
    _, _, engine, checkpoint, calls = imported(catalogue, monkeypatch)
    monkeypatch.setattr(module, 'get_checkpoints_dir', lambda: checkpoint.parent)
    monkeypatch.setattr(module, '_global_model_registry', None)
    monkeypatch.setattr(database, 'SessionLocal', lambda: Session(engine))
    monkeypatch.setattr(main, '_APP_STARTUP_POLICY', 'isolated')
    from sqlalchemy.orm import sessionmaker
    from app.models.user import Usuario
    from tests.http_security import configure_cookie_sessions, cookie_headers
    configure_cookie_sessions(monkeypatch)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        for index in (1, 2):
            db.add(Usuario(id=index, email=f'owner{index}@example.test',
                           nombre_completo=f'Owner {index}', password_hash='replaced-by-login-helper',
                           rol='administrador', activo=True))
        db.commit()
    credentials = lambda uid: cookie_headers(sessions, uid)
    def forbidden(*args, **kwargs):
        pytest.fail('Isolated HTTP lifecycle enabled automatic effects')
    monkeypatch.setattr(main.ensemble_service, 'load_models', forbidden)
    monkeypatch.setattr(auth, 'seed_initial_admin', forbidden)
    monkeypatch.setattr(main, 'FeedbackSyncWorker', forbidden)
    seen = []
    def dependency():
        registry = module.get_model_registry()
        seen.append(registry)
        return registry
    main.app.dependency_overrides[main.get_model_registry] = dependency
    with TestClient(main.app) as client:
        warmed = module.get_model_registry()
        assert calls == ['fama_trained_model_11']  # warm completed before readiness
        public = client.get('/api/models').json()
        assert public['models'] == [] and public['default_model_id'] == ''
        private = client.get('/api/models?private_only=true', headers=credentials(1))
        assert private.status_code == 200, private.text
        assert [m['id'] for m in private.json()['models']] == ['fama_trained_model_11']
        assert private.json()['default_model_id'] == ''
        assert client.get('/api/models?private_only=true', headers=credentials(2)).json()['models'] == []
        checkpoint.write_text('changed synthetic checkpoint' * 500)
        assert client.get('/api/models?private_only=true', headers=credentials(1)).json()['models'] == []
        assert calls == ['fama_trained_model_11']
        assert seen and all(registry is warmed for registry in seen)
