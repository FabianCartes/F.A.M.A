"""Diagnóstico de conexiones de solo lectura, independiente del backend ML."""
import json
import os
from functools import partial

from app.configuration import Configuration, ConfigurationError, credential_path, load_configuration


def _result(code: str, ok: bool = False) -> dict:
    return {"ok": ok, "code": code}


def _database(address: str | None) -> dict:
    if not address:
        return _result("database_configuration_missing")
    from sqlalchemy.engine import make_url
    from app.database_connection import database_engine

    engine = None
    try:
        if make_url(address).get_backend_name() not in {"postgres", "postgresql"}:
            return _result("database_unsupported")
        engine = database_engine(address)
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql("SELECT 1")
        return _result("database_connected", True)
    except Exception as error:
        original = getattr(error, "orig", error)
        state = getattr(original, "pgcode", "") or ""
        # libpq no siempre conserva SQLSTATE en errores anteriores a la sesión.
        message = str(original).casefold()
        if state.startswith("28") or any(value in message for value in (
            "password authentication failed", "no password supplied", "autenticación password falló",
        )):
            return _result("database_authentication_failed")
        if state == "42501":
            return _result("database_forbidden")
        return _result("database_unavailable")
    finally:
        if engine is not None:
            engine.dispose()


def _storage(configuration: Configuration) -> dict:
    if not configuration.bucket_name:
        return _result("storage_configuration_missing")
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError, RefreshError
    from google.auth.transport.requests import Request
    from google.api_core.exceptions import Forbidden, NotFound
    from google.cloud import storage
    import requests

    try:
        with requests.Session() as session:
            request = partial(Request(session=session), timeout=10)
            options = {"scopes": ["https://www.googleapis.com/auth/cloud-platform"], "request": request}
            path = credential_path(configuration)
            if path:
                credentials, inferred_project = google.auth.load_credentials_from_file(path, **options)
            else:
                credentials, inferred_project = google.auth.default(**options)
            project = configuration.values.get("GOOGLE_CLOUD_PROJECT") or inferred_project
            if not project:
                return _result("storage_project_missing")
            if not credentials.valid:
                credentials.refresh(request)
            with storage.Client(project=project, credentials=credentials) as client:
                list(client.list_blobs(configuration.bucket_name, max_results=1,
                                       fields="items(name),nextPageToken", timeout=5, retry=None))
        return _result("storage_read_connected", True)
    except DefaultCredentialsError:
        return _result("storage_credentials_missing")
    except RefreshError:
        return _result("storage_authentication_failed")
    except Forbidden:
        return _result("storage_forbidden")
    except NotFound:
        return _result("storage_bucket_not_found")
    except Exception:
        return _result("storage_unavailable")


def diagnose(configuration: Configuration) -> dict:
    return {
        "database": _database(configuration.database_url),
        "storage": _storage(configuration),
    }


def main() -> int:
    try:
        report = diagnose(load_configuration(dict(os.environ)))
    except ConfigurationError:
        report = {"configuration": {"ok": False, "code": "configuration_invalid"}}
    print(json.dumps(report))
    return 0 if all(value["ok"] for value in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
