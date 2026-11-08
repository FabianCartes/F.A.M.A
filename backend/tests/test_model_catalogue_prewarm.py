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
    assert events == (['ready'] if policy == 'isolated' else
                      ['ensemble', 'seed', 'warm', 'worker', 'ready', 'stop'])


@pytest.mark.parametrize("broken", ["database", "model"])
def test_prewarm_failure_is_sanitized_and_does_not_prevent_readiness(catalogue, monkeypatch, capsys, broken):
    from app import database
    from app.services import auth
    _, registry, _, engine = catalogue
    monkeypatch.setattr(main, '_APP_STARTUP_POLICY', 'normal')
    monkeypatch.setattr(main.ensemble_service, 'load_models', lambda: None)
    monkeypatch.setattr(auth, 'seed_initial_admin', lambda db: None)
    monkeypatch.setattr(database, 'SessionLocal', lambda: Session(engine))
    monkeypatch.setattr(main, 'get_model_registry', lambda: registry)
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
