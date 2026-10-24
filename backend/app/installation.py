"""Primera instalación autorizada por el operador del nodo."""
import hashlib
import hmac
import json
from pathlib import Path
import os
import secrets
import tempfile
import time
import re
from contextlib import contextmanager
from functools import wraps
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.configuration import InstallationStore, load_configuration


class InstallationError(RuntimeError):
    def __init__(self, code: str, status: int = 503):
        self.code, self.status = code, status


@contextmanager
def _node_lock(directory: Path):
    descriptor = os.open(directory / ".installation.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"1")
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise InstallationError("installation_busy", 409) from None
        try:
            yield
        finally:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _serialized(operation):
    @wraps(operation)
    def run(self, *arguments, **kwargs):
        with _node_lock(self.directory):
            if self.configuration().installation_status == "completed":
                raise InstallationError("installation_closed", 410)
            return operation(self, *arguments, **kwargs)
    return run


def _write_json(path: Path, value: dict):
    descriptor, temporary = tempfile.mkstemp(prefix=".setup-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_json(path: Path):
    if path.stat().st_size > 16384:
        raise ValueError()
    return json.loads(path.read_text(encoding="utf-8"))


def _origin(value: str):
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or value != value.strip() or not (parsed.scheme == "https" or
                parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})):
        raise ValueError()
    parsed.port
    return value


def issue_authorization(directory: Path, origin: str) -> dict:
    directory = directory.resolve()
    with _node_lock(directory):
        state = InstallationStore(directory).read()
        if state and state["completed"]:
            raise InstallationError("installation_closed", 410)
        token = secrets.token_urlsafe(32)
        _write_json(directory / "authorization.json", {
            "version": 1, "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "expires_at": int(time.time()) + 900, "origin": _origin(origin),
        })
        return {"code": "installation_authorization_created", "authorization_token": token, "expires_in": 900}

