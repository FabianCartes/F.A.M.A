"""Canonical integrity guard for persisted standard-evaluated artifacts."""
import hashlib
import inspect
import json
from pathlib import Path

import torch
from app.models.training import ModelEvaluation
from app.schemas.evaluation import EvaluationIdentity, validate_report
from app.services.recording_evaluator import EVALUATOR_VERSION


class StandardEvaluationError(ValueError):
    """A standard artifact cannot be safely published or activated."""


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


def _invalid(message="Evaluación estándar incompleta o identidad incompatible."):
    raise StandardEvaluationError(message)


def resolve_training_audio(dataset_name: str, audio_config) -> dict:
    """Rebuild the effective training-audio values from checkpointed inputs."""
    if dataset_name == "engine_diagnostics":
        settings = dict(target_sr=32000, duration_seconds=2.0, n_mels=128,
                        n_fft=1024, hop_length=512, f_min=50.0, f_max=16000.0)
    elif dataset_name == "AvesChilenas":
        settings = dict(target_sr=22050, duration_seconds=5.0, n_mels=128,
                        n_fft=2048, hop_length=512, f_min=800.0, f_max=10000.0)
    else:
        _invalid("Dataset estándar no admitido.")
    if audio_config is None:
        return settings
    if isinstance(audio_config, dict):
        settings.update({key: audio_config.get(key, settings[key]) for key in settings})
    else:
        settings.update({key: getattr(audio_config, key, settings[key]) for key in settings})
    settings["f_min"] = float(settings["f_min"])
    settings["f_max"] = float(settings["f_max"])
    return settings


