"""Read-only, batched view of persisted final evaluations for catalogue models."""
from dataclasses import dataclass
import re
from typing import Dict, Iterable, Optional

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.models.training import ModelEvaluation
from app.models.triad_composition import TriadCompositionEvaluation
from app.schemas.evaluation import (
    EvaluationIdentity, EvaluationProvenance, TriadEvaluationIdentity, validate_report,
)
from app.schemas.model_info import (
    CompletedEvaluationSummary,
    EvaluationAttemptSummary,
    EvaluationSplitSummary,
    ModelEvaluations,
)


_DB_MODEL_ID = re.compile(r"fama_trained_model_([1-9][0-9]*)\Z")
_MAX_MODEL_ID = 2_147_483_647


@dataclass(frozen=True)
class EvaluationCatalogueRead:
    """Read result keeps a missing table distinct from a valid empty catalogue."""
    by_model_id: Dict[str, ModelEvaluations]
    error_code: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.error_code is None


def _registered_db_ids(metadata: Iterable[object]):
    """Resolve only the exact ID spelling emitted by DB-backed registry entries."""
    parsed = {}
    for item in metadata:
        match = _DB_MODEL_ID.fullmatch(item.id)
        if match is None:
            continue
        model_id = int(match.group(1))
        if model_id <= _MAX_MODEL_ID and str(model_id) == match.group(1):
            parsed[model_id] = item.id
    return parsed


def _registered_triad_ids(metadata: Iterable[object]):
    """Composition ids of the exact ``fama_triad_<id>`` keys published by the registry."""
    from app.services.triad_compositions import parse_triad_key
    return {composition_id: item.id for item in metadata
            if (composition_id := parse_triad_key(item.id)) is not None}


_PROVENANCE_FIELDS = (
    "schema_version", "evaluator_version", "checkpoint_sha256", "dataset",
    "split", "manifest_sha256", "classes", "predictor_config",
    "preprocessing_config", "aggregation_config", "sample_count", "code_revision",
)


def _triad_evaluations(session, metadata):
    """Newest joint attempt and newest completed report per split of each published triad.

    Only stored attempts of the exact composition are read; inference never runs. As for
    individual models, failure reasons are never exposed by the catalogue.
    """
    triad_ids = _registered_triad_ids(metadata)
    if not triad_ids:
        return {}
    rows = (session.query(TriadCompositionEvaluation)
            .filter(TriadCompositionEvaluation.composition_id.in_(tuple(sorted(triad_ids))))
            .order_by(TriadCompositionEvaluation.composition_id.asc(),
                      TriadCompositionEvaluation.split.asc(),
                      TriadCompositionEvaluation.id.desc())
            .all())
    grouped = {}
    for row in rows:
        values = {name: getattr(row, name) for name in _PROVENANCE_FIELDS}
        provenance = EvaluationProvenance.model_validate(values)
        bucket = grouped.setdefault(triad_ids[row.composition_id], {}).setdefault(row.split, {
            "latest_attempt": None, "latest_completed": None, "admitted_completed": None,
        })
        if bucket["latest_attempt"] is None:
            bucket["latest_attempt"] = EvaluationAttemptSummary(
                id_evaluation=row.id, status=row.status, provenance=provenance,
                created_at=row.created_at, started_at=row.started_at, finished_at=row.finished_at,
            )
        if row.status == "completed" and bucket["latest_completed"] is None:
            identity = TriadEvaluationIdentity.model_validate({
                **values, "composition_id": row.composition_id,
                "composition_version": row.composition_version,
                "component_model_ids": row.component_model_ids,
                "checkpoint_sha256s": row.checkpoint_sha256s, "weights": row.weights,
            })
            bucket["latest_completed"] = CompletedEvaluationSummary(
                id_evaluation=row.id, provenance=provenance,
                report=validate_report(row.report, identity), created_at=row.created_at,
                started_at=row.started_at, finished_at=row.finished_at,
            )
    return {slug: ModelEvaluations(**{split: EvaluationSplitSummary(**values)
                                      for split, values in splits.items()})
            for slug, splits in grouped.items()}


