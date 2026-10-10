"""Evaluate the served three-component engine ensemble on explicit prepared data.

Example (all paths and component weights are explicit inputs):
  python backend/scripts/evaluate_engine_ensemble.py \
    --prepared-dir /data/prepared/engine_diagnostics --dataset engine_diagnostics \
    --raw-root /data/raw/engine_diagnostics \
    --processed-root /data/processed/engine_diagnostics \
    --resnet-checkpoint /models/resnet/weights.pt \
    --efficientnet-checkpoint /models/efficientnet/weights.pt \
    --panns-checkpoint /models/panns/weights.pt --output /reports/engine-eval.json

This is a local evaluation operation only: it does not train, activate, persist to
DB, publish a bundle, discover defaults, tune weights, or access remote services.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.predictors.engine_ensemble_predictor import EngineEnsemblePredictor
from app.services.recording_evaluator import (
    EVALUATOR_VERSION, LabelledRecording, RecordingEvaluator, validate_recording_splits,
)
from app.schemas.evaluation import strict_json
from dataset_references import resolve_reference
from training.pipelines.multitask_mapping import CLASS_NAMES_13
from training.prepare_data import load_prepared_dataset


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _recordings(frame, split, roots):
    records = []
    for index, row in frame.reset_index(drop=True).iterrows():
        stage, reference, label = str(row["file_stage"]), str(row["file_path"]), str(row["clase"])
        source_id = row.get("source_id")
        identity = f"{label}:{source_id}" if source_id is not None and str(source_id).strip() else f"{stage}:{reference}"
        group_value = row.get("recordist")
        group = None if group_value is None or not str(group_value).strip() else str(group_value)
        records.append(LabelledRecording(
            identity=identity, label=label,
            path=resolve_reference(reference, stage, roots),
            reference=reference, stage=stage, group=group,
        ))
    return tuple(records)


def evaluate_engine_ensemble(*, prepared_dir, dataset, roots, checkpoint_paths, output,
                             predictor_factory=EngineEnsemblePredictor):
    """Evaluate one frozen served predictor over prepared val/test snapshots."""
    if dataset != "engine_diagnostics":
        raise ValueError("Served EngineEnsemblePredictor requires explicit engine_diagnostics dataset")
    if set(checkpoint_paths) != {"resnet", "efficientnet", "panns"}:
        raise ValueError("All three named component checkpoint paths are required")
    splits = load_prepared_dataset(prepared_dir, roots=roots, dataset_name=dataset)
    train_df, val_df, test_df = splits
    classes = set(CLASS_NAMES_13)
    for part in splits:
        if not set(part["clase"]).issubset(classes):
            raise ValueError("Prepared labels are not in the served ensemble class order")
    recordings = {
        name: _recordings(frame, name, roots)
        for name, frame in zip(("train", "val", "test"), splits)
    }
    validate_recording_splits(recordings)
    audio_snapshot = {}
    for split, records in recordings.items():
        audio_snapshot[split] = {}
        for record in records:
            if record.path.is_symlink() or not record.path.is_file():
                raise ValueError("Prepared recording must resolve to a regular, non-symlink audio file")
            audio_snapshot[split][record.identity] = _sha256(record.path)

    def assert_audio_unchanged():
        for split, records in recordings.items():
            for record in records:
                if _sha256(record.path) != audio_snapshot[split][record.identity]:
                    raise ValueError("Prepared recording audio changed during evaluation")

    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Evaluation output already exists: {output}")
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise ValueError("Evaluation output parent must be an existing real directory")

    predictor = predictor_factory(
        checkpoint_paths=checkpoint_paths, device=None, lazy_load=True,
    )
    if list(predictor.classes) != list(CLASS_NAMES_13):
        raise ValueError("Predictor class order does not match the served engine taxonomy")
    predictor.ensure_evaluation_ready()
    assert_audio_unchanged()
    frozen_identity = predictor.evaluation_identity
    reports = {}
    for split in ("val", "test"):
        evaluator = RecordingEvaluator(
            recordings[split], predictor, dataset=dataset, split=split,
            checkpoint_sha256=frozen_identity["checkpoint_sha256"],
            predictor_config=frozen_identity["predictor_config"],
            preprocessing_config=frozen_identity["preprocessing_config"],
            aggregation_config=frozen_identity["aggregation_config"],
        )
        report = evaluator.evaluate()
        assert_audio_unchanged()
        predictor.assert_evaluation_unchanged()
        if predictor.evaluation_identity != frozen_identity:
            raise ValueError("Ensemble identity changed between evaluation splits")
        reports[split] = {
            "provenance": evaluator.identity.model_dump(),
            "report": report,
        }
    assert_audio_unchanged()
    predictor.assert_evaluation_unchanged()
    result = strict_json({
        "operation": "served-engine-ensemble-recording-evaluation-v1",
        "evaluator_version": EVALUATOR_VERSION,
        "dataset": dataset,
        "composite_checkpoint_sha256": frozen_identity["checkpoint_sha256"],
        "component_checkpoints": frozen_identity["components"],
        "classes": list(predictor.classes),
        "reports": reports,
    })
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-dir", required=True, type=Path)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--processed-root", required=True, type=Path)
    parser.add_argument("--resnet-checkpoint", required=True, type=Path)
    parser.add_argument("--efficientnet-checkpoint", required=True, type=Path)
    parser.add_argument("--panns-checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = evaluate_engine_ensemble(
        prepared_dir=args.prepared_dir,
        dataset=args.dataset,
        roots={"raw": args.raw_root, "processed": args.processed_root},
        checkpoint_paths={"resnet": args.resnet_checkpoint,
                          "efficientnet": args.efficientnet_checkpoint,
                          "panns": args.panns_checkpoint},
        output=args.output,
    )
    print(json.dumps({"status": "evaluated", "dataset": result["dataset"],
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
