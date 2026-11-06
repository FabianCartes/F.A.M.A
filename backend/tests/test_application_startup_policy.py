"""Startup policy at the real module-import and ASGI lifespan boundaries.

Run only through the existing isolated training runner: it blocks network/live
DB access, disables dotenv, and redirects collection-time checkpoint writes.
No subprocess is used: a scoped fresh app.main import avoids the module cache
without escaping the runner's in-process guards.
"""
from contextlib import asynccontextmanager, contextmanager
import importlib
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def startup_boundary(monkeypatch):
    from app import database
    from app.services import auth, feedback_sync_worker
    import app

    # A real, private SQLAlchemy destination, never the ambient runtime engine.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    sessions = sessionmaker(bind=engine)
    effects = []
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    # Avoid __getattr__: saving an absent lazy attribute would initialize the
    # ambient engine before the private replacement is installed.
    monkeypatch.setitem(database.__dict__, "engine", engine)
    monkeypatch.setitem(database.__dict__, "SessionLocal", sessions)

    def schema_bootstrap(*args, **kwargs):
        effects.append("schema")

    # Observe real DDL admission, without replacing create_all or storage logic.
    event.listen(database.Base.metadata, "before_create", schema_bootstrap)

    def seed(db):
        assert db.get_bind() is engine
        effects.append("seed")

    monkeypatch.setattr(auth, "seed_initial_admin", seed)

    class StartupWorker:
        """Startup construction boundary; never schedules a cloud-capable pass."""
        def __init__(self, session_factory, raw_data_dir):
            assert session_factory is sessions
            effects.append("worker")

        @asynccontextmanager
        async def running(self):
            effects.append("worker_enter")
            try:
                yield self
            finally:
                effects.append("worker_exit")

    monkeypatch.setattr(feedback_sync_worker, "FeedbackSyncWorker", StartupWorker)

    @contextmanager
    def fresh_application():
        # Restore both Python's module cache and its parent-package binding.
        absent = object()
        previous_module = sys.modules.pop("app.main", absent)
        previous_attribute = app.__dict__.pop("main", absent)
        try:
            module = importlib.import_module("app.main")
            monkeypatch.setattr(module.ensemble_service, "load_models",
                                lambda: effects.append("preload"))
            yield module.app
        finally:
            sys.modules.pop("app.main", None)
            app.__dict__.pop("main", None)
            if previous_module is not absent:
                sys.modules["app.main"] = previous_module
            if previous_attribute is not absent:
                app.main = previous_attribute

    try:
        yield fresh_application, effects
    finally:
        event.remove(database.Base.metadata, "before_create", schema_bootstrap)
        engine.dispose()


def test_isolated_startup_serves_public_health_without_startup_effects(startup_boundary, monkeypatch):
    fresh_application, effects = startup_boundary
    monkeypatch.setenv("FAMA_APP_STARTUP_POLICY", "isolated")
    with fresh_application() as application:
        assert effects == [], "Isolated module import must not bootstrap schema"
        with TestClient(application) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            assert effects == [], "Isolated lifespan must not preload, seed or construct a worker"
        assert effects == [], "Isolated shutdown must not own a feedback worker"


@pytest.mark.parametrize("policy", [None, "normal"], ids=["default", "explicit-normal"])
def test_normal_startup_preserves_bootstrap_and_lifespan(startup_boundary, monkeypatch, policy):
    fresh_application, effects = startup_boundary
    if policy is None:
        monkeypatch.delenv("FAMA_APP_STARTUP_POLICY", raising=False)
    else:
        monkeypatch.setenv("FAMA_APP_STARTUP_POLICY", policy)
    with fresh_application() as application:
        assert effects == ["schema"]
        with TestClient(application) as client:
            assert client.get("/health").json() == {"status": "ok"}
            assert effects == ["schema", "preload", "seed", "worker", "worker_enter"]
        assert effects == ["schema", "preload", "seed", "worker", "worker_enter", "worker_exit"]


@pytest.mark.parametrize("policy", ["", "ISOLATED", " isolated", "isolated ", "disabled"])
def test_invalid_policy_rejects_import_before_startup_effects(startup_boundary, monkeypatch, policy):
    fresh_application, effects = startup_boundary
    monkeypatch.setenv("FAMA_APP_STARTUP_POLICY", policy)
    # Accept any ordinary configuration exception, but require it to identify
    # the policy so an unrelated dependency/import error cannot satisfy this.
    # Rejection must precede yielding an app or entering its lifespan.
    with pytest.raises(Exception, match="FAMA_APP_STARTUP_POLICY"):
        with fresh_application():
            pytest.fail("Invalid startup policy admitted an application")
    assert effects == [], "Invalid configuration must fail before legacy DDL admission"
