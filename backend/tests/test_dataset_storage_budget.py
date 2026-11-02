"""Public policy requests only; no assertions against internal grant rows."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, update
from sqlalchemy.orm import Session

from app.models.dataset_storage import STORAGE_MODELS, StorageGrant, StoragePool, StorageSchema
from app.services.dataset_storage import PhysicalStorage

GIB = 1024**3
UNAVAILABLE = "El presupuesto físico requiere un perfil activo y compatible."


@contextmanager
def denied(code=503):
    with pytest.raises(HTTPException) as error:
        yield
    assert error.value.status_code == code
    assert error.value.detail == (UNAVAILABLE if code == 503 else "Espacio físico insuficiente.")


@pytest.fixture
def budget(tmp_path, monkeypatch):
    root = tmp_path / "imports"
    root.mkdir(mode=0o700)
    objects = root / "objects"
    objects.mkdir(mode=0o700)
    attempts = tmp_path / "attempts"
    attempts.mkdir(mode=0o700)
    roots = dict(imports=root, objects=objects, attempts=attempts,
                 manifests=attempts, scratch=attempts, exports=attempts)
    policy = PhysicalStorage(roots=roots, pools=dict.fromkeys(roots, "ssd"),
                             free_floors={"ssd": GIB})
    engine = create_engine("sqlite://")
    for model in STORAGE_MODELS:
        model.__table__.create(engine)
    service = SimpleNamespace(root=root, attempt_root=attempts,
                              limits=SimpleNamespace(expanded_bytes=10 * GIB,
                                  public=lambda: {"expanded_bytes": 10 * GIB}))
    space = SimpleNamespace(free=27 * GIB)
    monkeypatch.setattr("app.services.dataset_storage.shutil.disk_usage", lambda path: space)
    with Session(engine, autoflush=False) as db:
        db.add(StorageSchema(id=1, version=1, state="active"))
        db.add(StoragePool(id="ssd", configuration_sha256=policy.configuration_sha256,
                           free_floor_bytes=GIB))
        db.commit()
        yield SimpleNamespace(policy=policy, db=db, service=service, space=space,
                              engine=engine, roots=roots)
    engine.dispose()


def grant(budget, resource, amount, *, phase="write", attempt=0, token=0, policy=None):
    budget.policy.acquire(budget.db, resource=resource, phase=phase, attempt=attempt,
                          token=token, amounts={"ssd": amount},
                          policy=policy or budget.policy.policy_hash(budget.service.limits))


def test_initial_envelope_is_26_gib_plus_floor(budget):
    p, db, service = budget.policy, budget.db, budget.service
    p.initial(db, service, "one", 6 * GIB)
    p.require(db, service, "one", "archive", 6 * GIB)
    p.require(db, service, "one", "initial", 20 * GIB)
    with denied(507):
        p.initial(db, service, "two", 1)


def test_rejected_second_phase_keeps_entire_budget_available(budget):
    budget.space.free = 26 * GIB  # One GiB short, archive itself would fit.
    with denied(507):
        budget.policy.initial(budget.db, budget.service, "rejected", 6 * GIB)
    with denied():
        budget.policy.require(budget.db, budget.service, "rejected", "archive", 6 * GIB)
    grant(budget, "all-remaining", 25 * GIB)
    with denied(507):
        grant(budget, "one-byte-too-many", 1)


def test_same_session_promises_remain_additive_including_materialized_bytes(budget):
    assert budget.db.autoflush is False
    budget.space.free = GIB + 1000
    grant(budget, "first", 600)
    with denied(507):
        grant(budget, "rejected", 401)
    grant(budget, "second", 400)  # Rejection did not consume the remaining 400.
    (budget.roots["attempts"] / "synthetic-payload").write_bytes(b"a" * 600)
    budget.space.free = GIB + 400
    with denied(507):
        grant(budget, "materialized-is-not-a-discount", 1)
    budget.policy.require(budget.db, budget.service, "first", "write", 600)


def test_exact_retry_is_idempotent_but_policy_amount_and_fence_must_match(budget):
    grant(budget, "one", 26 * GIB, phase="preview", attempt=1, token=2)
    grant(budget, "one", 26 * GIB, phase="preview", attempt=1, token=2)
    for kwargs in ({"amount": 1}, {"policy": "0" * 64}):
        with denied():
            grant(budget, "one", kwargs.get("amount", 26 * GIB), phase="preview",
                  attempt=1, token=2, policy=kwargs.get("policy"))
    p, db, service = budget.policy, budget.db, budget.service
    p.require(db, service, "one", "preview", 26 * GIB, attempt=1, token=2)
    for phase, attempt, token in (("confirm", 1, 2), ("preview", 2, 2), ("preview", 1, 3)):
        with denied():
            p.require(db, service, "one", phase, 26 * GIB, attempt=attempt, token=token)
    with denied(507):
        grant(budget, "unchanged-full-budget", 1)


@pytest.mark.parametrize("initial", [False, True])
def test_caller_rollback_does_not_publish_authority(budget, initial):
    if initial:
        budget.policy.initial(budget.db, budget.service, "rolled-back", 6 * GIB)
    else:
        grant(budget, "rolled-back", 26 * GIB)
    budget.db.rollback()
    with denied():
        budget.policy.require(budget.db, budget.service, "rolled-back",
                              "archive" if initial else "write", 6 * GIB if initial else 26 * GIB)
    grant(budget, "replacement", 26 * GIB)


def test_retirement_requires_stop_attestation_and_never_resurrects_token(budget):
    grant(budget, "one", 26 * GIB, attempt=1, token=2)
    with denied():
        budget.policy.retire(budget.db, "one")
    with denied(507):
        grant(budget, "still-charged", 1)
    budget.policy.require(budget.db, budget.service, "one", "write", 26 * GIB, attempt=1, token=2)
    budget.policy.retire(budget.db, "one", durable_stop=True)
    budget.db.commit()  # Tombstone and charge release survive a transaction boundary.
    with denied():
        grant(budget, "one", 26 * GIB, attempt=1, token=2)
    with denied():
        budget.policy.require(budget.db, budget.service, "one", "write", 26 * GIB, attempt=1, token=2)
    grant(budget, "new-resource", 26 * GIB)
    with denied(507):
        grant(budget, "retired-retry-did-not-change-budget", 1)


@pytest.mark.parametrize("mismatch", ["prepared", "configuration", "schema-column", "service-root"])
def test_incompatible_profile_or_schema_denies_without_consuming_budget(budget, mismatch):
    if mismatch == "prepared":
        budget.db.execute(update(StorageSchema).values(state="prepared"))
    elif mismatch == "configuration":
        budget.db.execute(update(StoragePool).values(configuration_sha256="0" * 64))
    elif mismatch == "schema-column":
        budget.db.connection().exec_driver_sql("ALTER TABLE dataset_storage_pool ADD COLUMN unexpected INTEGER")
    else:
        budget.service.attempt_root = budget.roots["imports"]
    with denied():
        budget.policy.initial(budget.db, budget.service, "denied", 6 * GIB)
    budget.db.rollback()
    budget.service.attempt_root = budget.roots["attempts"]
    if mismatch != "schema-column":
        grant(budget, "all-available", 26 * GIB)
    else:
        with denied():
            grant(budget, "schema-remains-incompatible", 1)


def test_persisted_fencing_identity_must_match_the_requested_grant(budget):
    grant(budget, "one", 26 * GIB, attempt=1, token=2)
    # Malformed persisted-state fixture; assertions stay at public requests.
    budget.db.execute(update(StorageGrant).values(token=3))
    with denied():
        budget.policy.require(budget.db, budget.service, "one", "write", 26 * GIB, attempt=1, token=2)
    with denied():
        grant(budget, "one", 26 * GIB, attempt=1, token=2)
    with denied(507):
        grant(budget, "still-charged", 1)


@pytest.mark.parametrize("operation", ["require", "acquire"])
def test_separate_sessions_revalidate_committed_fencing_identity(budget, operation):
    p, service = budget.policy, budget.service
    policy = p.policy_hash(service.limits)
    with Session(budget.engine, autoflush=False, expire_on_commit=False) as first:
        p.acquire(first, resource="cached", phase="write", attempt=1, token=2,
                  amounts={"ssd": 26 * GIB}, policy=policy)
        # Setup only: retain a strong reference so the weak identity map cannot
        # discard this instance. No assertion observes its internal fields.
        cached_grant = first.query(StorageGrant).one()
        first.commit()  # End the reader's transaction BEFORE the second writer.
        with Session(budget.engine) as second:
            second.execute(update(StorageGrant).where(StorageGrant.resource_id == "cached").values(token=3))
            second.commit()  # Public authorization must see this committed state.
        with denied():
            if operation == "require":
                p.require(first, service, "cached", "write", 26 * GIB, attempt=1, token=2)
            else:
                p.acquire(first, resource="cached", phase="write", attempt=1, token=2,
                          amounts={"ssd": 26 * GIB}, policy=policy)
        with denied(507):
            p.acquire(first, resource="charge-is-preserved", phase="write", attempt=0, token=0,
                      amounts={"ssd": 1}, policy=policy)
        first.rollback()
        del cached_grant  # Keep the reference alive through both public requests.


def test_missing_schema_is_not_created_by_verification(budget):
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as empty_db:
            with denied():
                budget.policy.verify(empty_db, budget.service)
            assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("expanded", [True, 0, 2**63])
def test_malformed_limits_fail_closed_and_leave_budget_unchanged(budget, expanded):
    valid = budget.service.limits
    budget.service.limits = SimpleNamespace(expanded_bytes=expanded,
                                            public=lambda: {"expanded_bytes": expanded})
    with denied():
        budget.policy.initial(budget.db, budget.service, "malformed", 6 * GIB)
    budget.service.limits = valid
    grant(budget, "all-available", 26 * GIB)


def test_unconfigured_pool_rejection_does_not_partially_acquire(budget):
    with denied():
        budget.policy.acquire(budget.db, resource="two-pools", phase="write", attempt=0, token=0,
                              amounts={"ssd": 26 * GIB, "unconfigured": 1},
                              policy=budget.policy.policy_hash(budget.service.limits))
    grant(budget, "all-still-available", 26 * GIB)


def test_root_privacy_is_rechecked_before_each_admission(budget):
    root = budget.roots["attempts"]
    root.chmod(0o755)
    try:
        with denied():
            grant(budget, "no-longer-private", 26 * GIB)
    finally:
        root.chmod(0o700)
    grant(budget, "all-still-available", 26 * GIB)


def test_constructor_is_read_only_and_rejects_missing_or_aliased_roots(budget, tmp_path):
    def metadata():
        return {str(path.relative_to(tmp_path)): (path.stat().st_mode, path.stat().st_size,
                                                  path.stat().st_mtime_ns)
                for path in [tmp_path, *tmp_path.rglob("*")]}
    before = metadata()
    PhysicalStorage(roots=budget.roots, pools=dict.fromkeys(budget.roots, "ssd"),
                    free_floors={"ssd": GIB})
    assert metadata() == before
    missing = dict(budget.roots, scratch=tmp_path / "not-created")
    with pytest.raises(FileNotFoundError):
        PhysicalStorage(roots=missing, pools=dict.fromkeys(missing, "ssd"), free_floors={"ssd": GIB})
    aliases = dict.fromkeys(budget.roots, "ssd")
    aliases["scratch"] = "double-counted"
    with pytest.raises(ValueError, match="Pool aliases"):
        PhysicalStorage(roots=budget.roots, pools=aliases,
                        free_floors={"ssd": GIB, "double-counted": GIB})
    assert metadata() == before
