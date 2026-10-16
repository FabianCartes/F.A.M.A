"""Explicit offline preparation for supported canonical datasets; no training or promotion."""
import argparse
import json
from pathlib import Path

from training.prepare_data import prepare_dataset


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=("AvesChilenas", "engine_diagnostics"))
    parser.add_argument("--index-csv", required=True, type=Path, help="Explicit canonical source index")
    parser.add_argument("--raw-root", type=Path, help="Existing physical raw audio root")
    parser.add_argument("--processed-root", type=Path, help="Existing physical processed audio root")
    parser.add_argument("--versions-dir", required=True, type=Path,
                        help="Existing physical version store; existing versions are never replaced")
    parser.add_argument("--seed", type=int, default=42, help="Partition seed (default: 42)")
    args = parser.parse_args(argv)
    roots = {stage: root for stage, root in (("raw", args.raw_root), ("processed", args.processed_root))
             if root is not None}
    if not roots:
        parser.error("at least one of --raw-root or --processed-root is required")
    try:
        result = prepare_dataset(args.index_csv, roots=roots, dataset_name=args.dataset,
                                 output_dir=args.versions_dir, random_state=args.seed, versioned=True)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