def build_evaluation_configuration(config: dict, training_audio: dict) -> tuple:
    """Describe the effective published predictor once for training and validation.

    Hashes are intentionally taken from inference implementations, never this builder
    or the guard, so moving the integrity code cannot create a self-hash cycle.
    """
    from poc.preprocess import GPUAudioFrontEnd
    from app.services.predictors import trained_predictor as published_predictor

    signature = inspect.signature(published_predictor.extract_mel_spectrogram)
    mel = {key: signature.parameters[key].default
           for key in ("n_mels", "n_fft", "hop_length", "fmin", "fmax")}
    effective = dict(target_sr=published_predictor.TARGET_SR,
                     duration_seconds=published_predictor.DURATION_SECONDS,
                     n_mels=mel["n_mels"], n_fft=mel["n_fft"], hop_length=mel["hop_length"],
                     f_min=mel["fmin"], f_max=mel["fmax"])
    comparison = {**effective, "f_max": effective["f_max"] or effective["target_sr"] / 2}
    frontend_signature = inspect.signature(GPUAudioFrontEnd)
    training_frontend = {key: frontend_signature.parameters[key].default
                         for key in ("normalize", "top_db")}
    training_frontend["implementation"] = "GPUAudioFrontEnd"
    windowing = config.get("windowing_config")
    mismatch = (any(training_audio.get(key) != value for key, value in comparison.items()) or
                bool(windowing) or training_frontend["normalize"])

    def source_hash(function):
        return hashlib.sha256(inspect.getsource(function).encode()).hexdigest()

    predictor_config = dict(
        implementation="TrainedModelPredictor", version="published-fixed-crop-v1", lazy_load=True,
        implementation_sha256=source_hash(published_predictor.PREDICT_IMPLEMENTATION),
        model_loader_sha256=source_hash(published_predictor.MODEL_LOADER_IMPLEMENTATION),
        architecture=config["architecture"], job_id=config["job_id"], training_mismatch=mismatch,
        runtime_versions=dict(torch=str(torch.__version__), librosa=published_predictor.librosa.__version__,
                              numpy=published_predictor.np.__version__),
        training_config=dict(audio=training_audio, frontend=training_frontend, windowing=windowing))
    preprocessing = dict(
        **effective, mono=True, crop="center", padding="right-zero", mel_power=2.0,
        mel_db_reference="max", normalization="none", silence_rms_threshold=1e-4,
        noise_flatness_threshold=published_predictor.SPECTRAL_FLATNESS_NOISE_THRESHOLD,
        flatness_mask_abs_threshold=1e-4, flatness_mask_min_samples=512,
        load_function_sha256=source_hash(published_predictor.LENGTH_IMPLEMENTATION),
        rms_function_sha256=source_hash(published_predictor.RMS_IMPLEMENTATION),
        mel_function_sha256=source_hash(published_predictor.MEL_IMPLEMENTATION),
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
        _validate_standard_reports(target, db, checkpoints_root)
    except StandardEvaluationError:
        raise
    except Exception:
        _invalid("No se pudieron validar los informes estándar.")


def _validate_standard_reports(target, db, checkpoints_root: Path) -> None:
    """Require a coherent completed val/test pair for the exact trusted artifact.

    Newer failed attempts do not revoke a matching completed pair. Legacy model states
    remain outside this guard. Standard artifacts are read only:
    the checkpoint is hashed and metadata-deserialized on CPU, but no predictor is
    instantiated and no inference/evaluation is run.
    """
    state = target.estado or ""
    if not state.startswith("standard_"):
        return
    if state != "standard_eval_completed":
        _invalid("Modelo nuevo sin evaluación estándar val/test completada; activación/publicación bloqueada.")

    try:
        root = Path(checkpoints_root).resolve(strict=True)
        basename = Path(target.ruta_binario_gcp).name
        if not basename:
            _invalid("Checkpoint estándar ausente.")
        path = root / basename
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            _invalid("Checkpoint estándar fuera del almacenamiento local confiable.")
        checkpoint_hash = checkpoint_sha256(resolved)
        if not target.hash_binario or checkpoint_hash != target.hash_binario:
            _invalid("Checkpoint hash no coincide con la evaluación estándar.")
        payload = torch.load(resolved, map_location="cpu", weights_only=True)
        if checkpoint_sha256(resolved) != checkpoint_hash:
            _invalid("Checkpoint cambió durante comprobación de evaluación estándar.")
    except StandardEvaluationError:
        raise
    except Exception:
        _invalid("No se pudo comprobar el checkpoint estándar.")

    if type(payload) is not dict:
        _invalid("Checkpoint sin metadata de evaluación estándar.")
    job_id = payload.get("job_id")
    classes = payload.get("classes")
    dataset_name = payload.get("dataset_name")
    dataset_id = payload.get("dataset_id")
    architecture = payload.get("architecture")
    if (type(job_id) is not str or not job_id.strip() or type(classes) is not list or not classes or
            any(type(label) is not str or not label.strip() for label in classes) or
            len(set(classes)) != len(classes) or type(dataset_name) is not str or not dataset_name.strip() or
            type(dataset_id) is not int or dataset_id <= 0 or
            type(architecture) is not str or not architecture.strip() or
            "audio_config" not in payload or "windowing_config" not in payload or
            (payload["audio_config"] is not None and type(payload["audio_config"]) is not dict) or
            (payload["windowing_config"] is not None and type(payload["windowing_config"]) is not dict)):
        _invalid("Checkpoint sin identidad estándar válida.")
    if (target.conjunto_datos is None or target.conjunto_datos.nombre != dataset_name or
            target.id_conjunto_datos != dataset_id or target.arquitectura != architecture):
        _invalid("Dataset o arquitectura del checkpoint no coincide con el modelo.")

    try:
        expected_configs = build_evaluation_configuration(
            {"job_id": job_id, "architecture": architecture,
             "windowing_config": payload["windowing_config"]},
            resolve_training_audio(dataset_name, payload["audio_config"]))
        rows = (db.query(ModelEvaluation)
                .filter_by(id_modelo=target.id_modelo)
                .order_by(ModelEvaluation.id_evaluation.desc())
                .all())
    except Exception:
        _invalid("No se pudieron validar las evaluaciones estándar.")

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
                identity.evaluator_version != EVALUATOR_VERSION or
                not _effective_predictor_config_matches(identity.predictor_config, expected_configs[0]) or
                not _json_matches(identity.preprocessing_config, expected_configs[1]) or
                not _json_matches(identity.aggregation_config, expected_configs[2])):
            continue
        candidates[row.split].append(identity)

    if not candidates["val"] or not candidates["test"]:
        _invalid("Falta un par completado para la configuración exacta del checkpoint.")
    for val in candidates["val"]:
        for test in candidates["test"]:
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
                return
    _invalid("No existe un par val/test coherente ligado a una identidad conjunta de manifiestos; "
             "los informes estándar sin esa identidad requieren reevaluación explícita.")
