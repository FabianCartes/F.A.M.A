"""Engine naming adapter for explicit canonical preparation (not ingestion)."""
from pathlib import Path

from training.paths import get_raw_data_dir
from training.prepare_data import prepare_dataset


def prepare_engine_dataset(source_dir=None, *, index_csv=None, roots=None, output_dir=None,
                           train_ratio=.70, val_ratio=.15, test_ratio=.15, random_state=42):
    """Prepare a supplied index; legacy discovery callers must migrate explicitly.

    source_dir remains a raw-root convenience, never the output destination.
    No discovery, inferred index, overwrite or implicit raw-directory split writes.
    """
    source = Path(source_dir) if source_dir is not None else get_raw_data_dir("engine_diagnostics")
    if roots is None and (not source.is_absolute() or not source.is_dir()
            or any(p.is_symlink() for p in (source, *source.parents))):
        raise ValueError("source_dir must be an existing absolute physical raw root")
    if index_csv is None:
        raise ValueError("Explicit canonical index_csv is required; discovery callers must migrate")
    return prepare_dataset(index_csv, roots=roots if roots is not None else {"raw": source},
                           dataset_name="engine_diagnostics", output_dir=output_dir,
                           train_ratio=train_ratio, val_ratio=val_ratio, test_ratio=test_ratio,
                           random_state=random_state)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-csv", required=True, type=Path)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--processed-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--train-ratio", type=float, default=.70)
    parser.add_argument("--val-ratio", type=float, default=.15)
    parser.add_argument("--test-ratio", type=float, default=.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    roots = {"raw": args.raw_root}
    if args.processed_root is not None:
        roots["processed"] = args.processed_root
    try:
        result = prepare_engine_dataset(index_csv=args.index_csv, roots=roots,
                                        output_dir=args.output_dir, train_ratio=args.train_ratio,
                                        val_ratio=args.val_ratio, test_ratio=args.test_ratio,
                                        random_state=args.seed)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