class Installation:
    def __init__(self, directory: Path):
        self.directory = directory

    def configuration(self):
        return load_configuration({"FAMA_CONFIG_DIR": str(self.directory)})

    def authorize(self, request: Request):
        if self.configuration().installation_status == "completed":
            raise InstallationError("installation_closed", 410)
        try:
            authority = _read_json(self.directory / "authorization.json")
            if (authority["version"] != 1 or time.time() >= authority["expires_at"]
                    or not hmac.compare_digest(authority["token_hash"], hashlib.sha256(
                        request.headers.get("X-FAMA-Setup-Code", "").encode()).hexdigest())):
                raise ValueError()
        except (OSError, KeyError, TypeError, ValueError):
            raise InstallationError("installation_authorization_required", 401) from None
        origin = request.headers.get("origin")
        if (request.headers.get("sec-fetch-site") == "cross-site"
                or (origin is not None or request.method != "GET") and origin != authority["origin"]):
            raise InstallationError("installation_origin_forbidden", 403)
        return authority["origin"]

    def state(self):
        from sqlalchemy.engine import make_url
        from app.configuration import credential_path
        c = self.configuration()
        url = make_url(c.database_url) if c.database_url else None
        connection_name = c.values.get("FAMA_CLOUD_SQL_CONNECTION_NAME", "")
        manifest = self.directory.parent / "compose.env"
        if not connection_name and manifest.is_file():
            for line in manifest.read_text(encoding="utf-8").splitlines():
                if line.startswith("FAMA_CLOUD_SQL_CONNECTION_NAME="):
                    connection_name = line.split("=", 1)[1].strip().strip("'\"")
        credentials = credential_path(c)
        return {"status": c.installation_status, "resume_pending": (self.directory / "finalization.json").exists(),
                "configuration": {"project_id": c.values.get("GOOGLE_CLOUD_PROJECT", ""),
                    "bucket_name": c.bucket_name or "", "connection_name": connection_name,
                    "database": url.database if url else "", "database_user": url.username if url else "",
                    "proxy_host": url.host if url else "127.0.0.1", "proxy_port": url.port if url else 5433,
                    "password_saved": bool(url and url.password),
                    "credentials_prepared": bool(credentials and Path(credentials).is_file())}}

    @_serialized
    def configure(self, values: dict, origin: str):
        from sqlalchemy.engine import URL, make_url
        if (self.directory / "finalization.json").exists():
            raise InstallationError("installation_resume_required", 409)
        allowed = {"project_id", "bucket_name", "database", "database_user", "database_password"}
        if (not values or set(values) - allowed or any(not isinstance(v, str) or len(v) > 1024 for v in values.values())):
            raise InstallationError("installation_request_invalid", 422)
        for name in ("database", "database_user"):
            if name in values and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", values[name]):
                raise InstallationError("installation_request_invalid", 422)
        if "project_id" in values and not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", values["project_id"]):
            raise InstallationError("installation_request_invalid", 422)
        if "bucket_name" in values and not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", values["bucket_name"]):
            raise InstallationError("installation_request_invalid", 422)
        c = self.configuration()
        current = InstallationStore(self.directory).read()
        public = dict(current["values"]) if current else {}
        name = self.state()["configuration"]["connection_name"]
        if name:
            if values.get("project_id", name.split(":")[0]) != name.split(":")[0]:
                raise InstallationError("installation_project_mismatch", 422)
            public["FAMA_CLOUD_SQL_CONNECTION_NAME"] = name
        secret_dir = self.directory / "secrets"
        secret_dir.mkdir(mode=0o700, exist_ok=True)

        def secret(value):
            descriptor, path = tempfile.mkstemp(prefix="node-", dir=secret_dir)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            return str(Path(path).resolve())

        if set(values) & {"database", "database_user", "database_password"}:
            old = make_url(c.database_url) if c.database_url else None
            password = values.get("database_password") or (old.password if old else None)
            if not password:
                raise InstallationError("installation_database_password_required", 422)
            url = URL.create("postgresql+psycopg2", username=values.get("database_user", old.username if old else ""),
                password=password, host=old.host if old else "127.0.0.1", port=old.port if old else 5433,
                database=values.get("database", old.database if old else ""), query={"sslmode": "disable"})
            public["DATABASE_URL_FILE"] = secret(url.render_as_string(hide_password=False))
        for key in ("JWT_SECRET_KEY", "FAMA_RATE_LIMIT_KEY"):
            if not c.values.get(key):
                public[key + "_FILE"] = secret(secrets.token_urlsafe(48))
        for field, key in (("project_id", "GOOGLE_CLOUD_PROJECT"), ("bucket_name", "GCS_BUCKET_NAME")):
            if field in values:
                public[key] = values[field]
        public.update(FAMA_WEB_ORIGIN=origin, FAMA_ALLOW_INSECURE_LOOPBACK="1" if origin.startswith("http://") else "0")
        InstallationStore(self.directory).save(public)
        return {"code": "installation_configuration_saved"}

    def check(self):
        from app.connections import diagnose
        from app.schema import check_schema
        from app.database_connection import database_engine
        from migrations.schema_0003 import metadata
        c = self.configuration()
        checks = diagnose(c)
        schema = check_schema(c.database_url) if c.database_url else None
        checks["schema"] = {"ok": bool(schema and schema.code == "schema_current"),
                            "code": schema.code if schema else "database_configuration_missing",
                            "revision": schema.revision if schema else None}
        checks["configuration"] = {"ok": not c.missing_requirements,
                                   "code": "configuration_ready" if not c.missing_requirements else "configuration_incomplete"}
        try:
            from app.web_settings import settings
            from app.services.access_limits import configuration as limits
            settings(c.values)
            limits(c.values)
            if c.missing_requirements or c.values.get("JWT_SECRET_KEY") == "fama_bioacoustic_secret_key_mlops_2026":
                raise ValueError()
        except Exception:
            checks["configuration"] = {"ok": False, "code": "configuration_invalid"}
        checks["first_admin"] = {"ok": False, "code": "database_unavailable"}
        checks["permissions"] = {"ok": False, "code": "database_unavailable"}
        if checks["schema"]["ok"]:
            engine = database_engine(c.database_url)
            try:
                with engine.connect() as db:
                    db.exec_driver_sql("SET TRANSACTION READ ONLY")
                    tables = db.exec_driver_sql("""SELECT c.relname, pg_has_role(current_user,c.relowner,'MEMBER'),
                        has_table_privilege(current_user,c.oid,'SELECT'), has_table_privilege(current_user,c.oid,'INSERT'),
                        has_table_privilege(current_user,c.oid,'UPDATE'), has_table_privilege(current_user,c.oid,'DELETE'),
                        has_table_privilege(current_user,c.oid,'TRUNCATE'), has_table_privilege(current_user,c.oid,'REFERENCES'),
                        has_table_privilege(current_user,c.oid,'TRIGGER'),
                        (has_table_privilege(current_user,c.oid,'SELECT WITH GRANT OPTION') OR
                         has_table_privilege(current_user,c.oid,'INSERT WITH GRANT OPTION') OR
                         has_table_privilege(current_user,c.oid,'UPDATE WITH GRANT OPTION') OR
                         has_table_privilege(current_user,c.oid,'DELETE WITH GRANT OPTION'))
                        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                        WHERE n.nspname='public' AND c.relkind='r'""").all()
                    business = [row for row in tables if row[0] != "alembic_version"]
                    version = [row for row in tables if row[0] == "alembic_version"]
                    sequences = db.exec_driver_sql("""SELECT has_sequence_privilege(current_user,c.oid,'USAGE'),
                        has_sequence_privilege(current_user,c.oid,'SELECT'),has_sequence_privilege(current_user,c.oid,'UPDATE')
                        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                        WHERE n.nspname='public' AND c.relkind='S'""").all()
                    role = db.exec_driver_sql("""SELECT rolsuper,rolcreatedb,rolcreaterole,
                        has_schema_privilege(current_user,'public','CREATE') FROM pg_roles WHERE rolname=current_user""").one()
                    valid = (set(row[0] for row in business) == set(metadata.tables)
                        and all(tuple(row[1:]) == (False,True,True,True,True,False,False,False,False) for row in business)
                        and len(version) == 1 and tuple(version[0][1:]) == (False,True,False,False,False,False,False,False,False)
                        and len(sequences) == 9 and all(tuple(row) == (True,True,False) for row in sequences) and not any(role))
                    checks["permissions"] = {"ok": valid, "code": "database_runtime_permissions_ready" if valid else "database_runtime_permissions_invalid"}
                    occupied = any(db.exec_driver_sql(f'SELECT 1 FROM public."{name}" LIMIT 1').first()
                                   for name in metadata.tables)
                pending = (self.directory / "finalization.json").exists()
                checks["first_admin"] = {"ok": not occupied or pending,
                    "code": "initial_administrator_resume_pending" if pending else
                            "database_already_initialized" if occupied else "initial_administrator_available"}
            except Exception:
                pass
            finally:
                engine.dispose()
        return {"ready": all(item["ok"] for item in checks.values()), "checks": checks}

    def _intent(self):
        path = self.directory / "finalization.json"
        if not path.exists():
            return None
        try:
            value = _read_json(path)
            if (set(value) != {"version", "fingerprint", "email", "name", "password_hash"}
                    or value["version"] != 1 or any(not isinstance(value[key], str) or not value[key]
                        for key in ("fingerprint", "email", "name", "password_hash"))):
                raise ValueError()
            return value
        except (OSError, ValueError, TypeError):
            raise InstallationError("installation_journal_invalid") from None

    @_serialized
    def complete(self, values: dict):
        from sqlalchemy import text
        from sqlalchemy.engine import make_url
        from app.database_connection import database_engine
        from app.passwords import hash_password
        from migrations.schema_0003 import metadata
        intent = self._intent()
        if intent and values:
            raise InstallationError("installation_resume_required", 409)
        if not intent:
            if (set(values) != {"email", "name", "password"} or any(not isinstance(v, str) for v in values.values())
                    or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"].strip())
                    or len(values["email"]) > 150 or not 1 <= len(values["name"].strip()) <= 150
                    or not 12 <= len(values["password"]) <= 1024 or not values["password"].strip()):
                raise InstallationError("installation_request_invalid", 422)
        checks = self.check()
        if checks["checks"]["first_admin"]["code"] == "database_already_initialized":
            raise InstallationError("database_already_initialized", 409)
        if not checks["ready"]:
            raise InstallationError("installation_checks_failed", 409)
        c = self.configuration()
        url = make_url(c.database_url)
        target = {"host": url.host, "port": url.port, "database": url.database, "user": url.username,
                  "project": c.values.get("GOOGLE_CLOUD_PROJECT"), "bucket": c.bucket_name,
                  "origin": c.values.get("FAMA_WEB_ORIGIN")}
        fingerprint = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()
        if intent and intent["fingerprint"] != fingerprint:
            raise InstallationError("installation_configuration_changed", 409)
        engine = database_engine(c.database_url)
        try:
            with engine.begin() as db:
                if not db.scalar(text("SELECT pg_try_advisory_xact_lock(5065941)")):
                    raise InstallationError("installation_busy", 409)
                users = db.exec_driver_sql("SELECT id_usuario,correo_electronico,hash_contrasena,nombre_completo,rol,activo FROM public.usuario").all()
                if users:
                    if (not intent or len(users) != 1 or users[0][1] != intent["email"]
                            or not hmac.compare_digest(users[0][2], intent["password_hash"])
                            or tuple(users[0][3:]) != (intent["name"], "administrador", True)):
                        raise InstallationError("database_already_initialized", 409)
                    if any(db.exec_driver_sql(f'SELECT 1 FROM public."{name}" LIMIT 1').first()
                           for name in metadata.tables if name not in {"usuario", "evento_seguridad"}):
                        raise InstallationError("database_already_initialized", 409)
                    events = db.exec_driver_sql("SELECT action,outcome,actor_id,subject_user_id,dataset_id FROM public.evento_seguridad").all()
                    if events != [("account.created", "success", users[0][0], users[0][0], None)]:
                        raise InstallationError("database_already_initialized", 409)
                else:
                    if any(db.exec_driver_sql(f'SELECT 1 FROM public."{name}" LIMIT 1').first() for name in metadata.tables):
                        raise InstallationError("database_already_initialized", 409)
                    if intent is None:
                        intent = {"version": 1, "fingerprint": fingerprint, "email": values["email"].strip().lower(),
                                  "name": values["name"].strip(), "password_hash": hash_password(values["password"])}
                        _write_json(self.directory / "finalization.json", intent)
                    user = db.execute(text("""INSERT INTO public.usuario
                        (correo_electronico,hash_contrasena,rol,nombre_completo,activo,fecha_creacion)
                        VALUES (:email,:password,'administrador',:name,true,CURRENT_TIMESTAMP)
                        RETURNING id_usuario"""), {"email": intent["email"], "password": intent["password_hash"],
                                                  "name": intent["name"]}).scalar_one()
                    db.execute(text("""INSERT INTO public.evento_seguridad
                        (occurred_at,action,outcome,actor_id,subject_user_id)
                        VALUES (:now,'account.created','success',:user,:user)"""), {"now": int(time.time()), "user": user})
            public = InstallationStore(self.directory).read()["values"]
            InstallationStore(self.directory).save(public, completed=True)
            for name in ("finalization.json", "authorization.json"):
                try:
                    (self.directory / name).unlink(missing_ok=True)
                except OSError:
                    pass
            return {"code": "installation_completed", "restart_required": True}
        except InstallationError:
            raise
        except Exception:
            raise InstallationError("installation_finalization_pending") from None
        finally:
            engine.dispose()



async def _body(request: Request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise InstallationError("installation_request_invalid", 415)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 16384:
            raise InstallationError("installation_request_too_large", 413)
    try:
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise InstallationError("installation_request_invalid", 422) from None


def installation_router(directory: Path):
    installation = Installation(directory)
    router = APIRouter(prefix="/api/installation")

    @router.get("/state")
    def state(request: Request):
        installation.authorize(request)
        return installation.state()

    @router.post("/configuration")
    async def configure(request: Request):
        origin = installation.authorize(request)
        values = await _body(request)
        try:
            return await run_in_threadpool(installation.configure, values, origin)
        except (OSError, ValueError):
            raise InstallationError("installation_configuration_failed") from None

    @router.post("/check")
    async def check(request: Request):
        installation.authorize(request)
        if await _body(request):
            raise InstallationError("installation_request_invalid", 422)
        return await run_in_threadpool(installation.check)

    @router.post("/complete")
    async def complete(request: Request):
        installation.authorize(request)
        return await run_in_threadpool(installation.complete, await _body(request))

    return router
