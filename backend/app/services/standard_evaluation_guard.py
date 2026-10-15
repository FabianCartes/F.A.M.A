"""Canonical integrity guard for persisted standard-evaluated artifacts."""
from dataclasses import dataclass
from enum import Enum
import hashlib
import inspect
import json
from pathlib import Path

import torch
from app.models.training import ModelEvaluation
from app.schemas.evaluation import EvaluationIdentity, validate_report
from app.services.recording_evaluator import EVALUATOR_VERSION
from poc.preprocess import (
    GPUAudioFrontEnd, build_gpu_audio_frontend_contract,
    validate_gpu_audio_frontend_contract,
)


class StandardEvaluationReason(str, Enum):
    """Bounded public categories for known standard-evaluation failures."""

    RUNTIME_CONFIGURATION_INCOMPATIBLE = "runtime_configuration_incompatible"
    EVALUATION_PAIR_INCOMPLETE = "evaluation_pair_incomplete"
    CHECKPOINT_INVALID = "checkpoint_invalid"
    PAIR_PROVENANCE_INVALID = "pair_provenance_invalid"
    MODEL_STATE_INCOMPLETE = "model_state_incomplete"


class StandardEvaluationError(ValueError):
    """A standard artifact cannot be safely published or activated."""

    def __init__(self, message: str, *, reason: StandardEvaluationReason | None = None):
        super().__init__(message)
        self.reason = reason


ADMITTED_MANIFEST_PAIR_KEY = "admitted_val_test_manifest_pair"
ADMITTED_MANIFEST_PAIR_VERSION = 1
_ADMITTED_MANIFEST_PAIR_DOMAIN = "fama.standard-evaluation.admitted-val-test-manifest-pair"


def admitted_manifest_pair_provenance(val_manifest_sha256: str, test_manifest_sha256: str) -> dict:
    """Return the versioned digest shared by both reports for one admitted split pair."""
    hashes = (val_manifest_sha256, test_manifest_sha256)
    if any(type(value) is not str or len(value) != 64 or
           any(char not in "0123456789abcdef" for char in value) for value in hashes):
        raise ValueError("Manifest pair requires two lowercase SHA-256 digests")
    canonical_identity = {
        "domain": _ADMITTED_MANIFEST_PAIR_DOMAIN,
        "version": ADMITTED_MANIFEST_PAIR_VERSION,
        "val_manifest_sha256": val_manifest_sha256,
        "test_manifest_sha256": test_manifest_sha256,
    }
    canonical = json.dumps(canonical_identity, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"version": ADMITTED_MANIFEST_PAIR_VERSION,
            "sha256": hashlib.sha256(canonical).hexdigest()}


def checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_signature(path):
    info = Path(path).stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class CheckpointInspection:
    path: Path
    sha256: str
    size_bytes: int
    signature: tuple
    payload: dict
    configurations: tuple


@dataclass(frozen=True)
class AdmittedStandardEvaluationPair:
    """Path-free identities for the exact completed pair accepted by the guard."""
    val_id: int
    val_identity: EvaluationIdentity
    test_id: int
    test_identity: EvaluationIdentity


