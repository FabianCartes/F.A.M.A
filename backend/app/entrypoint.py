"""Entrada ligera: instalación y diagnósticos antes del backend funcional."""
from contextlib import asynccontextmanager
from pathlib import Path
from contextlib import ExitStack
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.configuration import Configuration, ConfigurationError, load_configuration


def create_app(configuration: Configuration | None = None) -> FastAPI:
    try:
        configuration = configuration or load_configuration()
    except ConfigurationError:
        configuration = None
    code = "installation_required"
    operational = None
    directory = None
    runtime_error = None
    if configuration and 'FAMA_RUNTIME_DIR' in configuration.values:
        from app.runtime import RuntimeDirectory
        try:
            directory = RuntimeDirectory(configuration)
            with directory.lease():
                pass  # Fail before SQL/ML if this tree belongs to another node/environment.
        except ConfigurationError as error:
            runtime_error = str(error)
            directory = None
    if configuration is None:
        code = "configuration_invalid"
    elif runtime_error:
        code = runtime_error
    elif configuration.installation_status != "required":
        if configuration.missing_requirements:
            code = "configuration_incomplete"
        else:
            from app.schema import check_schema
            code = check_schema(configuration.database_url).code
    if code == "schema_current":
        from app.configuration import activate_configuration
        activate_configuration(configuration)
        from app.services.auth import ensure_authentication_configured, AuthenticationConfigurationError
        from app.services.web_sessions import settings as session_settings
        from app.services.access_limits import configuration as access_limit_settings
        try:
            ensure_authentication_configured()
            session_settings()
            access_limit_settings()
        except (AuthenticationConfigurationError, HTTPException):
            code = "configuration_invalid"
        if code == "schema_current":
            from app.main import app as operational

    @asynccontextmanager
    async def lifespan(app):
        with ExitStack() as ownership:
            if directory is not None:
                # Losing the startup race must abort startup, never leave mounted routes running.
                ownership.enter_context(directory.lease())
            if operational is None:
                yield
            else:
                async with operational.router.lifespan_context(operational):
                    yield

    app = FastAPI(title="F.A.M.A.", docs_url=None, redoc_url=None, lifespan=lifespan)

    from app.installation import InstallationError, installation_router

    @app.exception_handler(InstallationError)
    async def installation_error(request, error):
        return JSONResponse({"code": error.code}, status_code=error.status, headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def installation_no_store(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/installation/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/installation/status")
    def installation_status():
        try:
            current = load_configuration({"FAMA_CONFIG_DIR": configuration.values["FAMA_CONFIG_DIR"]}) \
                if configuration and configuration.values.get("FAMA_CONFIG_DIR") else configuration
            return {"status": current.installation_status if current else "unavailable"}
        except ConfigurationError:
            return {"status": "unavailable"}

    @app.get("/ready")
    def ready():
        current_code = code
        if directory is not None and code != 'runtime_in_use':
            try:
                directory.describe()
            except ConfigurationError as error:
                return JSONResponse({'code': str(error)}, status_code=503)
        if operational is not None:
            from app.schema import check_schema
            current_code = check_schema(configuration.database_url).code
        return JSONResponse({"code": current_code}, status_code=200 if current_code == "schema_current" else 503)

    if configuration and configuration.values.get("FAMA_CONFIG_DIR"):
        app.include_router(installation_router(Path(configuration.values["FAMA_CONFIG_DIR"])))

    if operational is not None:
        app.mount("/", operational)
    else:
        @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
        def unavailable(path: str):
            return JSONResponse({"code": code}, status_code=503)

    return app
