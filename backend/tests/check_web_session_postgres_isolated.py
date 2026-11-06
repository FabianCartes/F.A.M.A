#!/usr/bin/env python3
"""Explicit Docker-only PostgreSQL migration regression; not part of pytest.

Requires a local postgres:16-alpine image, Docker, psycopg2 and SQLAlchemy.
Creates no host port and never accepts a database URL. Cleanup is best effort;
any owned remnants are reported and make the process fail.
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
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout).stdout.strip()


def startup_diagnostic(container_id, socket_dir, error):
    """Report bounded, allowlisted evidence without emitting driver or log text."""
    original = getattr(error, "orig", error)
    code = getattr(original, "pgcode", None)
    code = code if isinstance(code, str) and len(code) == 5 and code.isalnum() else "none"
    socket = socket_dir / ".s.PGSQL.5432"
    try:
        socket_present = stat.S_ISSOCK(socket.lstat().st_mode)
    except OSError:
        socket_present = False
    print(f"startup: socket_present={socket_present} exception={type(error).__name__} "
          f"driver_exception={type(original).__name__} pgcode={code}", file=sys.stderr)
    try:
        info = json.loads(docker("inspect", container_id, timeout=2))[0]["State"]
        print(f"startup: running={bool(info['Running'])} exit_code={int(info['ExitCode'])} "
              f"oom_killed={bool(info.get('OOMKilled'))}", file=sys.stderr)
        logs = subprocess.run(["docker", "logs", "--tail", "50", container_id],
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=2, check=True)
        text = (logs.stdout + logs.stderr).lower()
        # Only the owned empty test container is inspected; emit log categories,
        # not connection details or SQL.
        for line in (logs.stdout + logs.stderr).splitlines():
            print("postgres disposable test:", line[:500], file=sys.stderr)
        # Fixed labels remain useful when no selected category is emitted.
        for label, marker in (("ready_message", "ready to accept connections"),
                              ("permission_denied", "permission denied"),
                              ("socket_path_too_long", "unix-domain socket path"),
                              ("fatal", "fatal:"), ("init_error", "initdb: error"),
                              ("panic", "panic:"), ("signal", "terminated by signal"),
                              ("disk_full", "no space left"), ("shutdown", "shutdown request")):
            print(f"startup: {label}={marker in text}", file=sys.stderr)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        print("startup: container diagnostics unavailable", file=sys.stderr)


def run_checks(socket_dir, container_id):
    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import URL, create_engine, inspect, text
    from sqlalchemy.pool import NullPool
    from app.models.user import Usuario
    from app.models.web_session import SesionWeb
    from app.models.access_quota import CuotaAcceso
    from app.models.security_audit import EventoSeguridad
    from scripts.migrate_web_sessions import migrate_web_sessions, validate_web_sessions

    # The sole connection destination is the socket directory just mounted in
    # our container. No environment database URL is consulted.
    url = URL.create("postgresql+psycopg2", username="postgres", database="postgres",
                     query={"host": str(socket_dir), "port": "5432"})
    admin = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 1})
    deadline = time.monotonic() + 10
    while True:
        try:
            with admin.connect() as conn:
                conn.execute(text("SELECT 1"))
            break
        except Exception as error:
            if time.monotonic() >= deadline:
                startup_diagnostic(container_id, socket_dir, error)
                admin.dispose()
                raise RuntimeError("Owned PostgreSQL did not become ready") from None
            time.sleep(0.5)

    def diagnose_fresh_checks():
        # Fresh schemas contain only model-generated DDL, never application data.
        for index, table in enumerate((SesionWeb.__table__, CuotaAcceso.__table__,
                                       EventoSeguridad.__table__)):
            diagnostic_schema = f"fresh_diagnostic_{index}"
            diagnostic_engine = None
            try:
                with admin.begin() as conn:
                    conn.execute(text(f'CREATE SCHEMA "{diagnostic_schema}"'))
                diagnostic_engine = create_engine(
                    url, poolclass=NullPool,
                    connect_args={"connect_timeout": 2, "options": f"-csearch_path={diagnostic_schema}"})
                with diagnostic_engine.begin() as conn:
                    if conn.execute(text("SELECT current_schema() = :expected"),
                                    {"expected": diagnostic_schema}).scalar_one() is not True:
                        raise RuntimeError("Unexpected diagnostic schema")
                    Usuario.__table__.create(conn)
                    table.create(conn)
                    actual = [check["sqltext"] for check in inspect(conn).get_check_constraints(table.name)]
                    expected = [str(check.sqltext) for check in table.constraints if hasattr(check, "sqltext")]
                    print(f"diagnostic {table.name}: actual={actual!r} expected={expected!r}",
                          file=sys.stderr, flush=True)
            except Exception:
                print(f"diagnostic {table.name}: unavailable", file=sys.stderr, flush=True)
            finally:
                if diagnostic_engine is not None:
                    diagnostic_engine.dispose()

    failures = []
    cases = [("fresh", None, None),
             ("quota_missing", "cuota_acceso", None),
             ("quota_weak", "cuota_acceso", "intentos >= 0"),
             ("event_missing", "evento_seguridad", None),
             ("event_weak", "evento_seguridad", "outcome IN ('success', 'denied', 'other')"),
             ("quota_not_valid", "cuota_acceso", "intentos > 0"),
             ("event_not_valid", "evento_seguridad", "outcome IN ('success', 'denied')")]
    try:
        for schema, target, replacement in cases:
            engine = None
            stage = "create_schema"
            try:
                with admin.begin() as conn:
                    conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                stage = "create_engine"
                engine = create_engine(url, poolclass=NullPool,
                                       connect_args={"connect_timeout": 2, "options": f"-csearch_path={schema}"})
                stage = "schema_probe"
                with engine.connect() as conn:
                    if conn.execute(text("SELECT 1")).scalar_one() != 1:
                        raise AssertionError("Connection probe failed")
                    schema_matches = conn.execute(text("SELECT current_schema() = :expected"),
                                                  {"expected": schema}).scalar_one()
                    print(f"{schema}: schema_matches={schema_matches is True}", flush=True)
                    if schema_matches is not True:
                        raise AssertionError("Unexpected current schema")
                stage = "create_user"
                Usuario.__table__.create(engine)
                if target is None:
                    stage = "first_migration"
                    migrate_web_sessions(engine, writers_stopped=True)
                    stage = "second_migration"
                    migrate_web_sessions(engine, writers_stopped=True)
                    stage = "validate"
                    validate_web_sessions(engine)
                else:
                    # Leave a different required table absent: a rejected preflight
                    # must not create it as an acceptance artifact.
                    stage = "create_target"
                    table = {"cuota_acceso": CuotaAcceso.__table__,
                             "evento_seguridad": EventoSeguridad.__table__}[target]
                    table.create(engine)
                    constraint = {"cuota_acceso": "chk_cuota_intentos_positivos",
                                  "evento_seguridad": "chk_evento_resultado"}[target]
                    stage = "tamper_check"
                    with engine.begin() as conn:
                        conn.execute(text(f'ALTER TABLE "{target}" DROP CONSTRAINT "{constraint}"'))
                        if replacement:
                            suffix = " NOT VALID" if schema.endswith("_not_valid") else ""
                            conn.execute(text(f'ALTER TABLE "{target}" ADD CONSTRAINT "{constraint}" CHECK ({replacement}){suffix}'))
                    stage = "reject_migration"
                    try:
                        migrate_web_sessions(engine, writers_stopped=True)
                    except RuntimeError as error:
                        if "Incompatible web-session checks" not in str(error):
                            raise AssertionError("Rejected for the wrong reason") from error
                    else:
                        raise AssertionError("Migration accepted an absent or weakened check")
                    stage = "check_artifacts"
                    if inspect(engine).has_table(SesionWeb.__tablename__):
                        raise AssertionError("Rejected migration created the absent session table")
                print(f"{schema}: PASS", flush=True)
            except Exception as error:
                # Fixed labels and allowlisted class names only; never print exception text.
                original = getattr(error, "orig", error)
                name = type(original).__name__
                allowed = {"OperationalError", "InterfaceError", "DatabaseError", "ProgrammingError",
                           "IntegrityError", "DataError", "InternalError", "NotSupportedError",
                           "AssertionError", "RuntimeError"}
                driver_class = name if name in allowed else "Other"
                code = getattr(original, "pgcode", None)
                sqlstate = code if (isinstance(code, str) and len(code) == 5
                                    and all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in code)) else "none"
                print(f"{schema}: FAIL stage={stage} driver_exception={driver_class} sqlstate={sqlstate}",
                      file=sys.stderr, flush=True)
                if not failures and driver_class == "OperationalError":
                    startup_diagnostic(container_id, socket_dir, error)
                failures.append(schema)
                if schema == "fresh" and stage == "first_migration":
                    diagnose_fresh_checks()
            finally:
                if engine is not None:
                    engine.dispose()
    finally:
        admin.dispose()
    if failures:
        raise RuntimeError("Regression failed: " + ", ".join(failures))


def main():
    # libpq otherwise accepts ambient PGHOSTADDR, PGSERVICE and related settings.
    for key in list(os.environ):
        if key.startswith("PG"):
            del os.environ[key]
    name = "fama-web-session-test-" + secrets.token_hex(16)
    label = "fama.web-session-test=" + name
    directory = Path(tempfile.mkdtemp(prefix=".web-session-postgres-", dir=ROOT)).resolve()
    socket_dir = directory / "socket"
    container_id = None
    attempted_create = False
    failed = False
    try:
        socket_dir.mkdir(mode=0o777)
        socket_dir.chmod(0o777)  # private parent remains mode 0700
        attempted_create = True
        container_id = docker("create", "--pull", "never", "--name", name,
                              "--label", label, "--network", "none",
                              "--mount", f"type=bind,src={socket_dir},dst=/var/run/postgresql",
                              "-e", "POSTGRES_HOST_AUTH_METHOD=trust", IMAGE,
                              "postgres", "-c", "listen_addresses=")
        info = json.loads(docker("inspect", container_id))[0]
        mounts = info["Mounts"]
        socket_mounts = [m for m in mounts if m["Destination"] == "/var/run/postgresql"]
        other_mounts = [m for m in mounts if m["Destination"] != "/var/run/postgresql"]
        if (info["Name"] != "/" + name or info["Config"]["Labels"].get("fama.web-session-test") != name
                or info["HostConfig"]["NetworkMode"] != "none"
                or info["HostConfig"].get("PortBindings")
                or len(socket_mounts) != 1 or socket_mounts[0]["Source"] != str(socket_dir)
                or not socket_mounts[0]["RW"]
                or any(m["Type"] != "volume" or m["Destination"] != "/var/lib/postgresql/data" for m in other_mounts)):
            raise RuntimeError("Owned container isolation verification failed")
        docker("start", container_id)
        # The image briefly starts an init server, then shuts it down before
        # starting the final server. Do not connect to that transient socket.
        deadline = time.monotonic() + 30
        while True:
            logs = subprocess.run(["docker", "logs", container_id], text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=2, check=True)
            if "PostgreSQL init process complete; ready for start up." in logs.stdout + logs.stderr:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned PostgreSQL initialization did not complete")
            time.sleep(0.5)
        run_checks(socket_dir, container_id)
    except Exception as error:
        print(f"isolated regression failed: {type(error).__name__}", file=sys.stderr)
        failed = True
    finally:
        # A create timeout may have created the named resource despite no response.
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
        # Only the two PostgreSQL socket entries are eligible for owner cleanup.
        try:
            allowed = {".s.PGSQL.5432", ".s.PGSQL.5432.lock"}
            entries = list(socket_dir.iterdir())
            if any(p.name not in allowed or stat.S_ISLNK(p.lstat().st_mode) for p in entries):
                raise RuntimeError("Unexpected socket directory entry")
            if entries:
                docker("run", "--rm", "--pull", "never", "--network", "none",
                       "--name", name + "-cleanup", "--label", label,
                       "--user", "postgres", "--mount", f"type=bind,src={socket_dir},dst=/socket",
                       "--entrypoint", "sh", IMAGE, "-c",
                       "rm -f -- /socket/.s.PGSQL.5432 /socket/.s.PGSQL.5432.lock")
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
