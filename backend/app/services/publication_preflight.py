"""Read-only publication admission for one explicit candidate model identity."""
import re
from pathlib import Path
from typing import Any, Optional

from app.models.training import Modelo
from app.services.registry import ModelRegistry

_MODEL_ID = re.compile(r"fama_trained_model_([1-9][0-9]{0,9})\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_PUBLICATION_REASONS = {
    "checkpoint_hash_missing": ("checkpoint_hash_missing", "El modelo no tiene un hash SHA-256 persistido."),
    "checkpoint_hash_invalid": ("checkpoint_hash_invalid", "El hash SHA-256 persistido no es válido."),
    "checkpoint_hash_mismatch": ("checkpoint_hash_mismatch", "El checkpoint no coincide con el hash esperado."),
    "checkpoint_missing": ("checkpoint_missing", "No se encontró el checkpoint del modelo en la raíz indicada."),
    "checkpoint_outside_root": ("checkpoint_outside_root", "El checkpoint no pertenece a la raíz indicada."),
    "checkpoint_too_small": ("checkpoint_invalid", "El checkpoint no cumple los requisitos de publicación."),
    "checkpoint_invalid": ("checkpoint_invalid", "El checkpoint no cumple los requisitos de publicación."),
    "checkpoint_unreadable": ("checkpoint_unreadable", "No se pudo leer el checkpoint del modelo."),
    "standard_evaluation_invalid": (
        "standard_evaluation_invalid",
        "El modelo no cumple la guarda de evaluación estándar.",
    ),
}


def _result(ok: bool, model_id: Optional[str], expected_sha256: Optional[str], code: str,
            reason: Optional[str] = None) -> dict:
    result = {
        "ok": ok,
        "model_id": model_id,
        "expected_sha256": expected_sha256,
        "code": code,
    }
    if reason is not None:
        result["reason"] = reason
    return result


def preflight_publication(
    db: Any,
    *,
    model_id: str,
    expected_sha256: str,
    checkpoints_root: Path,
    smoke_audio: Optional[Path] = None,
) -> dict:
    """Validate one persisted model through the registry without writes or activation.

    Publication remains lazy: a passing result confirms persisted identity, checkpoint
    bytes and the existing evaluation guard, but does not prove network construction.
    When ``smoke_audio`` is supplied, real public prediction is a separate required
    second phase and passes only after a classified forward reports the loaded hash.
    """
    match = _MODEL_ID.fullmatch(model_id) if isinstance(model_id, str) else None
    safe_model_id = model_id if match else None
    safe_hash = expected_sha256.lower() if isinstance(expected_sha256, str) and _SHA256.fullmatch(
        expected_sha256
    ) else None
    if (match is None or str(int(match.group(1))) != match.group(1)
            or int(match.group(1)) > 2147483647):
        return _result(False, safe_model_id, safe_hash, "invalid_model_id", "El identificador de modelo no es válido.")
    if safe_hash is None:
        return _result(False, safe_model_id, None, "invalid_expected_sha256", "El SHA-256 esperado no es válido.")

    try:
        model_number = int(match.group(1))
        target = db.query(Modelo).filter(Modelo.id_modelo == model_number).one_or_none()
    except Exception:
        return _result(False, safe_model_id, safe_hash, "database_unavailable", "No se pudo consultar el modelo requerido.")
    if target is None:
        return _result(False, safe_model_id, safe_hash, "model_not_found", "No existe el modelo requerido en la base de datos.")

    persisted_hash = getattr(target, "hash_binario", None)
    if persisted_hash is None or (isinstance(persisted_hash, str) and not persisted_hash.strip()):
        return _result(False, safe_model_id, safe_hash, "checkpoint_hash_missing", "El modelo no tiene un hash SHA-256 persistido.")
    if not isinstance(persisted_hash, str) or not _SHA256.fullmatch(persisted_hash):
        return _result(False, safe_model_id, safe_hash, "checkpoint_hash_invalid", "El hash SHA-256 persistido no es válido.")
    if persisted_hash.lower() != safe_hash:
        return _result(False, safe_model_id, safe_hash, "expected_checkpoint_hash_mismatch", "El SHA-256 esperado no coincide con el registrado para el modelo.")

    try:
        registry = ModelRegistry()
        publication_errors = registry.publish_from_db(db, checkpoints_root=Path(checkpoints_root))
    except Exception:
        return _result(False, safe_model_id, safe_hash, "publication_failed", "No se pudo validar la publicación del modelo.")

    if any(error.get("code") == "database_unavailable" for error in publication_errors):
        return _result(False, safe_model_id, safe_hash, "database_unavailable", "No se pudo consultar el catálogo persistido de modelos.")

    candidate_error = next(
        (error for error in publication_errors if error.get("model_id") == safe_model_id),
        None,
    )
    if candidate_error is not None:
        code, reason = _PUBLICATION_REASONS.get(
            candidate_error.get("code"),
            ("publication_failed", "El modelo requerido no pudo publicarse."),
        )
        return _result(False, safe_model_id, safe_hash, code, reason)

    try:
        predictor = registry.get(safe_model_id)
        metadata = predictor.metadata
    except Exception:
        return _result(False, safe_model_id, safe_hash, "model_not_published", "El modelo requerido no quedó publicado en el runtime candidato.")

    if (getattr(predictor, "expected_checkpoint_sha256", None) != safe_hash or
            getattr(metadata, "checkpoint_sha256", None) != safe_hash):
        return _result(False, safe_model_id, safe_hash, "checkpoint_hash_mismatch", "El checkpoint disponible no coincide con el SHA-256 esperado.")
    if getattr(metadata, "loaded_checkpoint_sha256", None) is not None:
        return _result(False, safe_model_id, safe_hash, "unexpected_network_load", "La publicación inicial no debe cargar la red del modelo.")

    result = _result(True, safe_model_id, safe_hash, "published")
    result["runtime"] = {"validation": "lazy_metadata", "network_loaded": False}
    if smoke_audio is None:
        return result

    try:
        prediction = predictor.predict(Path(smoke_audio))
        details = prediction.detalles if isinstance(prediction.detalles, dict) else {}
        status = details.get("status")
        loaded_hash = getattr(predictor.metadata, "loaded_checkpoint_sha256", None)
        forward_proven = (
            status == "classified"
            and loaded_hash == safe_hash
            and details.get("loaded_checkpoint_sha256") == safe_hash
            and details.get("is_mock") is False
        )
        bounded_status = status if status in {"classified", "noise", "silence"} else "invalid"
    except Exception:
        return _result(False, safe_model_id, safe_hash, "smoke_failed", "La inferencia smoke no se completó correctamente.") | {
            "smoke": {"status": "failed", "forward_proven": False}
        }

    validation = "network_forward" if forward_proven else (
        "checkpoint_loaded_no_forward" if loaded_hash == safe_hash else "lazy_metadata"
    )
    result["runtime"] = {"validation": validation, "network_loaded": loaded_hash == safe_hash}
    result["smoke"] = {"status": bounded_status, "forward_proven": forward_proven}
    if not forward_proven:
        result.update({
            "ok": False,
            "code": "smoke_forward_not_proven",
            "reason": "La señal no demostró una pasada de red clasificada con la identidad esperada.",
        })
    else:
        result["code"] = "smoke_passed"
    return result
