#!/usr/bin/env python3
"""Disposable, offline PostgreSQL bootstrap regression; not part of pytest.

Requires Docker, the locally available postgres:16-alpine image, SQLAlchemy and
psycopg2. Never accepts a URL or exposes a port. Cleanup failures are reported.
"""
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import time

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
IMAGE = "postgres:16-alpine"


def docker(*args, timeout=60):
    return subprocess.run(["docker", *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout).stdout.strip()


def run_checks(socket_dir):
    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import URL, create_engine, event, inspect, text
    from sqlalchemy.pool import NullPool
    from scripts.prepare_zip_manual_database import (
        _guard_training_development_checkouts, initialize, verify,
    )

    url = URL.create("postgresql+psycopg2", username="postgres", database="postgres",
                     query={"host": str(socket_dir), "port": "5432"})
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 1})
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Owned PostgreSQL did not become ready") from None
                time.sleep(0.5)
        with engine.begin() as conn:
            conn.execute(text('CREATE PUBLICATION bootstrap_sentinel'))
        try:
            try:
                initialize(engine, writers_stopped=True)
            except ValueError:
                pass
            else:
                print('publication: initialization accepted unexpectedly', file=sys.stderr, flush=True)
                raise AssertionError('Bootstrap accepted a database with a publication')
            if inspect(engine).get_table_names(schema='public'):
                raise AssertionError('Rejected publication case created application tables')
            with engine.connect() as conn:
                if conn.execute(text("SELECT count(*) FROM pg_catalog.pg_publication WHERE pubname='bootstrap_sentinel'")).scalar_one() != 1:
                    raise AssertionError('Existing publication was changed')
            print('publication rejection: PASS', flush=True)
        finally:
            with engine.begin() as conn:
                conn.execute(text('DROP PUBLICATION bootstrap_sentinel'))
        with engine.begin() as conn:
            large_object_oid = conn.execute(text('SELECT lo_create(0)')).scalar_one()
        try:
            try:
                initialize(engine, writers_stopped=True)
            except ValueError:
                pass
            else:
                print('large object: initialization accepted unexpectedly', file=sys.stderr, flush=True)
                raise AssertionError('Bootstrap accepted a database with a large object')
            if inspect(engine).get_table_names(schema='public'):
                raise AssertionError('Rejected large object case created application tables')
            with engine.connect() as conn:
                if conn.execute(text('SELECT count(*) FROM pg_catalog.pg_largeobject_metadata WHERE oid=:oid'), {'oid': large_object_oid}).scalar_one() != 1:
                    raise AssertionError('Existing large object was changed')
            print('large object rejection: PASS', flush=True)
        finally:
            with engine.begin() as conn:
                conn.execute(text('SELECT lo_unlink(:oid)'), {'oid': large_object_oid})
        with engine.begin() as conn:
            conn.execute(text('CREATE SCHEMA sentinel'))
            conn.execute(text('CREATE TABLE sentinel.existing (id integer PRIMARY KEY)'))
            conn.execute(text('INSERT INTO sentinel.existing VALUES (42)'))
        before = inspect(engine).get_table_names(schema="public")
        if before:
            raise AssertionError("Disposable public schema was not empty")
        with engine.connect() as conn:
            database, oid, system_id = conn.execute(text(
                "SELECT current_database(), oid, system_identifier "
                "FROM pg_database CROSS JOIN pg_control_system() "
                "WHERE datname = current_database()"
            )).one()

        # Each incorrect identity is checked on the actual checkout, before
        # initialize can reach its nonempty-schema check or any bootstrap DDL.
        for wrong_database, wrong_oid, wrong_system in (
            (database + "_wrong", str(oid), str(system_id)),
            (database, str(oid + 1), str(system_id)),
            (database, str(oid), str(int(system_id) + 1)),
        ):
            mismatch = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 1})
            try:
                _guard_training_development_checkouts(
                    mismatch, wrong_database, wrong_system, wrong_oid)
                for operation in (lambda: initialize(mismatch, writers_stopped=True),
                                  lambda: verify(mismatch)):
                    try:
                        operation()
                    except ValueError as error:
                        if str(error) != "Connected database identity mismatch":
                            raise
                    else:
                        raise AssertionError("Mismatched identity was accepted")
            finally:
                mismatch.dispose()
            after_mismatch = inspect(engine).get_table_names(schema="public")
            with engine.connect() as conn:
                sentinel = conn.execute(text('SELECT id FROM sentinel.existing')).scalar_one()
            if after_mismatch != before or sentinel != 42:
                raise AssertionError("Mismatched checkout changed the disposable database")
        print("identity mismatch initialize/check: PASS", flush=True)

        rejected = False
        try:
            initialize(engine, writers_stopped=True)
        except ValueError:
            rejected = True
        # Check artifacts even if initialization accepted or failed after DDL.
        after = inspect(engine).get_table_names(schema="public")
        with engine.connect() as conn:
            value = conn.execute(text('SELECT id FROM sentinel.existing')).scalar_one()
        if not rejected or after != before or value != 42:
            print(f"non-default schema: rejected={rejected} public_unchanged={after == before} sentinel_unchanged={value == 42}", file=sys.stderr, flush=True)
            raise AssertionError("Bootstrap must reject the nonempty database without DDL")
        print("non-default schema table: PASS", flush=True)
        # This schema and its only row were created by this test in its own
        # disposable PostgreSQL container; no application data is removed.
        with engine.begin() as conn:
            conn.execute(text('DROP SCHEMA sentinel CASCADE'))
        guarded = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 1})
        checkouts = []
        try:
            _guard_training_development_checkouts(guarded, database, str(system_id), str(oid))
            event.listen(guarded, "checkout", lambda *args: checkouts.append(True))
            result = initialize(guarded, writers_stopped=True)
            if result.get("prepared") is not True:
                raise AssertionError("Empty database was not initialized")
            if verify(guarded) != {"prepared": True, "verification": "schema_and_markers"}:
                raise AssertionError("Guarded verification did not succeed")
            if len(checkouts) < 2:
                raise AssertionError("Expected multiple guarded physical checkouts")
            # dispose() replaces the pool; its new connections must retain the guard.
            guarded.dispose()
            with guarded.connect() as conn:
                if conn.execute(text("SELECT current_database()")).scalar_one() != database:
                    raise AssertionError("Unexpected database after reconnect")
            _guard_training_development_checkouts(guarded, database, str(system_id), str(oid + 1))
            guarded.dispose()
            try:
                with guarded.connect():
                    raise AssertionError("Reconnect bypassed the identity guard")
            except ValueError as error:
                if str(error) != "Connected database identity mismatch":
                    raise
        finally:
            guarded.dispose()
        print("empty database initialization and guarded verification: PASS", flush=True)
    finally:
        engine.dispose()


