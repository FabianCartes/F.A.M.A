"""Read-only, batched view of persisted final evaluations for catalogue models."""
from dataclasses import dataclass
import re
from typing import Dict, Iterable, Optional

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.models.training import ModelEvaluation
from app.schemas.evaluation import EvaluationIdentity, EvaluationProvenance, validate_report
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


def read_model_evaluations(session, metadata: Iterable[object]) -> EvaluationCatalogueRead:
    """Read all matching attempts in one ordered query; never infer or mutate models.

    ``metadata`` contains the model entries actually returned by the registry. Only
    its documented ``fama_trained_model_<positive integer>`` IDs participate; static
    predictors and generic ensembles are never associated by name guessing.
    """
    db_ids = _registered_db_ids(metadata)
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
            bucket = grouped.setdefault((row.id_modelo, row.split), {
                "latest_attempt": None, "latest_completed": None,
            })
            if bucket["latest_attempt"] is None:
                bucket["latest_attempt"] = EvaluationAttemptSummary(
                    id_evaluation=row.id_evaluation, status=row.status,
                    provenance=provenance, created_at=row.created_at,
                    started_at=row.started_at, finished_at=row.finished_at,
                )
            if row.status == "completed" and bucket["latest_completed"] is None:
                report = validate_report(row.report, identity)
                bucket["latest_completed"] = CompletedEvaluationSummary(
                    id_evaluation=row.id_evaluation, provenance=provenance,
                    report=report, created_at=row.created_at,
                    started_at=row.started_at, finished_at=row.finished_at,
                )

        result = {}
        for (model_id, split), values in grouped.items():
            slug = db_ids.get(model_id)
            if slug is None:
                continue
            per_model = result.setdefault(slug, {})
            per_model[split] = EvaluationSplitSummary(**values)
        return EvaluationCatalogueRead({
            slug: ModelEvaluations(**result[slug]) for slug in result
        })
    except SQLAlchemyError:
        return EvaluationCatalogueRead({}, "evaluation_store_unavailable")
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
        return EvaluationCatalogueRead({}, "evaluation_records_invalid")