def inspect_checkpoint(checkpoints_root, checkpoint_path, expected_sha256, *, expected_size=None):
    """Safely inspect explicit checkpoint bytes and require complete MAIN provenance."""
    try:
        root = Path(checkpoints_root).resolve(strict=True)
        path = Path(checkpoint_path).resolve(strict=True)
        if (not root.is_dir() or not path.is_relative_to(root) or not path.is_file() or
                type(expected_sha256) is not str or len(expected_sha256) != 64 or
                any(char not in "0123456789abcdef" for char in expected_sha256)):
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Checkpoint fuera de la raíz confiable o hash inválido.")
        before = _file_signature(path)
        if before[2] <= 0 or expected_size is not None and expected_size > 0 and before[2] != expected_size:
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Tamaño de checkpoint no coincide con la identidad esperada.")
        digest = checkpoint_sha256(path)
        if digest != expected_sha256:
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Checkpoint hash no coincide con la identidad esperada.")
        try:
            payload = torch.load(path, map_location="cpu", weights_only=True)
        except Exception:
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "No se pudo leer el checkpoint estándar.")
        after = _file_signature(path)
        if before != after or checkpoint_sha256(path) != digest:
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Checkpoint cambió durante su inspección.")
        if type(payload) is not dict:
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Checkpoint sin metadata de evaluación MAIN.")
        job_id, classes = payload.get("job_id"), payload.get("classes")
        dataset_name, dataset_id = payload.get("dataset_name"), payload.get("dataset_id")
        architecture = payload.get("architecture")
        if (type(job_id) is not str or not job_id.strip() or type(classes) is not list or not classes or
                any(type(label) is not str or not label.strip() for label in classes) or
                len(set(classes)) != len(classes) or type(dataset_name) is not str or not dataset_name.strip() or
                type(dataset_id) is not int or dataset_id <= 0 or
                type(architecture) is not str or not architecture.strip() or
                "audio_config" not in payload or "windowing_config" not in payload or
                (payload["audio_config"] is not None and type(payload["audio_config"]) is not dict) or
                (payload["windowing_config"] is not None and type(payload["windowing_config"]) is not dict)):
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Checkpoint sin identidad estándar válida.")
        training_audio = resolve_training_audio(dataset_name, payload["audio_config"])
        try:
            preprocessing_contract = validate_gpu_audio_frontend_contract(
                payload.get("preprocessing_contract"))
        except ValueError:
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Checkpoint sin contrato de preprocessing GPU válido.")
        expected_contract = build_gpu_audio_frontend_contract(
            sample_rate=training_audio["target_sr"],
            duration_seconds=training_audio["duration_seconds"],
            n_mels=training_audio["n_mels"], n_fft=training_audio["n_fft"],
            hop_length=training_audio["hop_length"], f_min=training_audio["f_min"],
            f_max=training_audio["f_max"],
            top_db=preprocessing_contract["parameters"]["top_db"],
            normalize=preprocessing_contract["parameters"]["normalize"])
        acoustic_fields = ("n_mels", "n_fft", "hop_length", "f_min", "f_max")
        contract_parameters = preprocessing_contract["parameters"]
        expected_parameters = expected_contract["parameters"]
        acoustic_mismatch = (
            preprocessing_contract["sample_rate"] != expected_contract["sample_rate"] or
            preprocessing_contract["duration_seconds"] != expected_contract["duration_seconds"] or
            any(contract_parameters[key] != expected_parameters[key] for key in acoustic_fields))
        if acoustic_mismatch:
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Checkpoint frontend contract differs from its effective training audio settings.")
        configurations = build_evaluation_configuration(
            {"job_id": job_id, "architecture": architecture,
             "windowing_config": payload["windowing_config"]},
            training_audio, preprocessing_contract)
        return CheckpointInspection(path, digest, before[2], before, payload, configurations)
    except StandardEvaluationError:
        raise
    except OSError:
        raise StandardEvaluationError(
            "No se pudo leer el checkpoint estándar.",
            reason=StandardEvaluationReason.CHECKPOINT_INVALID,
        ) from None
    except Exception:
        raise StandardEvaluationError("No se pudo comprobar el checkpoint estándar.") from None


def assert_checkpoint_unchanged(inspection):
    """Fail closed if the admitted file was replaced or changed after inspection."""
    try:
        if (_file_signature(inspection.path) != inspection.signature or
                checkpoint_sha256(inspection.path) != inspection.sha256 or
                _file_signature(inspection.path) != inspection.signature):
            _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                     "Checkpoint cambió durante la evaluación.")
    except StandardEvaluationError:
        raise
    except OSError:
        raise StandardEvaluationError(
            "No se pudo comprobar el checkpoint durante la evaluación.",
            reason=StandardEvaluationReason.CHECKPOINT_INVALID,
        ) from None
    except Exception:
        raise StandardEvaluationError("No se pudo comprobar el checkpoint durante la evaluación.") from None


def _invalid(reason: StandardEvaluationReason, message: str) -> None:
    raise StandardEvaluationError(message, reason=reason)


def resolve_training_audio(dataset_name: str, audio_config) -> dict:
    """Rebuild the effective training-audio values from checkpointed inputs."""
    if dataset_name == "engine_diagnostics":
        settings = dict(target_sr=32000, duration_seconds=2.0, n_mels=128,
                        n_fft=1024, hop_length=512, f_min=50.0, f_max=16000.0)
    elif dataset_name == "AvesChilenas":
        settings = dict(target_sr=22050, duration_seconds=5.0, n_mels=128,
                        n_fft=2048, hop_length=512, f_min=800.0, f_max=10000.0)
    else:
        _invalid(StandardEvaluationReason.RUNTIME_CONFIGURATION_INCOMPATIBLE,
                 "Dataset estándar no admitido.")
    if audio_config is None:
        return settings
    if isinstance(audio_config, dict):
        settings.update({key: audio_config.get(key, settings[key]) for key in settings})
    else:
        settings.update({key: getattr(audio_config, key, settings[key]) for key in settings})
    settings["f_min"] = float(settings["f_min"])
    settings["f_max"] = float(settings["f_max"])
    return settings


