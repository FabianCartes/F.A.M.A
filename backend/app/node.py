"""Operaciones locales del nodo sobre una configuración elegida explícitamente."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess

from app.configuration import ConfigurationError, InstallationStore, load_configuration
from app.configuration import protect_private_directory as _protect_directory


def create_node_app(directory: str):
    """Arranque nativo sobre el registro seleccionado, sin heredar otro nodo."""
    from app.configuration import activate_configuration
    from app.entrypoint import create_app

    configuration = load_configuration({"FAMA_CONFIG_DIR": str(Path(directory).resolve())})
    activate_configuration(configuration, replace_environment=True)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    return create_app(configuration)


def _write_secret(directory: Path, name: str, value: str) -> Path:
    path = directory / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _prepare(arguments) -> str:
    from sqlalchemy.engine import URL

    root = Path(arguments.config_dir).resolve()
    if root.exists():
        return "configuration_directory_exists"
    credentials = Path(arguments.credentials_file).resolve()
    if not credentials.is_file() or credentials.name != "application_default_credentials.json":
        return "credentials_file_invalid"
    parts = arguments.connection_name.split(":")
    if len(parts) != 3 or parts[0] != arguments.project or not all(parts):
        return "cloud_connection_name_invalid"
    password = getpass.getpass("Contraseña SQL del usuario de aplicación: ")
    if not password:
        return "database_password_required"
    try:
        root.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        return "configuration_directory_exists"
    _protect_directory(root)
    secret_dir = root / "secrets"
    secret_dir.mkdir(mode=0o700)
    _protect_directory(secret_dir)
    for mode, host, port in (("native", "127.0.0.1", arguments.proxy_port), ("docker", "cloud-sql-proxy", 5432)):
        address = URL.create("postgresql+psycopg2", username=arguments.user, password=password,
                             host=host, port=port, database=arguments.database, query={"sslmode": "disable"})
        _write_secret(secret_dir, "database-" + mode, address.render_as_string(hide_password=False))
    _write_secret(secret_dir, "jwt", secrets.token_urlsafe(48))
    _write_secret(secret_dir, "rate-limit", secrets.token_urlsafe(48))
    for mode in ("native", "docker"):
        prefix = secret_dir if mode == "native" else Path("/run/fama/installation/secrets")
        # Las referencias Docker son rutas POSIX aunque la preparación se haga en Windows.
        reference = lambda name: str(prefix / name) if mode == "native" else "/run/fama/installation/secrets/" + name
        values = {
            "DATABASE_URL_FILE": reference("database-" + mode),
            "JWT_SECRET_KEY_FILE": reference("jwt"),
            "FAMA_RATE_LIMIT_KEY_FILE": reference("rate-limit"),
            "GOOGLE_APPLICATION_CREDENTIALS": str(credentials) if mode == "native" else "/run/fama/credentials/application_default_credentials.json",
            "GOOGLE_CLOUD_PROJECT": arguments.project,
            "FAMA_CLOUD_SQL_CONNECTION_NAME": arguments.connection_name,
            "GCS_BUCKET_NAME": arguments.bucket,
            "FAMA_WEB_ORIGIN": arguments.web_origin,
            "FAMA_ALLOW_INSECURE_LOOPBACK": "1" if arguments.web_origin.startswith("http://") else "0",
        }
        mode_directory = root / mode
        mode_directory.mkdir(mode=0o700)
        _protect_directory(mode_directory)
        InstallationStore(mode_directory).save(values)
    uid = getattr(os, "getuid", lambda: 10001)() or 10001
    gid = getattr(os, "getgid", lambda: 10001)()
    compose = {
        "HOST_UID": str(uid), "HOST_GID": str(gid),
        "FAMA_CREDENTIALS_DIR": credentials.parent.as_posix(),
        "FAMA_INSTALLATION_DIR": root.as_posix(),
        "FAMA_CLOUD_SQL_CONNECTION_NAME": arguments.connection_name,
    }
    with (root / "compose.env").open("x", encoding="utf-8") as stream:
        for key, value in compose.items():
            stream.write(key + "='" + value.replace("'", "\\'") + "'\n")
    return "configuration_prepared"


def main() -> int:
    parser = argparse.ArgumentParser(description="Preparación local de conexiones de F.A.M.A.; no aplica migraciones")
    parser.add_argument("--config-dir", required=True)
    commands = parser.add_subparsers(dest="operation", required=True)
    prepare = commands.add_parser("prepare")
    for flag in ("project", "bucket", "credentials-file", "connection-name", "database", "user"):
        prepare.add_argument("--" + flag, required=True)
    prepare.add_argument("--proxy-port", type=int, choices=range(1, 65536), default=5433, metavar="PUERTO")
    prepare.add_argument("--web-origin", default="http://localhost:3000")
    commands.add_parser("check")
    runtime = commands.add_parser('runtime')
    runtime.add_argument('--directory')
    backup = commands.add_parser('backup')
    backup.add_argument('--directory', required=True)
    backup.add_argument('--pg-bin', required=True)
    restore = commands.add_parser('restore')
    restore.add_argument('--backup', required=True)
    restore.add_argument('--target-url-file', required=True)
    restore.add_argument('--pg-bin', required=True)
    recovery = commands.add_parser('recover-admin')
    recovery_target = recovery.add_mutually_exclusive_group(required=True)
    recovery_target.add_argument('--user-id', type=int)
    recovery_target.add_argument('--email')
    recovery.add_argument('--apply', action='store_true')
    recovery.add_argument('--confirm-database')
    recovery.add_argument('--reactivate', action='store_true')
    setup = commands.add_parser("setup-code")
    setup.add_argument("--web-origin", default="http://localhost:3000")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    if arguments.operation == 'recover-admin':
        from app.operator_recovery import OperatorRecoveryError, inspect_administrator, recover_administrator
        from sqlalchemy.exc import SQLAlchemyError
        applying = False
        try:
            configuration = load_configuration({'FAMA_CONFIG_DIR': str(Path(arguments.config_dir).resolve())})
            report = inspect_administrator(configuration, arguments.user_id, email=arguments.email)
            if arguments.apply:
                import sys
                import warnings
                if arguments.confirm_database != report['database']:
                    raise OperatorRecoveryError('administrator_recovery_database_confirmation_required')
                if report['reactivation_required'] and not arguments.reactivate:
                    raise OperatorRecoveryError('administrator_recovery_reactivation_required')
                if not sys.stdin.isatty():
                    raise OperatorRecoveryError('administrator_recovery_interactive_terminal_required')
                print('Correo de la cuenta administradora que vas a recuperar: ',file=sys.stderr,end='',flush=True)
                email = input()
                with warnings.catch_warnings():
                    warnings.simplefilter('error',getpass.GetPassWarning)
                    password = getpass.getpass('Nueva contraseña (12–1024 caracteres): ')
                    confirmation = getpass.getpass('Repite la nueva contraseña: ')
                if password != confirmation:
                    raise OperatorRecoveryError('administrator_recovery_password_mismatch')
                from app.configuration import activate_configuration
                activate_configuration(configuration,replace_environment=True)
                applying = True
                report = recover_administrator(configuration,report['user']['id'],database=arguments.confirm_database,
                                               email=email,password=password,reactivate=arguments.reactivate)
        except OperatorRecoveryError as error:
            report = {'code': str(error)}
        except (EOFError, KeyboardInterrupt):
            report = {'code': 'administrator_recovery_outcome_unknown' if applying else 'administrator_recovery_cancelled'}
        except getpass.GetPassWarning:
            report = {'code': 'administrator_recovery_interactive_terminal_required'}
        except SQLAlchemyError as error:
            report = {'code': 'administrator_recovery_outcome_unknown'
                      if applying and getattr(error,'connection_invalidated',False) else 'administrator_recovery_unavailable'}
        except (ConfigurationError, OSError, ValueError):
            report = {'code': 'administrator_recovery_unavailable'}
        print(json.dumps(report))
        return 0 if report['code'] in {'administrator_recovery_ready','administrator_recovered'} else 1
    if arguments.operation in {'backup', 'restore'}:
        from app.database_backup import BackupError, create_backup, restore_backup
        import psycopg2
        try:
            configuration = load_configuration({'FAMA_CONFIG_DIR': str(Path(arguments.config_dir).resolve())})
            if arguments.operation == 'backup':
                report = create_backup(configuration, arguments.directory, arguments.pg_bin)
            else:
                report = restore_backup(configuration, arguments.backup, arguments.target_url_file, arguments.pg_bin)
        except BackupError as error:
            report = {'code': str(error)}
        except ConfigurationError:
            report = {'code': 'backup_configuration_invalid'}
        except (OSError, ValueError, TypeError, KeyError, psycopg2.Error, subprocess.SubprocessError):
            report = {'code': 'database_backup_operation_failed'}
        print(json.dumps(report))
        return 0 if report['code'] in {'database_backup_created', 'database_restore_verified'} else 1
    if arguments.operation == 'runtime':
        from contextlib import ExitStack
        from app.runtime import RuntimeDirectory
        try:
            selected = Path(arguments.config_dir).resolve()
            configuration = load_configuration({'FAMA_CONFIG_DIR': str(selected)})
            store = RuntimeDirectory(configuration, arguments.directory)
            with ExitStack() as ownership:
                if arguments.directory is not None:
                    from app.runtime import runtime_root
                    old_root = runtime_root(configuration)
                    if old_root is not None and old_root != store.root:
                        ownership.enter_context(RuntimeDirectory(configuration).lease())
                    report = store.prepare()
                    ownership.enter_context(store.lease())
                    InstallationStore(selected).select_runtime(store.root)
                else:
                    report = store.describe()
        except ConfigurationError as error:
            report = {'code': str(error)}
        except (OSError, ValueError):
            report = {'code': 'runtime_configuration_failed'}
        print(json.dumps(report))
        return 0 if report['code'] == 'runtime_ready' else 1
    if arguments.operation == "setup-code":
        from app.installation import InstallationError, issue_authorization
        try:
            directory = Path(arguments.config_dir).resolve()
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            _protect_directory(directory)
            result = issue_authorization(directory, arguments.web_origin)
        except InstallationError as error:
            print(json.dumps({"code": error.code}))
            return 1
        except (OSError, ValueError, ConfigurationError, subprocess.SubprocessError):
            print(json.dumps({"code": "installation_authorization_failed"}))
            return 1
        print(json.dumps(result))
        return 0
    if arguments.operation == "check":
        from app.connections import diagnose
        try:
            report = diagnose(load_configuration({"FAMA_CONFIG_DIR": str(Path(arguments.config_dir).resolve())}))
        except ConfigurationError:
            report = {"configuration": {"ok": False, "code": "configuration_invalid"}}
        print(json.dumps(report))
        return 0 if all(item["ok"] for item in report.values()) else 1
    if arguments.operation == "serve":
        if not 1 <= arguments.port <= 65535:
            parser.error("El puerto debe estar entre 1 y 65535")
        try:
            application = create_node_app(arguments.config_dir)
        except ConfigurationError:
            print(json.dumps({"code": "configuration_invalid"}))
            return 1
        import uvicorn
        uvicorn.run(application, host="127.0.0.1", port=arguments.port)
        return 0
    try:
        code = _prepare(arguments)
    except (OSError, ValueError, ConfigurationError, subprocess.SubprocessError):
        code = "configuration_preparation_failed"
    print(json.dumps({"code": code}))
    return 0 if code == "configuration_prepared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
