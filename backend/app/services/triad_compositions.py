"""Versioned standard-triad compositions: creation, weight revision and lookup.

A composition fuses three independently trained ``Modelo`` rows of one training job.
A weight revision is a new row (``version`` + 1, ``previous_id``); rows are never
edited, and no checkpoint is touched. The unique ``(job_id, version)`` constraint
makes concurrent revisions from the same version fail instead of forking history.
"""
import math
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import exists, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.models.training import Modelo
from app.models.triad_composition import TriadComposition

TRIAD_PREFIX = "fama_triad_"
_WEIGHT_TOLERANCE = 1e-9
_MAX_ID = 2 ** 31 - 1


class TriadCompositionError(ValueError):
    """The requested composition or weights are not admissible."""


class TriadCompositionConflict(Exception):
    """The composition already has a newer version (or another writer revised it first)."""


def triad_model_key(composition_id: int) -> str:
    return f"{TRIAD_PREFIX}{composition_id}"


def parse_triad_key(model_id) -> Optional[int]:
    """Return the composition id of an exact ``fama_triad_<id>`` key, otherwise None."""
    if not isinstance(model_id, str) or not model_id.startswith(TRIAD_PREFIX):
        return None
    suffix = model_id[len(TRIAD_PREFIX):]
    if (not suffix.isascii() or not suffix.isdecimal() or len(suffix) > 10
            or not 1 <= int(suffix) <= _MAX_ID or str(int(suffix)) != suffix):
        return None
    return int(suffix)


def validate_weights(weights: Sequence) -> tuple:
    """Exactly three finite, non-negative numbers summing to one; never normalized."""
    values = tuple(weights) if isinstance(weights, (list, tuple)) else ()
    if (len(values) != 3
            or any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0
                   for w in values)
            or not any(w > 0 for w in values)
            or not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=_WEIGHT_TOLERANCE)):
        raise TriadCompositionError("Se requieren tres pesos no negativos que sumen 1.")
    return tuple(float(w) for w in values)


def component_ids(composition: TriadComposition) -> tuple:
    return (composition.first_model_id, composition.second_model_id, composition.third_model_id)


def component_weights(composition: TriadComposition) -> tuple:
    return (composition.first_weight, composition.second_weight, composition.third_weight)


def composition_query(access):
    """Compositions the caller may use: every one for an administrator, else assigned datasets."""
    query = access.db.query(TriadComposition)
    if access.administrator:
        return query
    return query.filter(TriadComposition.dataset_id.in_(access.ids))


def get_composition(db, composition_id: int) -> Optional[TriadComposition]:
    return db.query(TriadComposition).filter_by(id=composition_id).one_or_none()


def latest_compositions(db) -> list:
    """The highest version of every job; older versions stay stored for traceability."""
    newer = aliased(TriadComposition)
    return (db.query(TriadComposition)
            .filter(~exists().where((newer.job_id == TriadComposition.job_id)
                                    & (newer.version > TriadComposition.version)))
            .order_by(TriadComposition.id).all())


def _latest_version(db, job_id: str) -> int:
    return db.query(func.max(TriadComposition.version)).filter(TriadComposition.job_id == job_id).scalar() or 0


def is_latest(db, composition: TriadComposition) -> bool:
    return composition.version == _latest_version(db, composition.job_id)


def activate_composition(db, composition: TriadComposition) -> TriadComposition:
    """Make the latest version of a composition the single active default model.

    Every ``modelo`` and every other composition is deactivated in the same transaction.
    Raises ``TriadCompositionConflict`` when the composition is not the latest version.
    """
    if not is_latest(db, composition):
        raise TriadCompositionConflict("Solo la última versión de la composición puede activarse.")
    try:
        db.query(Modelo).update({Modelo.activo: False})
        db.query(TriadComposition).update({TriadComposition.activo: False})
        composition.activo = True
        db.commit()
    except Exception:
        db.rollback()
        raise
    return composition


def create_initial_composition(db, *, job_id: str, dataset_id: int, partition_version: Optional[str],
                               components: Sequence, author_id: Optional[int] = None) -> TriadComposition:
    """Register version 1 of a job from its three ordered ``(id_modelo, weight)`` pairs.

    Idempotent per job: an existing version 1 is returned unchanged. Nothing is created
    unless the three models belong to the dataset and carry a valid checkpoint hash.
    """
    from app.services.registry import _persisted_checkpoint_hash

    pairs = list(components)
    if len(pairs) != 3 or len({model_id for model_id, _ in pairs}) != 3:
        raise TriadCompositionError("Una tríada requiere exactamente tres modelos distintos.")
    weights = validate_weights([weight for _, weight in pairs])
    existing = db.query(TriadComposition).filter_by(job_id=job_id, version=1).one_or_none()
    if existing is not None:
        return existing
    rows = {row.id_modelo: row for row in db.query(Modelo).filter(
        Modelo.id_modelo.in_([model_id for model_id, _ in pairs])).all()}
    for model_id, _ in pairs:
        row = rows.get(model_id)
        if row is None or row.id_conjunto_datos != dataset_id:
            raise TriadCompositionError("Los tres modelos deben existir y pertenecer al dataset.")
        if _persisted_checkpoint_hash(row)[1] is not None:
            raise TriadCompositionError("Los tres modelos requieren un hash de checkpoint válido.")
    composition = TriadComposition(
        dataset_id=dataset_id, partition_version=partition_version, job_id=job_id, version=1,
        first_model_id=pairs[0][0], second_model_id=pairs[1][0], third_model_id=pairs[2][0],
        first_weight=weights[0], second_weight=weights[1], third_weight=weights[2],
        author_id=author_id, created_at=datetime.now(timezone.utc))
    db.add(composition)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(TriadComposition).filter_by(job_id=job_id, version=1).one_or_none()
        if existing is None:
            raise
        return existing
    return composition


def revise_weights(db, composition: TriadComposition, weights: Sequence,
                   author_id: Optional[int]) -> TriadComposition:
    """Create the next version of the latest composition with new weights.

    Raises ``TriadCompositionError`` for invalid weights and ``TriadCompositionConflict``
    when the composition is not the latest version or another revision won the race.
    A revision of the active composition becomes the active one.
    """
    new_weights = validate_weights(weights)
    if not is_latest(db, composition):
        raise TriadCompositionConflict("La composición ya tiene una versión más reciente.")
    revision = TriadComposition(
        dataset_id=composition.dataset_id, partition_version=composition.partition_version,
        job_id=composition.job_id, version=composition.version + 1, previous_id=composition.id,
        first_model_id=composition.first_model_id, second_model_id=composition.second_model_id,
        third_model_id=composition.third_model_id,
        first_weight=new_weights[0], second_weight=new_weights[1], third_weight=new_weights[2],
        author_id=author_id, created_at=datetime.now(timezone.utc),
        activo=bool(composition.activo))
    # The default never silently disappears from the catalogue: a revision of the active
    # composition inherits the activation in the same commit, so one entry stays active.
    composition.activo = False
    db.add(revision)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        taken = db.query(TriadComposition).filter_by(
            job_id=composition.job_id, version=composition.version + 1).first() is not None
        if not taken:
            raise  # not the unique-version race: surface the real integrity failure
        raise TriadCompositionConflict("La composición ya tiene una versión más reciente.") from None
    return revision
