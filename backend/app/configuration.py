"""Configuración del nodo: sin conexiones, modelos ni valores institucionales implícitos."""
import json
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Mapping


class ConfigurationError(ValueError):
    """Error sanitizado: nunca incluye contenido ni rutas de secretos."""


def protect_private_directory(directory: Path) -> None:
    """Protect a newly created private directory before writing secrets or SQL archives."""
    if os.name != 'nt':
        return
    import subprocess
    program = """
$ErrorActionPreference = 'Stop'
$security = [Security.AccessControl.DirectorySecurity]::new()
$security.SetAccessRuleProtection($true, $false)
$identities = @([Security.Principal.WindowsIdentity]::GetCurrent().User,
                [Security.Principal.SecurityIdentifier]::new('S-1-5-18'))
foreach ($identity in $identities) {
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $security.AddAccessRule($rule)
}
[IO.Directory]::SetAccessControl($env:FAMA_PRIVATE_DIRECTORY, $security)
"""
    powershell = Path(os.environ['SYSTEMROOT'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', program],
                   env=dict(os.environ, FAMA_PRIVATE_DIRECTORY=str(directory)),
                   capture_output=True, check=True, timeout=15)


_PUBLIC_KEYS = {
    "FAMA_RUNTIME_DIR", "FAMA_IMPORT_ROOT", "FAMA_EXPORT_ROOT", "FAMA_EXPORT_DOWNLOAD_ORIGIN",
    "GCS_BUCKET_NAME", "GOOGLE_APPLICATION_CREDENTIALS", "GCP_KEY_PATH", "GOOGLE_CLOUD_PROJECT",
    "FAMA_CLOUD_SQL_CONNECTION_NAME",
    "FAMA_ENSEMBLES_JSON",
    "FAMA_WEB_ORIGIN", "FAMA_ALLOW_INSECURE_LOOPBACK", "FAMA_SESSION_MAX_AGE_SECONDS",
    "FAMA_SESSION_IDLE_SECONDS", "FAMA_AUDIT_RETENTION_DAYS",
    "FAMA_ACCESS_LIMITS_JSON", "DATABASE_URL_FILE", "JWT_SECRET_KEY_FILE",
    "FAMA_RATE_LIMIT_KEY_FILE",
}
_SECRET_KEYS = ("DATABASE_URL", "JWT_SECRET_KEY", "FAMA_RATE_LIMIT_KEY")


def declared_ensembles(values: Mapping[str, str]) -> tuple[tuple[str, ...], str | None]:
    """Validate an explicit installation declaration without importing inference."""
    raw = values.get("FAMA_ENSEMBLES_JSON")
    if raw is None:
        return (), None
    known = {"chilean-birds-ensemble", "car-engine-diagnostics-super-ensemble"}
    try:
        if not isinstance(raw, str) or len(raw) > 16384:
            raise ValueError
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {"version", "enabled", "default"}
                or type(data["version"]) is not int or data["version"] != 1):
            raise ValueError
        enabled, default = data["enabled"], data["default"]
        if (not isinstance(enabled, list)
                or any(not isinstance(item, str) or item not in known for item in enabled)
                or len(set(enabled)) != len(enabled)
                or (enabled and (not isinstance(default, str) or default not in enabled))
                or (not enabled and default is not None)):
            raise ValueError
        return tuple(enabled), default
    except (ValueError, TypeError, RecursionError):
        raise ConfigurationError("ensemble_declaration_invalid") from None


def _configured_key(value: str) -> bool:
    try:
        return bool(value.strip()) and len(value.encode("utf-8")) >= 32
    except UnicodeError:
        return False