def build_evaluation_configuration(config: dict, training_audio: dict,
                                   preprocessing_contract=None) -> tuple:
    """Describe the effective published predictor once for training and validation.

    Hashes are intentionally taken from inference implementations, never this builder
    or the guard, so moving the integrity code cannot create a self-hash cycle.
    """
    from app.services.predictors import trained_predictor as published_predictor

    if preprocessing_contract is None:
        preprocessing_contract = build_gpu_audio_frontend_contract(
            sample_rate=training_audio["target_sr"],
            duration_seconds=training_audio["duration_seconds"],
            n_mels=training_audio["n_mels"], n_fft=training_audio["n_fft"],
            hop_length=training_audio["hop_length"], f_min=training_audio["f_min"],
            f_max=training_audio["f_max"])
    preprocessing_contract = validate_gpu_audio_frontend_contract(preprocessing_contract)
    frontend_params = preprocessing_contract["parameters"]
    effective = dict(
        target_sr=preprocessing_contract["sample_rate"],
        duration_seconds=preprocessing_contract["duration_seconds"],
        n_mels=frontend_params["n_mels"], n_fft=frontend_params["n_fft"],
        hop_length=frontend_params["hop_length"], f_min=frontend_params["f_min"],
        f_max=frontend_params["f_max"])
    comparison = dict(effective)
    training_frontend = {
        "implementation": "GPUAudioFrontEnd",
        "version": preprocessing_contract["version"],
        "normalize": frontend_params["normalize"],
        "top_db": frontend_params["top_db"],
    }
    windowing = config.get("windowing_config")
    mismatch = (any(training_audio.get(key) != value for key, value in comparison.items()) or
                bool(windowing))

    def source_hash(function):
        return hashlib.sha256(inspect.getsource(function).encode()).hexdigest()

    predictor_config = dict(
        implementation="TrainedModelPredictor", version="gpu-audio-frontend-v1", lazy_load=True,
        implementation_sha256=source_hash(published_predictor.PREDICT_IMPLEMENTATION),
        model_loader_sha256=source_hash(published_predictor.MODEL_LOADER_IMPLEMENTATION),
        architecture=config["architecture"], job_id=config["job_id"], training_mismatch=mismatch,
        runtime_versions=dict(torch=str(torch.__version__), librosa=published_predictor.librosa.__version__,
                              numpy=published_predictor.np.__version__),
        training_config=dict(audio=training_audio, frontend=training_frontend, windowing=windowing))
    preprocessing = dict(
        **effective, mono=True, crop="center", padding="right-zero", mel_power=2.0,
        mel_db_reference=1.0, silence_rms_threshold=1e-4,
        noise_flatness_threshold=published_predictor.SPECTRAL_FLATNESS_NOISE_THRESHOLD,
        flatness_mask_abs_threshold=1e-4, flatness_mask_min_samples=512,
        normalization=("per-example-zscore" if frontend_params["normalize"] else "none"),
        frontend_contract=preprocessing_contract,
        load_function_sha256=source_hash(published_predictor.LENGTH_IMPLEMENTATION),
        rms_function_sha256=source_hash(published_predictor.RMS_IMPLEMENTATION),
        mel_function_sha256=source_hash(GPUAudioFrontEnd.forward),
        resampling=inspect.signature(published_predictor.librosa.load).parameters["res_type"].default,
        flatness_defaults={key: parameter.default for key, parameter in
                           inspect.signature(published_predictor.librosa.feature.spectral_flatness).parameters.items()
                           if key not in {"y", "S"}})
    aggregation = dict(unit="recording", predictions_per_recording=1, windowing="fixed-center-crop",
                       decision="softmax-argmax", rejection_statuses=["silence", "noise"])
    return predictor_config, preprocessing, aggregation