def _provenance(row):
    values = {
        name: getattr(row, name)
        for name in (
            "schema_version", "evaluator_version", "checkpoint_sha256", "dataset",
            "split", "manifest_sha256", "classes", "predictor_config",
            "preprocessing_config", "aggregation_config", "sample_count", "code_revision",
        )
    }
    identity = EvaluationIdentity.model_validate({**values, "id_modelo": row.id_modelo})
    return EvaluationProvenance.model_validate(values), identity


def read_model_evaluations(
    session, metadata: Iterable[object],
    admitted_pair_ids: Optional[Dict[str, tuple[int, int]]] = None,
) -> EvaluationCatalogueRead:
    """Read all matching attempts in ordered queries; never infer or mutate models.

    ``metadata`` contains the model entries actually returned by the registry. Only
    its documented ``fama_trained_model_<positive integer>`` and ``fama_triad_<id>``
    IDs participate; static predictors and generic ensembles are never associated by
    name guessing. A triad reads the joint attempts of its exact composition.
    """
    metadata = list(metadata)
    db_ids = _registered_db_ids(metadata)
    admitted_pair_ids = admitted_pair_ids or {}
    admitted_by_split = {
        slug: {"val": pair[0], "test": pair[1]}
        for slug, pair in admitted_pair_ids.items() if slug in db_ids.values()
    }
    try:
        rows = (
            session.query(ModelEvaluation)
            .filter(ModelEvaluation.id_modelo.in_(tuple(sorted(db_ids))))
            .order_by(
                ModelEvaluation.id_modelo.asc(),
                ModelEvaluation.split.asc(),
                ModelEvaluation.id_evaluation.desc(),
            )
            .all()
        )
        grouped = {}
        for row in rows:
            provenance, identity = _provenance(row)
            slug = db_ids.get(row.id_modelo)
            admitted_id = admitted_by_split.get(slug, {}).get(row.split)
            bucket = grouped.setdefault((row.id_modelo, row.split), {
                "latest_attempt": None, "latest_completed": None, "admitted_completed": None,
            })
            if bucket["latest_attempt"] is None:
                bucket["latest_attempt"] = EvaluationAttemptSummary(
                    id_evaluation=row.id_evaluation, status=row.status,
                    provenance=provenance, created_at=row.created_at,
                    started_at=row.started_at, finished_at=row.finished_at,
                )
            if row.status == "completed":
                report = validate_report(row.report, identity)
                if bucket["latest_completed"] is None:
                    bucket["latest_completed"] = CompletedEvaluationSummary(
                        id_evaluation=row.id_evaluation, provenance=provenance,
                        report=report, created_at=row.created_at,
                        started_at=row.started_at, finished_at=row.finished_at,
                    )
                if row.id_evaluation == admitted_id:
                    bucket["admitted_completed"] = CompletedEvaluationSummary(
                        id_evaluation=row.id_evaluation, provenance=provenance,
                        report=report, created_at=row.created_at,
                        started_at=row.started_at, finished_at=row.finished_at,
                    )

        grouped_by_model = {}
        for (model_id, split), values in grouped.items():
            slug = db_ids.get(model_id)
            if slug is None:
                continue
            grouped_by_model.setdefault(slug, {})[split] = values

        result = {}
        for slug, splits in grouped_by_model.items():
            selected = admitted_by_split.get(slug)
            if selected is not None:
                pair_found = all(
                    splits.get(split, {}).get("admitted_completed") is not None
                    and splits[split]["admitted_completed"].id_evaluation == evaluation_id
                    for split, evaluation_id in selected.items()
                )
                if not pair_found:
                    for values in splits.values():
                        values["admitted_completed"] = None
            result[slug] = {
                split: EvaluationSplitSummary(**values) for split, values in splits.items()
            }
        evaluations = {slug: ModelEvaluations(**result[slug]) for slug in result}
        evaluations.update(_triad_evaluations(session, metadata))
        return EvaluationCatalogueRead(evaluations)
    except SQLAlchemyError:
        return EvaluationCatalogueRead({}, "evaluation_store_unavailable")
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
        return EvaluationCatalogueRead({}, "evaluation_records_invalid")