class InstallationStore:
    """Estado del servidor, escrito atómicamente; el operador protege el directorio."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise ConfigurationError("configuration_path_invalid")
        self.path = self.directory / "installation.json"

    def read(self) -> dict | None:
        try:
            if not self.path.exists():
                return None
            if self.path.stat().st_size > 65536:
                raise ValueError
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (set(data) != {"version", "completed", "values"}
                    or data["version"] != 1 or type(data["completed"]) is not bool):
                raise ValueError
            self._validate(data["values"])
            return data
        except (OSError, ValueError, TypeError) as error:
            raise ConfigurationError("installation_state_invalid") from None

    @staticmethod
    def _validate(values):
        if (not isinstance(values, dict) or not set(values) <= _PUBLIC_KEYS
                or any(not isinstance(v, str) or len(v) > 16384 for v in values.values())):
            raise ConfigurationError("installation_values_invalid")
        declared_ensembles(values)

    def save(self, values: dict[str, str], *, completed: bool = False) -> None:
        self._validate(values)
        previous = self.read()
        if previous and previous["completed"]:
            raise ConfigurationError("installation_already_completed")
        self._publish(values, completed)

    def select_runtime(self, directory: Path) -> None:
        """Operator-only local selection; preserve installation closure and secret references."""
        previous = self.read()
        if previous is None:
            raise ConfigurationError("installation_state_required")
        values = dict(previous['values'], FAMA_RUNTIME_DIR=str(directory))
        self._validate(values)
        self._publish(values, previous['completed'])

    def _publish(self, values, completed):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".installation-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "completed": completed, "values": values}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)


@dataclass(frozen=True)
class Configuration:
    database_url: str | None = field(default=None, repr=False)
    bucket_name: str | None = None
    installation_status: str = "required"
    values: Mapping[str, str] = field(default_factory=dict, repr=False)

    @property
    def missing_requirements(self) -> tuple[str, ...]:
        return tuple(name for name, value in (
            ("database", self.database_url), ("bucket", self.bucket_name),
            ("web_origin", self.values.get("FAMA_WEB_ORIGIN")),
            ("jwt_key", _configured_key(self.values.get("JWT_SECRET_KEY", ""))),
            ("rate_limit_key", _configured_key(self.values.get("FAMA_RATE_LIMIT_KEY", ""))),
        ) if not value)


def load_configuration(environment: Mapping[str, str] | None = None) -> Configuration:
    if environment is None:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        environment = os.environ
    values = {}
    managed = environment.get("FAMA_CONFIG_DIR")
    state = InstallationStore(Path(managed)).read() if managed else None
    if state:
        values.update(state["values"])
    values.update(environment)
    declared_ensembles(values)
    for key in _SECRET_KEYS:
        reference = values.get(key + "_FILE")
        if reference:
            try:
                path = Path(reference)
                if not path.is_absolute() or path.stat().st_size > 16384:
                    raise ValueError
                resolved = path.read_text(encoding="utf-8").strip()
            except (OSError, ValueError):
                raise ConfigurationError("secret_file_unavailable") from None
            if values.get(key) and values[key] != resolved:
                raise ConfigurationError("secret_source_ambiguous")
            values[key] = resolved
    status = "required"
    if managed:
        if state and state["completed"]:
            status = "completed"
    elif values.get("DATABASE_URL"):
        status = "configured"
    return Configuration(
        database_url=values.get("DATABASE_URL") or None,
        bucket_name=values.get("GCS_BUCKET_NAME") or None,
        installation_status=status,
        values=values,
    )


_active_configuration: Configuration | None = None


def credential_path(configuration: Configuration) -> str | None:
    """Misma resolución de archivo ADC para el nodo y los diagnósticos."""
    credentials = configuration.values.get("GOOGLE_APPLICATION_CREDENTIALS") or configuration.values.get("GCP_KEY_PATH")
    if not credentials:
        return None
    path = Path(credentials)
    if not path.is_absolute():
        backend = Path(__file__).resolve().parents[1]
        candidates = (Path.cwd() / path, backend / path, backend.parent / path)
        path = next((candidate for candidate in candidates if candidate.exists()), backend / path)
    return str(path.resolve())


def activate_configuration(configuration: Configuration, *, replace_environment: bool = False) -> None:
    """Fija la configuración del proceso antes de importar los servicios funcionales."""
    global _active_configuration
    _active_configuration = configuration
    if replace_environment:
        keys = _PUBLIC_KEYS | set(_SECRET_KEYS) | {key + "_FILE" for key in _SECRET_KEYS} | {"FAMA_CONFIG_DIR"}
        for key in keys:
            os.environ.pop(key, None)
        if configuration.values.get("FAMA_CONFIG_DIR"):
            os.environ["FAMA_CONFIG_DIR"] = configuration.values["FAMA_CONFIG_DIR"]
    for key in _PUBLIC_KEYS | set(_SECRET_KEYS):
        if key in configuration.values and not key.endswith("_FILE"):
            os.environ[key] = configuration.values[key]
    credentials = credential_path(configuration)
    if credentials:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials


def get_configuration() -> Configuration:
    if _active_configuration is None:
        activate_configuration(load_configuration())
    return _active_configuration


def storage_bucket(override: str | None = None) -> str:
    bucket = override or get_configuration().bucket_name
    if not bucket:
        raise ConfigurationError("storage_configuration_missing")
    return bucket
