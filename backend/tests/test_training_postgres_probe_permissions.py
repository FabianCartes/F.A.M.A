"""Owned-cluster permission proof through main(), with no DBAPI connections.

The synthetic catalog answers only evidence actually requested by the probe;
connection errors, including their text, never supply catalog evidence.
"""
import json
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest


DATABASE = "fama_training_dev_20260401123456"
SENTINEL = "synthetic bootstrap reached"


@pytest.fixture
def permission_cluster(monkeypatch):
    import sqlalchemy
    from sqlalchemy.exc import OperationalError

    state = SimpleNamespace(
        fault=None, bootstrap=[], controls=[], denials=[], role=None,
        password=None, catalog_reads=[], role_attributes={},
    )

    class DriverFailure(Exception):
        pgcode = None

    def unavailable():
        # Intentionally plausible text, not evidence of permission rejection.
        return OperationalError(None, {}, DriverFailure("permission denied for database"))

    class Row(dict):
        def __getitem__(self, key):
            if isinstance(key, int):
                return tuple(self.values())[key]
            return super().__getitem__(key)

        def __iter__(self):
            return iter(self.values())

        @property
        def _mapping(self):
            return self

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

        fetchall = all

        def first(self):
            return self.rows[0] if self.rows else None

        fetchone = first
        one_or_none = first

        def one(self):
            assert len(self.rows) == 1
            return self.rows[0]

        def scalar(self):
            row = self.first()
            return row[0] if row is not None else None

        scalar_one = scalar
        scalar_one_or_none = scalar

        def mappings(self):
            return self

        def __iter__(self):
            return iter(self.rows)

    def catalog_result(statement):
        lower = statement.lower()
        state.catalog_reads.append(lower)
        if "pg_auth_members" in lower:
            if "exists" in lower or "count(" in lower:
                return Result([Row(value=int(state.fault == "membership"))])
            return Result([Row(roleid=42, member=43)] if state.fault == "membership" else [])
        if "pg_roles" in lower and state.fault == "missing_role":
            return Result([])
        if "pg_database" in lower and state.fault == "missing_database":
            return Result([])
        values = dict(
            rolname="other_writer" if state.fault == "wrong_role" else state.role,
            **state.role_attributes,
            datname="other_database" if state.fault == "wrong_database" else DATABASE,
            oid=790 if state.fault == "wrong_oid" else 789,
            datallowconn=state.fault != "allowconn_false",
            has_database_privilege=(state.fault == "connect_true" or
                                    (state.fault == "connect_changed_after_denial" and bool(state.denials))),
        )
        if state.fault == "nologin":
            values["rolcanlogin"] = False
        if state.fault in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls"):
            values[state.fault] = True
        # Honor the selected catalog columns, rather than return a pre-approved
        # truth value for every SELECT. Split commas outside function arguments.
        projection = re.split(r"\bfrom\b", lower, maxsplit=1)[0].removeprefix("select").strip()
        fields = re.split(r",(?![^()]*\))", projection)
        row = Row()
        for field in fields:
            expression = re.split(r"\s+as\s+", field.strip())[0]
            key = expression.rsplit(".", 1)[-1]
            if "has_database_privilege(" in expression:
                key = "has_database_privilege"
            if key not in values:
                raise AssertionError(f"Unsupported synthetic catalog projection: {expression}")
            alias = re.split(r"\s+as\s+", field.strip())[-1]
            row[alias if " as " in field else key] = values[key]
        return Result([row])

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement, parameters=None):
            sql = str(statement).strip()
            lower = sql.lower()
            if lower.startswith("create role") and parameters and "password" in parameters:
                state.role = sql.split()[2].strip('"')
                state.password = parameters["password"]
                # PostgreSQL CREATE ROLE defaults are NOLOGIN and all these
                # non-elevated attributes; explicit options override them.
                options = set(lower.split())
                state.role_attributes = {
                    column: option in options
                    for column, option in (
                        ("rolcanlogin", "login"), ("rolsuper", "superuser"),
                        ("rolcreatedb", "createdb"), ("rolcreaterole", "createrole"),
                        ("rolreplication", "replication"), ("rolbypassrls", "bypassrls"),
                    )
                }
            if "current_database(), oid, system_identifier" in lower:
                return Result([Row(database=DATABASE, oid=789, system=123456)])
            if lower.startswith("select"):
                if any(name in lower for name in ("pg_roles", "pg_database", "pg_auth_members", "has_database_privilege")):
                    return catalog_result(sql)
                if lower in ("select 1", "select current_user", "select current_user, current_database()"):
                    return Result([Row(user=state.role, database="postgres")] if "current_user" in lower else [Row(value=1)])
                raise AssertionError(f"Unsupported synthetic SELECT: {sql}")
            return Result([])

    class Engine:
        def __init__(self, url):
            self.url = url

        def connect(self):
            if self.url.username == state.role and state.role is not None:
                assert self.url.password == state.password
                if self.url.database == "postgres":
                    state.controls.append((self.url.username, self.url.password))
                    if state.fault == "control_failure":
                        raise unavailable()
                else:
                    assert self.url.database == DATABASE
                    state.denials.append((self.url.username, self.url.password))
                    if state.fault == "non_operational_denial":
                        raise RuntimeError("permission denied for database")
                    if state.fault in ("wrong_sqlstate", "classified_denial"):
                        error = unavailable()
                        error.orig.pgcode = "42501" if state.fault == "classified_denial" else "08006"
                        raise error
                    if state.fault != "target_success":
                        raise unavailable()
            return Connection()

        def dispose(self):
            pass

    bootstrap = ModuleType("scripts.prepare_zip_manual_database")

    def initialize(args):
        state.bootstrap.append(args)
        raise RuntimeError(SENTINEL)

    bootstrap.main = initialize
    monkeypatch.setitem(sys.modules, bootstrap.__name__, bootstrap)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda url, **kwargs: Engine(url))
    return state