def main():
    for key in list(os.environ):
        if key.startswith("PG"):
            del os.environ[key]
    name = "fama-bootstrap-test-" + secrets.token_hex(16)
    label = "fama.bootstrap-test=" + name
    directory = Path(tempfile.mkdtemp(prefix=".bootstrap-postgres-", dir=ROOT)).resolve()
    socket_dir = directory / "socket"
    container_id = None
    attempted_create = False
    failed = False
    try:
        socket_dir.mkdir(mode=0o777)
        socket_dir.chmod(0o777)
        attempted_create = True
        container_id = docker("create", "--pull", "never", "--name", name,
                              "--label", label, "--network", "none",
                              "--mount", f"type=bind,src={socket_dir},dst=/var/run/postgresql",
                              "-e", "POSTGRES_HOST_AUTH_METHOD=trust", IMAGE,
                              "postgres", "-c", "listen_addresses=")
        info = json.loads(docker("inspect", container_id))[0]
        mounts = info["Mounts"]
        sockets = [m for m in mounts if m["Destination"] == "/var/run/postgresql"]
        others = [m for m in mounts if m["Destination"] != "/var/run/postgresql"]
        if (info["Name"] != "/" + name or info["Config"]["Labels"].get("fama.bootstrap-test") != name
                or info["HostConfig"]["NetworkMode"] != "none" or info["HostConfig"].get("PortBindings")
                or len(sockets) != 1 or sockets[0]["Source"] != str(socket_dir) or not sockets[0]["RW"]
                or any(m["Type"] != "volume" or m["Destination"] != "/var/lib/postgresql/data" for m in others)):
            raise RuntimeError("Owned container isolation verification failed")
        docker("start", container_id)
        deadline = time.monotonic() + 30
        while True:
            logs = subprocess.run(["docker", "logs", container_id], text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2, check=True)
            if "PostgreSQL init process complete; ready for start up." in logs.stdout + logs.stderr:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned PostgreSQL initialization did not complete")
            time.sleep(0.5)
        run_checks(socket_dir)
    except Exception as error:
        print(f"isolated bootstrap regression failed: {type(error).__name__}", file=sys.stderr)
        failed = True
    finally:
        if attempted_create:
            try:
                ids = docker("ps", "-aq", "--no-trunc", "--filter", "name=^/" + name + "$", "--filter", "label=" + label).splitlines()
                if len(ids) > 1 or (container_id and ids != [container_id]):
                    raise RuntimeError("Container identity mismatch")
                if ids:
                    docker("rm", "-f", "-v", ids[0])
            except Exception:
                print(f"cleanup failed; owned container may remain: {name}", file=sys.stderr)
                failed = True
        try:
            allowed = {".s.PGSQL.5432", ".s.PGSQL.5432.lock"}
            entries = list(socket_dir.iterdir())
            if any(p.name not in allowed or stat.S_ISLNK(p.lstat().st_mode) for p in entries):
                raise RuntimeError("Unexpected socket directory entry")
            if entries:
                docker("run", "--rm", "--pull", "never", "--network", "none",
                       "--name", name + "-cleanup", "--label", label, "--user", "postgres",
                       "--mount", f"type=bind,src={socket_dir},dst=/socket", "--entrypoint", "sh",
                       IMAGE, "-c", "rm -f -- /socket/.s.PGSQL.5432 /socket/.s.PGSQL.5432.lock")
            socket_dir.rmdir()
            directory.rmdir()
        except Exception:
            print(f"cleanup failed; owned directory remains: {directory}", file=sys.stderr)
            print(f"cleanup helper may remain: {name}-cleanup", file=sys.stderr)
            if socket_dir.exists():
                for path in socket_dir.iterdir():
                    print(f"remaining path: {path}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