def _json_matches(actual, expected) -> bool:
    return json.dumps(actual, sort_keys=True, separators=(",", ":"), allow_nan=False) == json.dumps(
        expected, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _effective_predictor_config_matches(actual, expected) -> bool:
    if type(actual) is not dict:
        return False
    effective = dict(actual)
    effective.pop(ADMITTED_MANIFEST_PAIR_KEY, None)
    return _json_matches(effective, expected)


def require_standard_reports(target, db, checkpoints_root: Path) -> None:
    """Validate standard artifacts and expose only bounded, path-free errors."""
    try:
        select_admitted_standard_pair(target, db, checkpoints_root)
    except StandardEvaluationError:
        raise
    except Exception:
        raise StandardEvaluationError("No se pudieron validar los informes estándar.") from None


def select_admitted_standard_pair(
    target, db, checkpoints_root: Path,
) -> AdmittedStandardEvaluationPair | None:
    """Return the exact coherent val/test pair admitted for a standard artifact.

    Non-standard legacy states have no guard-selected pair and return ``None``.
    Newer failed attempts do not revoke a matching completed pair. Standard artifacts
    are read only: checkpoint metadata is deserialized on CPU without instantiating a
    predictor or running inference/evaluation. Returned identities are path-free.
    """
    state = target.estado or ""
    if not state.startswith("standard_"):
        return None
    if state != "standard_eval_completed":
        _invalid(StandardEvaluationReason.MODEL_STATE_INCOMPLETE,
                 "Modelo nuevo sin evaluación estándar val/test completada; activación/publicación bloqueada.")

    try:
        root = Path(checkpoints_root).resolve(strict=True)
        basename = Path(target.ruta_binario_gcp).name
    except OSError:
        _invalid(StandardEvaluationReason.CHECKPOINT_INVALID, "No se pudo resolver el checkpoint estándar.")
    if not basename or not target.hash_binario:
        _invalid(StandardEvaluationReason.CHECKPOINT_INVALID, "Checkpoint estándar ausente.")
    inspection = inspect_checkpoint(root, root / basename, target.hash_binario,
                                    expected_size=target.tamano_bytes)
    payload = inspection.payload
    checkpoint_hash = inspection.sha256
    job_id, classes = payload["job_id"], payload["classes"]
    dataset_name, dataset_id = payload["dataset_name"], payload["dataset_id"]
    architecture = payload["architecture"]
    if (target.conjunto_datos is None or target.conjunto_datos.nombre != dataset_name or
            target.id_conjunto_datos != dataset_id or target.arquitectura != architecture):
        _invalid(StandardEvaluationReason.CHECKPOINT_INVALID,
                 "Dataset o arquitectura del checkpoint no coincide con el modelo.")

    try:
        expected_configs = inspection.configurations
        rows = (db.query(ModelEvaluation)
                .filter_by(id_modelo=target.id_modelo)
                .order_by(ModelEvaluation.id_evaluation.desc())
                .all())
    except Exception:
        raise StandardEvaluationError("No se pudieron validar las evaluaciones estándar.") from None

    matching_identity = {"val": [], "test": []}
    candidates = {"val": [], "test": []}
    for row in rows:
        if row.split not in candidates or row.status != "completed":
            continue
        try:
            identity = EvaluationIdentity.model_validate({
                field: getattr(row, field) for field in EvaluationIdentity.model_fields
            })
            validate_report(row.report, identity)
        except Exception:
            continue
        if (identity.id_modelo != target.id_modelo or identity.split != row.split or
                identity.checkpoint_sha256 != checkpoint_hash or identity.dataset != dataset_name or
                identity.classes != classes or identity.schema_version != 2 or
                identity.evaluator_version != EVALUATOR_VERSION):
            continue
        matching_identity[row.split].append(identity)
        if (_effective_predictor_config_matches(identity.predictor_config, expected_configs[0]) and
                _json_matches(identity.preprocessing_config, expected_configs[1]) and
                _json_matches(identity.aggregation_config, expected_configs[2])):
            candidates[row.split].append((identity, row.id_evaluation))

    if not matching_identity["val"] or not matching_identity["test"]:
        _invalid(StandardEvaluationReason.EVALUATION_PAIR_INCOMPLETE,
                 "Falta un par completado para la identidad del checkpoint.")
    if not candidates["val"] or not candidates["test"]:
        _invalid(StandardEvaluationReason.RUNTIME_CONFIGURATION_INCOMPATIBLE,
                 "Los informes completados no corresponden a la configuración efectiva del predictor.")
    for val, val_id in candidates["val"]:
        for test, test_id in candidates["test"]:
            try:
                expected_pair = admitted_manifest_pair_provenance(
                    val.manifest_sha256, test.manifest_sha256)
            except ValueError:
                continue
            if (not _json_matches(val.predictor_config.get(ADMITTED_MANIFEST_PAIR_KEY), expected_pair) or
                    not _json_matches(test.predictor_config.get(ADMITTED_MANIFEST_PAIR_KEY), expected_pair)):
                continue
            if all(_json_matches(getattr(val, field), getattr(test, field)) for field in (
                "checkpoint_sha256", "dataset", "classes", "schema_version", "evaluator_version",
                "predictor_config", "preprocessing_config", "aggregation_config", "code_revision",
            )):
                return AdmittedStandardEvaluationPair(
                    val_id=val_id, val_identity=val, test_id=test_id, test_identity=test)
    _invalid(StandardEvaluationReason.PAIR_PROVENANCE_INVALID,
             "No existe un par val/test coherente ligado a una identidad conjunta de manifiestos; "
             "los informes estándar sin esa identidad requieren reevaluación explícita.")
