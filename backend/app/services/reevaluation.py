"""Explicit, append-only reevaluation of an existing MAIN checkpoint."""
import hashlib
import json
from pathlib import Path

from app.models.training import Modelo
from app.services.evaluations import EvaluationService
from app.services.recording_evaluator import LabelledRecording, RecordingEvaluator, validate_recording_splits
from app.services.standard_evaluation_guard import (
    ADMITTED_MANIFEST_PAIR_KEY, StandardEvaluationError, admitted_manifest_pair_provenance,
    assert_checkpoint_unchanged, inspect_checkpoint,
)
from dataset_references import resolve_reference
from training.prepare_data import load_prepared_dataset


class ReevaluationError(ValueError):
    """A bounded, path-free failure of explicit reevaluation admission or execution."""


class _PredictorSlot:
    """Delay loading the exact predictor until both durable attempts exist."""
    def __init__(self, classes):
        self.classes = list(classes)
        self.predictor = None

    def predict(self, path):
        if self.predictor is None:
            raise ReevaluationError("Predictor is unavailable during preflight.")
        return self.predictor.predict(path)


def _admit_model(session, *, model_id, checkpoint_root, checkpoint_path, expected_sha256,
                 prepared_dir, dataset_name, roots):
    try:
        if session.new or session.dirty or session.deleted:
            raise ReevaluationError("Session must not contain pending changes.")
        model = (session.query(Modelo).filter_by(id_modelo=model_id)
                 .populate_existing().one_or_none())
        if model is None or model.conjunto_datos is None:
            raise ReevaluationError("Model or explicit dataset identity is unavailable.")
        if model.estado == "standard_component_evaluated":
            raise ReevaluationError("Ensemble component checkpoints are not MAIN models.")
        if model.conjunto_datos.nombre != dataset_name or model.id_conjunto_datos is None:
            raise ReevaluationError("Requested dataset does not match the stored model identity.")
        if not model.hash_binario or model.hash_binario != expected_sha256:
            raise ReevaluationError("Expected checkpoint hash does not match the stored model.")
        inspection = inspect_checkpoint(checkpoint_root, checkpoint_path, expected_sha256,
                                        expected_size=model.tamano_bytes)
        if (Path(model.ruta_binario_gcp).name != inspection.path.name or
                inspection.payload["dataset_name"] != dataset_name or
                inspection.payload["dataset_id"] != model.id_conjunto_datos or
                inspection.payload["architecture"] != model.arquitectura):
            raise ReevaluationError("Checkpoint metadata does not match the stored MAIN model.")
        train, val, test = load_prepared_dataset(
            prepared_dir, roots=roots, dataset_name=dataset_name)
    except ReevaluationError:
        raise
    except StandardEvaluationError:
        raise ReevaluationError("Checkpoint metadata or bytes failed integrity validation.") from None
    except Exception:
        raise ReevaluationError("Prepared source or stored model could not be admitted.") from None

    classes = inspection.payload["classes"]
    frames = {"train": train, "val": val, "test": test}
    if any(set(frame["clase"]) != set(classes) for frame in frames.values()):
        raise ReevaluationError("Prepared split classes do not match the ordered checkpoint classes.")
    recordings = {}
    try:
        for split, frame in frames.items():
            admitted = []
            for row in frame.to_dict("records"):
                path = resolve_reference(row["file_path"], row["file_stage"], roots)
                if dataset_name == "AvesChilenas":
                    identity = row["xc_id"]
                elif "source_id" in row:
                    source_id = row["source_id"]
                    if type(source_id) is not str or not source_id.strip():
                        raise ReevaluationError("Prepared recording source identity is blank.")
                    identity = json.dumps([row["clase"], source_id],
                                          ensure_ascii=False, separators=(",", ":"))
                else:
                    identity = f"{row['file_stage']}:{row['file_path']}"
                admitted.append(LabelledRecording(identity, row["clase"], path,
                                                  row["file_path"], row["file_stage"], row["recordist"]))
            recordings[split] = tuple(admitted)
        validate_recording_splits(recordings)
        configs = inspection.configurations
        predictor_slot = _PredictorSlot(classes)
        evaluators = {
            split: RecordingEvaluator(
                recordings[split], predictor_slot, id_modelo=model_id, dataset=dataset_name,
                split=split, checkpoint_sha256=inspection.sha256,
                predictor_config=configs[0], preprocessing_config=configs[1],
                aggregation_config=configs[2], code_revision=inspection.payload.get("code_revision"))
            for split in ("val", "test")
        }
    except ReevaluationError:
        raise
    except Exception:
        raise ReevaluationError("Prepared recordings failed split, path, or audio admission.") from None

    pair = admitted_manifest_pair_provenance(
        evaluators["val"].identity.manifest_sha256,
        evaluators["test"].identity.manifest_sha256)
    for evaluator in evaluators.values():
        identity = evaluator.identity
        evaluator.identity = type(identity).model_validate({
            **identity.model_dump(),
            "predictor_config": {**identity.predictor_config, ADMITTED_MANIFEST_PAIR_KEY: pair},
        })
    return model, inspection, evaluators, predictor_slot