def test_missing_sqlstate_fails_closed_despite_independent_permission_state(permission_cluster, capsys):
    from scripts import training_postgres_probe as probe

    state = permission_cluster
    assert probe.main(["--database", DATABASE]) == 1
    output = capsys.readouterr()
    assert state.bootstrap == [], "catalog state cannot prove the cause of an unclassified connection failure"
    assert state.controls == state.denials != [], "control and denial must use the same generated credentials"
    assert state.catalog_reads, "startup error text alone is not permission evidence"
    assert output.out == ""
    assert json.loads(output.err) == {
        "phase": "permission_rejection", "category": "operational_error", "sqlstate_present": False,
    }
    assert SENTINEL not in output.err


def test_classified_permission_denial_preserves_initialization_path(permission_cluster, capsys):
    from scripts import training_postgres_probe as probe

    state = permission_cluster
    state.fault = "classified_denial"
    assert probe.main(["--database", DATABASE]) == 1
    output = capsys.readouterr()
    assert len(state.bootstrap) == 1
    assert "--initialize" in state.bootstrap[0]
    assert state.controls == state.denials != []
    assert output.out == ""
    assert json.loads(output.err) == {
        "phase": "initialize", "category": "unexpected_error", "sqlstate_present": False,
    }
    assert SENTINEL not in output.err


@pytest.mark.parametrize("fault", [
    "missing_role", "missing_database", "wrong_role", "nologin",
    "rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls",
    "membership", "wrong_database", "wrong_oid", "connect_true", "allowconn_false",
    "control_failure", "target_success", "connect_changed_after_denial",
    "non_operational_denial", "wrong_sqlstate",
])
def test_missing_sqlstate_fails_closed_without_permission_preconditions(permission_cluster, capsys, fault):
    from scripts import training_postgres_probe as probe

    state = permission_cluster
    state.fault = fault
    assert probe.main(["--database", DATABASE]) == 1
    assert state.bootstrap == [], f"unsafe permission evidence accepted: {fault}"
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["phase"] == "permission_rejection"
    assert SENTINEL not in output.err
