"""Read-only publication preflight for one explicit candidate runtime."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import quote

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import normalize_database_url
from app.services.publication_preflight import preflight_publication


class _InvalidArguments(Exception):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise _InvalidArguments(message)


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        description=(
            "Comprueba la publicación de un modelo en el runtime candidato indicado. "
            "No crea esquema, no activa modelos y no modifica la base de datos."
        )
    )
    parser.add_argument("--database-url", required=True,
                        help="URL explícita de la base candidata (PostgreSQL o archivo SQLite existente).")
    parser.add_argument("--checkpoints-root", required=True,
                        help="Raíz explícita de checkpoints del runtime candidato.")
    parser.add_argument("--model-id", required=True,
                        help="ID persistido, por ejemplo fama_trained_model_<id>.")
    parser.add_argument("--expected-sha256", required=True,
                        help="SHA-256 esperado del checkpoint persistido.")
    parser.add_argument("--smoke-audio", metavar="PATH",
                        help="Ejecuta aparte una inferencia pública con este audio controlado.")
    return parser


def _failure(code: str, reason: str) -> dict:
    return {
        "ok": False,
        "model_id": None,
        "expected_sha256": None,
        "code": code,
        "reason": reason,
    }


def _readonly_sqlite_url(url):
    database = url.database
    if not database:
        raise ValueError("SQLite preflight requires an existing file-backed database")

    query = dict(url.query)
    mode = query.get("mode")
    if mode is not None and mode != "ro":
        raise ValueError("SQLite preflight only accepts mode=ro")

    uri = query.get("uri")
    if uri is not None and str(uri).lower() not in {"1", "true", "yes", "on"}:
        raise ValueError("SQLite preflight requires URI support")
    immutable = query.get("immutable")
    if immutable is not None and str(immutable).lower() in {"1", "true", "yes", "on"}:
        raise ValueError("SQLite immutable mode is not supported")

    path = database[5:] if database.startswith("file:") else database
    if not path or path == ":memory:":
        raise ValueError("SQLite preflight requires an existing file-backed database")

    query["mode"] = "ro"
    query["uri"] = "true"
    return url.set(database="file:" + quote(path, safe="/:"), query=query)


def _readonly_preflight(database_url: str, *, model_id: str, expected_sha256: str,
                        checkpoints_root: Path, smoke_audio: Path | None) -> dict:
    engine = None
    try:
        url = make_url(normalize_database_url(database_url))
        if url.get_backend_name() == "sqlite":
            url = _readonly_sqlite_url(url)
        engine = create_engine(url)
        with engine.connect() as connection:
            dialect = connection.dialect.name
            if dialect == "sqlite":
                connection.exec_driver_sql("PRAGMA query_only = ON")
            elif dialect == "postgresql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            else:
                return _failure("unsupported_database", "Solo se admiten PostgreSQL y SQLite en modo de solo lectura.")

            session = Session(bind=connection, autoflush=False, expire_on_commit=False)
            try:
                return preflight_publication(
                    session,
                    model_id=model_id,
                    expected_sha256=expected_sha256,
                    checkpoints_root=checkpoints_root,
                    smoke_audio=smoke_audio,
                )
            finally:
                try:
                    session.rollback()
                except Exception:
                    pass
                try:
                    session.close()
                except Exception:
                    pass
    except Exception:
        return _failure("database_unavailable", "No se pudo abrir el runtime candidato en modo de solo lectura.")
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _InvalidArguments:
        output = _failure("invalid_arguments", "Argumentos incompletos o no válidos; consulte --help.")
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 2

    result = _readonly_preflight(
        args.database_url,
        model_id=args.model_id,
        expected_sha256=args.expected_sha256,
        checkpoints_root=Path(args.checkpoints_root),
        smoke_audio=Path(args.smoke_audio) if args.smoke_audio else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