class _CheckpointGuardedPredictor:
    def __init__(self, predictor, inspection):
        self._predictor = predictor
        self._inspection = inspection
        self.classes = list(predictor.classes)

    def predict(self, path):
        assert_checkpoint_unchanged(self._inspection)
        result = self._predictor.predict(path)
        assert_checkpoint_unchanged(self._inspection)
        return result


def _mark_unfinished_failed(service, attempts, reason):
    for attempt_id in attempts.values():
        try:
            attempt = service.read(attempt_id)
            if attempt is not None and attempt["status"] in ("pending", "running"):
                service.fail(attempt_id, reason)
        except Exception:
            # Preserve any durable outcomes; a failed DB connection may prevent compensation.
            continue


def reevaluate_model(session, *, model_id, checkpoint_root, checkpoint_path, expected_sha256,
                     prepared_dir, dataset_name, roots, execute=False):
    """Preflight by default; with execute=True append val/test attempts and evaluate them.

    The caller owns the SQLAlchemy session. Preflight performs reads only; execution
    uses EvaluationService and never changes model activation or historical metrics.
    """
    if type(execute) is not bool:
        raise ReevaluationError("execute must be an explicit boolean.")
    model, inspection, evaluators, predictor_slot = _admit_model(
        session, model_id=model_id, checkpoint_root=checkpoint_root,
        checkpoint_path=checkpoint_path, expected_sha256=expected_sha256,
        prepared_dir=prepared_dir, dataset_name=dataset_name, roots=roots)
    result = {
        "mode": "execute" if execute else "preflight",
        "model_id": model.id_modelo,
        "dataset": dataset_name,
        "checkpoint_sha256": inspection.sha256,
        "checkpoint_size_bytes": inspection.size_bytes,
        "classes": list(inspection.payload["classes"]),
        "splits": {split: {"sample_count": evaluator.identity.sample_count,
                            "manifest_sha256": evaluator.identity.manifest_sha256}
                   for split, evaluator in evaluators.items()},
    }
    if not execute:
        return result

    from app.services.predictors.trained_predictor import TrainedModelPredictor

    attempts, evaluations = {}, EvaluationService(session)
    phase = "attempt creation"
    try:
        for split in ("val", "test"):
            attempts[split] = evaluations.create(evaluators[split].identity)["id_evaluation"]
        for split in ("val", "test"):
            evaluations.start(attempts[split])
        phase = "checkpoint loading"
        assert_checkpoint_unchanged(inspection)
        predictor = TrainedModelPredictor(
            inspection.path, model_id=f"fama_trained_model_{model.id_modelo}",
            is_default=False, lazy_load=True, dataset_name=dataset_name)
        assert_checkpoint_unchanged(inspection)
        if list(predictor.classes) != list(inspection.payload["classes"]):
            raise ReevaluationError("Loaded predictor class order differs from checkpoint metadata.")
        predictor_slot.predictor = _CheckpointGuardedPredictor(predictor, inspection)
        for split in ("val", "test"):
            phase = f"{split} inference"
            assert_checkpoint_unchanged(inspection)
            final_report = evaluators[split].evaluate()
            assert_checkpoint_unchanged(inspection)
            evaluations.complete(attempts[split], final_report)
    except Exception:
        reason = f"Reevaluation failed during {phase}."
        _mark_unfinished_failed(evaluations, attempts, reason)
        raise ReevaluationError(reason) from None
    result["attempts"] = {
        split: {"id_evaluation": attempt_id, "status": evaluations.read(attempt_id)["status"]}
        for split, attempt_id in attempts.items()
    }
    return result
