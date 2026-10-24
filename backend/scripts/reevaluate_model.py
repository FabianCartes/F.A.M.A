"""Explicit preflight or append-only reevaluation of one existing MAIN checkpoint.

Preflight is read-only. Add --execute only after reviewing its checkpoint, dataset,
and split snapshot summary; every argument, including DATABASE_URL, is explicit.
"""
import argparse
import json


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--model-id", required=True, type=int)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--prepared-dir", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--root", action="append", required=True, metavar="STAGE=PATH",
                        help="Explicit audio root; provide raw=PATH and processed=PATH")
    parser.add_argument("--execute", action="store_true",
                        help="Persist new val/test attempts and run inference")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    roots = {}
    for declaration in args.root:
        stage, separator, path = declaration.partition("=")
        if not separator or stage not in {"raw", "processed"} or not path or stage in roots:
            _parser().error("--root must declare each of raw and processed exactly once")
        roots[stage] = path
    if set(roots) != {"raw", "processed"}:
        _parser().error("--root must declare both raw and processed")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = None
    reevaluation_error = None
    try:
        from app.services.reevaluation import ReevaluationError, reevaluate_model
        reevaluation_error = ReevaluationError
        engine = create_engine(args.database_url, pool_pre_ping=True)
        sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with sessions() as session:
            result = reevaluate_model(
                session, model_id=args.model_id, checkpoint_root=args.checkpoint_root,
                checkpoint_path=args.checkpoint, expected_sha256=args.expected_sha256,
                prepared_dir=args.prepared_dir, dataset_name=args.dataset, roots=roots,
                execute=args.execute)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except Exception as error:
        if reevaluation_error is not None and isinstance(error, reevaluation_error):
            message = str(error)[:2000]
        else:
            message = "Database or reevaluation operation failed."
        print(json.dumps({"status": "failed", "error": message}, ensure_ascii=False))
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
