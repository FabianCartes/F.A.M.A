"""Execute one durable attempt, or watch explicitly local-only or sync-only jobs."""
import argparse
import json
import math
import signal
import threading


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="FAMA_IMPORT_STORAGE_PROFILE optionally selects an existing physical JSON profile; no activation or migration.")
    parser.add_argument("--database-url", required=True, help="Explicit migrated database; no ambient URL or migration.")
    parser.add_argument("--import-root", required=True, help="Existing private physical absolute import root shared with the API.")
    parser.add_argument("--staging-root", required=True, help="Existing private attempt root, stable across restarts, on the same filesystem.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cleanup-only", action="store_true",
                      help="Reclaim eligible staging only; no execution jobs, HTTP work or cloud operations.")
    mode.add_argument("--local-only", action="store_true",
                      help="Claim preview/confirm only, leaving queued and expired sync jobs unchanged; no cloud storage.")
    mode.add_argument("--sync-only", action="store_true",
                      help="Claim sync only, leaving queued and expired preview/confirm jobs unchanged; requires explicit GCS configuration.")
    parser.add_argument("--watch", action="store_true",
                        help="Supervise local-only or sync-only attempts in this foreground process; SIGINT/SIGTERM stop after the current attempt.")
    parser.add_argument("--poll-seconds", type=float,
                        help="Wait between watch attempts, including idle polls (finite 1–3600 seconds; default 2).")
    parser.add_argument("--execution-seconds", type=float,
                        help="Per-attempt cooperative execution bound in seconds (finite >0 and <=3600; default 1800). Does not change the lease, validator or HTTP timeout.")
    args = parser.parse_args(argv)
    if args.watch and not (args.local_only or args.sync_only):
        parser.error("--watch requires --local-only or --sync-only")
    if args.poll_seconds is not None and (not args.watch or not math.isfinite(args.poll_seconds)
                                          or not 1 <= args.poll_seconds <= 3600):
        parser.error("--poll-seconds requires --watch and a finite value between 1 and 3600")
    if args.execution_seconds is not None:
        if not math.isfinite(args.execution_seconds) or not 0 < args.execution_seconds <= 3600:
            parser.error("--execution-seconds requires a finite value greater than 0 and at most 3600")
        if args.cleanup_only:
            parser.error("--execution-seconds is not supported with --cleanup-only")
    interval = args.poll_seconds if args.poll_seconds is not None else 2
    engine = None
    handlers = {}
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import normalize_database_url
        from app.services.dataset_import_execution import ImportExecution
        from app.services.dataset_import_jobs import ImportJobQueue
        from app.services.dataset_import_worker import _private_root
        from app.services.dataset_storage_runtime import runtime_import_service

        root, staging = _private_root(args.import_root), _private_root(args.staging_root)
        if root.stat().st_dev != staging.stat().st_dev:
            raise ValueError("Publication requires the same filesystem")
        service = runtime_import_service(root, attempt_root=staging)
        engine = create_engine(normalize_database_url(args.database_url))
        allowed_kinds = ("preview", "confirm") if args.local_only else ("sync",) if args.sync_only else None
        queue = ImportJobQueue(sessionmaker(bind=engine), allowed_kinds=allowed_kinds)
        if args.cleanup_only:
            with queue.sessions() as db:
                result = service.cleanup(db, attempt_root=staging)
        else:
            storage = None
            if not args.local_only:
                from app.services.dataset_import_storage import GCSImportStorage
                storage = GCSImportStorage()
            options = {"execution_seconds": args.execution_seconds} if args.execution_seconds is not None else {}
            execution = ImportExecution(queue, service, staging, storage=storage, **options)
            stop = threading.Event() if args.watch else None
            if stop is not None:
                for number in (signal.SIGINT, signal.SIGTERM):
                    handlers[number] = signal.signal(number, lambda *_: stop.set())
            while True:
                result = {"claimed": execution.run_once()}
                if args.watch:
                    print(json.dumps(result), flush=True)
                if stop is None or stop.wait(interval):
                    break
    except Exception:
        # Connection/driver/paths may contain secrets. Domain errors live in job state.
        parser.exit(1, "Import worker unavailable; preserve state and inspect the operation manual.\n")
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
        if engine is not None:
            engine.dispose()
    if not args.watch:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
