"""
Registro centralizado y catálogo de modelos de predicción bioacústica.
Permite registrar y resolver dinámicamente instancias de AudioPredictor en tiempo de ejecución.
"""
from pathlib import Path
from threading import RLock
from urllib.parse import unquote, urlparse
from typing import Dict, List, Optional, Any
from app.schemas.model_info import ModelMetadata
from app.services.predictors.base import AudioPredictor, ModelWeightsError
from training.paths import get_checkpoints_dir


def _verified_dataset_name(dataset, raw_data_root: Optional[Path] = None) -> Optional[str]:
    """Verify a persisted relation against its GCS or canonical local route."""
    from app.services import storage
    if dataset is None:
        return None
    try:
        name = storage.validate_path_component(dataset.nombre)
        route = dataset.ruta_gcp.rstrip("/")
        if route in (f"datasets/{name}", f"gs://{storage.DEFAULT_BUCKET_NAME}/datasets/{name}"):
            return name
        from training.paths import get_raw_data_dir
        raw_root = Path(raw_data_root) if raw_data_root is not None else get_raw_data_dir()
        canonical = raw_root / name
        if (route == canonical.as_uri() and canonical.is_dir()
                and canonical.resolve(strict=True).is_relative_to(raw_root.resolve(strict=True))):
            return name
    except (ValueError, TypeError, AttributeError, OSError, RuntimeError):
        pass
    # Unknown/mismatched associations do not disable inference, only incorporation.
    return None


class ModelNotFoundError(Exception):
    """Excepción lanzada cuando se solicita un modelo no registrado."""
    pass


def _persisted_checkpoint_hash(model) -> tuple[Optional[str], Optional[str]]:
    value = getattr(model, "hash_binario", None)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "checkpoint_hash_missing"
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in value)):
        return None, "checkpoint_hash_invalid"
    return value.lower(), None


class ModelRegistry:
    """
    Catálogo y gestor de ciclo de vida de modelos en memoria.
    """

    def __init__(self, raw_data_root: Optional[Path] = None):
        # Deployment uses the canonical resolver; isolated catalogues can supply
        # their actual filesystem root without replacing internal collaborators.
        self._raw_data_root = raw_data_root
        self._predictors: Dict[str, AudioPredictor] = {}
        # Track provenance, not ID spelling: explicit registrations are not DB-owned.
        self._db_predictors: Dict[str, AudioPredictor] = {}
        self._default_model_id: Optional[str] = None
        self._blocked_db_aliases: Dict[str, str] = {}
        self._blocked_default_error: Optional[str] = None
        self._db_checkpoint_names: set[str] = set()
        self._publication_lock = RLock()

    def register(self, predictor: AudioPredictor, is_default: bool = False) -> None:
        """
        Registra una estrategia predictora en el catálogo.

        Parámetros:
            predictor: Instancia de AudioPredictor.
            is_default: Si es True, designa a este modelo como el fallback por defecto.
        """
        model_id = predictor.model_id
        self._predictors[model_id] = predictor
        if is_default or self._default_model_id is None:
            self.set_default_model(model_id)

    def set_default_model(self, model_id: str) -> None:
        """Establece un modelo registrado como el modelo por defecto y actualiza metadatos."""
        if model_id not in self._predictors:
            raise ModelNotFoundError(
                f"No se puede establecer como default: modelo '{model_id}' no registrado."
            )
        self._default_model_id = model_id
        for pred in set(self._predictors.values()):
            is_def = (pred.model_id == model_id)
            if hasattr(pred, "is_default"):
                pred.is_default = is_def
            if hasattr(pred, "_metadata") and pred._metadata:
                pred._metadata.is_default = is_def


    def get_active_predictor(self) -> AudioPredictor:
        """Retorna el predictor activo actual (modelo por defecto)."""
        return self.get()

    def get(self, model_id: Optional[str] = None) -> AudioPredictor:
        """
        Recupera una estrategia predictora según su ID.
        Si model_id es None o 'default', retorna el modelo por defecto.
        """
        is_default_request = not model_id or model_id == "default"
        if is_default_request and self._blocked_default_error:
            raise ModelWeightsError(self._blocked_default_error)

        target_id = self._default_model_id if is_default_request else model_id
        if target_id:
            blocked_error = self._blocked_db_aliases.get(target_id)
            if blocked_error:
                raise ModelWeightsError(blocked_error)
        if not self._predictors:
            raise ModelNotFoundError("El catálogo de modelos está vacío.")

        if not target_id or target_id not in self._predictors:
            disponibles = list(self._predictors.keys())
            raise ModelNotFoundError(
                f"Modelo '{model_id}' no encontrado en el catálogo. Modelos disponibles: {disponibles}"
            )

        return self._predictors[target_id]

    def list_models(self, only_with_weights: bool = False) -> List[ModelMetadata]:
        """Retorna la lista de metadatos de todos los modelos registrados de forma única."""
        models = []
        seen_ids = set()
        for predictor in self._predictors.values():
            if predictor.model_id in seen_ids:
                continue
            seen_ids.add(predictor.model_id)
            meta = predictor.metadata.model_copy()
            meta.is_default = (predictor.model_id == self._default_model_id)
            meta.has_weights = getattr(predictor, "has_weights", True)
            if only_with_weights and not meta.has_weights:
                continue
            models.append(meta)
        return models

    def unregister(self, model_id: str) -> bool:
        """Elimina un modelo del registro por su ID o alias."""
        removed = False
        keys_to_remove = [k for k, v in self._predictors.items() if k == model_id or v.model_id == model_id]
        for k in keys_to_remove:
            del self._predictors[k]
            removed = True

        if self._default_model_id == model_id:
            self._default_model_id = next(iter(self._predictors.keys()), None)

        return removed

    def get_default_model_id(self) -> Optional[str]:
        """Retorna el identificador del modelo por defecto."""
        return self._default_model_id

    def has_model(self, model_id: str) -> bool:
        """Verifica si un modelo específico está registrado."""
        return model_id in self._predictors

    def _reset_db_identity_errors(self, models: List[Any]) -> None:
        self._blocked_db_aliases = {}
        self._blocked_default_error = None
        self._db_checkpoint_names = set()
        for model in models:
            route = getattr(model, "ruta_binario_gcp", "") or ""
            uri = urlparse(route)
            basename = Path(unquote(uri.path) if uri.scheme else route).name
            if basename:
                self._db_checkpoint_names.add(basename)

    def _block_db_model(self, model: Any, model_id: str, checkpoint_name: str, code: str) -> None:
        self._discard_invalid_standard_predictor(model_id)
        if code == "checkpoint_hash_missing":
            reason = "falta el hash SHA-256 registrado del checkpoint"
        elif code == "checkpoint_hash_invalid":
            reason = "el hash SHA-256 registrado del checkpoint no es válido"
        else:
            reason = "el checkpoint no coincide con el hash SHA-256 registrado"
        message = f"El modelo persistido '{model_id}' está bloqueado: {reason}."
        aliases = {model_id, str(model.id_modelo)}
        if checkpoint_name:
            aliases.update({checkpoint_name, Path(checkpoint_name).stem})
        for alias in aliases:
            self._blocked_db_aliases[alias] = message
        if bool(getattr(model, "activo", False)):
            self._blocked_default_error = message
        if checkpoint_name:
            self._db_checkpoint_names.add(checkpoint_name)

    def _discard_invalid_standard_predictor(self, model_id: str) -> None:
        """Remove a previously published DB predictor and its aliases after identity failure."""
        cached = self._db_predictors.pop(model_id, None)
        removed = []
        for alias, predictor in list(self._predictors.items()):
            if cached is not None and predictor is cached:
                del self._predictors[alias]
                removed.append(alias)
        if self._default_model_id in removed:
            self._default_model_id = None

    def _reconcile_db_models(self, models: List[Any]) -> None:
        """Retire only DB-owned instances absent from a successful DB snapshot.

        Call under the publication lock. Remove every alias of the retired instance,
        but preserve explicit replacements and never select an unrelated fallback.
        """
        persisted_ids = {f"fama_trained_model_{model.id_modelo}" for model in models}
        for model_id, predictor in list(self._db_predictors.items()):
            if model_id in persisted_ids:
                continue
            for alias, registered in list(self._predictors.items()):
                if registered is predictor:
                    del self._predictors[alias]
            if self._default_model_id == model_id and model_id not in self._predictors:
                self._default_model_id = None
            del self._db_predictors[model_id]

    def publish_from_db(
        self, db: Any, checkpoints_root: Optional[Path] = None,
        admitted_pair_ids: Optional[Dict[str, tuple[int, int]]] = None,
    ) -> List[Dict[str, Any]]:
        """Reconcile and publish persisted predictors without activation or DB writes.

        Lazy initialization deserializes metadata once without building inference.
        Failures are returned as public codes; exception text and paths stay private.
        Concurrent catalogue requests cannot replace an already published predictor.
        """
        from app.models.training import Modelo
        from app.services.predictors.trained_predictor import TrainedModelPredictor

        root = Path(checkpoints_root) if checkpoints_root is not None else get_checkpoints_dir()
        errors = []
        with self._publication_lock:
            if admitted_pair_ids is not None:
                admitted_pair_ids.clear()
            try:
                models = db.query(Modelo).order_by(Modelo.id_modelo.desc()).all()
            except Exception:
                return [{"code": "database_unavailable"}]
            from app.services.model_names import model_display_names
            names = model_display_names(models)
            self._reconcile_db_models(models)
            self._reset_db_identity_errors(models)
            for model in models:
                key = f"fama_trained_model_{model.id_modelo}"
                uri = urlparse(model.ruta_binario_gcp)
                basename = Path(unquote(uri.path) if uri.scheme else model.ruta_binario_gcp).name
                expected_hash, hash_error = _persisted_checkpoint_hash(model)
                if hash_error:
                    self._block_db_model(model, key, basename, hash_error)
                    errors.append({"model_id": key, "code": hash_error})
                    continue
                admitted_pair = None
                if str(model.estado or "").startswith("standard_"):
                    try:
                        from app.services.standard_evaluation_guard import (
                            StandardEvaluationError, select_admitted_standard_pair,
                        )
                    except Exception:
                        self._discard_invalid_standard_predictor(key)
                        errors.append({"model_id": key, "code": "standard_evaluation_invalid"})
                        continue
                    try:
                        admitted_pair = select_admitted_standard_pair(model, db, root)
                    except StandardEvaluationError as err:
                        self._discard_invalid_standard_predictor(key)
                        publication_error = {
                            "model_id": key, "code": "standard_evaluation_invalid",
                        }
                        if err.reason is not None:
                            publication_error["reason"] = err.reason.value
                        errors.append(publication_error)
                        continue
                    except Exception:
                        self._discard_invalid_standard_predictor(key)
                        errors.append({"model_id": key, "code": "standard_evaluation_invalid"})
                        continue
                cached = self._db_predictors.get(key)
                if cached is not None:
                    if getattr(cached, "expected_checkpoint_sha256", None) == expected_hash:
                        self._apply_display_name(cached, names[model.id_modelo])
                        if admitted_pair is not None and admitted_pair_ids is not None:
                            admitted_pair_ids[key] = (admitted_pair.val_id, admitted_pair.test_id)
                        continue
                    self._discard_invalid_standard_predictor(key)
                elif self.has_model(key):
                    continue
                code = "checkpoint_unreadable"
                try:
                    physical_root = root.resolve()
                    checkpoint = (physical_root / basename).resolve()
                    if not checkpoint.is_relative_to(physical_root):
                        code = "checkpoint_outside_root"
                        raise ModelWeightsError(code)
                    if not checkpoint.is_file():
                        code = "checkpoint_missing"
                        raise ModelWeightsError(code)
                    if checkpoint.stat().st_size <= 10000:
                        code = "checkpoint_too_small"
                        raise ModelWeightsError(code)
                    # Verify readable storage before asking the ML adapter for metadata.
                    with checkpoint.open("rb") as stream:
                        stream.read(1)
                    code = "checkpoint_invalid"
                    pred = TrainedModelPredictor(
                        checkpoint_path=checkpoint,
                        model_id=key,
                        name=names[model.id_modelo]["name"],
                        is_default=False,
                        lazy_load=True,
                        dataset_name=_verified_dataset_name(model.conjunto_datos, self._raw_data_root),
                        expected_checkpoint_sha256=expected_hash,
                    )
                    self._apply_display_name(pred, names[model.id_modelo])
                    # register() selects a default on an empty catalogue. Publication
                    # deliberately preserves even an unset default instead.
                    self._predictors[key] = pred
                    self._db_predictors[key] = pred
                    for alias in (basename, Path(basename).stem, str(model.id_modelo)):
                        self._predictors.setdefault(alias, pred)
                    if admitted_pair is not None and admitted_pair_ids is not None:
                        admitted_pair_ids[key] = (admitted_pair.val_id, admitted_pair.test_id)
                except Exception as err:
                    if isinstance(err, ModelWeightsError) and "no coincide con el hash SHA-256 registrado" in str(err):
                        self._block_db_model(model, key, basename, "checkpoint_hash_mismatch")
                        code = "checkpoint_hash_mismatch"
                    errors.append({"model_id": key, "code": code})
        return errors

    @staticmethod
    def _apply_display_name(predictor, display):
        predictor.custom_name = display["name"]
        for field, value in display.items():
            setattr(predictor.metadata, field, value)

    def register_from_db(
        self,
        db: Any,
        checkpoints_root: Optional[Path] = None,
    ) -> Optional[AudioPredictor]:
        """
        Sincroniza y registra los modelos entrenados presentes en PostgreSQL.
        Busca los modelos ordenados de forma descendente, asocia sus checkpoints y
        marca como default el modelo activo.
        """
        if checkpoints_root is None:
            checkpoints_root = get_checkpoints_dir()
        else:
            checkpoints_root = Path(checkpoints_root)

        from app.models.training import Modelo
        from app.services.predictors.trained_predictor import TrainedModelPredictor

        with self._publication_lock:
            db_models = db.query(Modelo).order_by(Modelo.id_modelo.desc()).all()
            from app.services.model_names import model_display_names
            names = model_display_names(db_models)
            self._reconcile_db_models(db_models)
            self._reset_db_identity_errors(db_models)
            active_predictor = None

            for m in db_models:
                model_key = f"fama_trained_model_{m.id_modelo}"
                uri = urlparse(m.ruta_binario_gcp)
                ckpt_name = Path(unquote(uri.path) if uri.scheme else m.ruta_binario_gcp).name
                expected_hash, hash_error = _persisted_checkpoint_hash(m)
                if hash_error:
                    self._block_db_model(m, model_key, ckpt_name, hash_error)
                    continue

                candidate_paths = [
                    checkpoints_root / ckpt_name,
                    checkpoints_root.parent / "checkpoints" / ckpt_name,
                ]
                ckpt_file = next((path for path in candidate_paths if path.exists()), None)
                is_standard = str(getattr(m, "estado", "") or "").startswith("standard_")
                if is_standard:
                    try:
                        from app.services.standard_evaluation_guard import require_standard_reports
                        require_standard_reports(m, db, ckpt_file.parent if ckpt_file else checkpoints_root)
                    except Exception:
                        self._discard_invalid_standard_predictor(model_key)
                        continue

                is_active = bool(m.activo)
                cached = self._db_predictors.get(model_key)
                if cached is not None:
                    if getattr(cached, "expected_checkpoint_sha256", None) == expected_hash:
                        self._apply_display_name(cached, names[m.id_modelo])
                        if is_active:
                            active_predictor = cached
                            self.set_default_model(model_key)
                        continue
                    self._discard_invalid_standard_predictor(model_key)

                # Solo registrar si el archivo existe físicamente y contiene pesos reales (> 10KB).
                if ckpt_file and ckpt_file.stat().st_size > 10000:
                    try:
                        pred = TrainedModelPredictor(
                            checkpoint_path=ckpt_file,
                            model_id=model_key,
                            name=names[m.id_modelo]["name"],
                            is_default=is_active,
                            lazy_load=not is_active,
                            dataset_name=_verified_dataset_name(m.conjunto_datos, self._raw_data_root),
                            expected_checkpoint_sha256=expected_hash,
                        )
                        self._apply_display_name(pred, names[m.id_modelo])
                        self._predictors[model_key] = pred
                        self._db_predictors[model_key] = pred
                        # Registrar alias útiles para consultas directas.
                        self._predictors[ckpt_file.name] = pred
                        self._predictors[ckpt_file.stem] = pred
                        self._predictors[str(m.id_modelo)] = pred

                        if is_active:
                            active_predictor = pred
                            self.set_default_model(model_key)
                    except Exception as err:
                        if isinstance(err, ModelWeightsError) and "no coincide con el hash SHA-256 registrado" in str(err):
                            self._block_db_model(m, model_key, ckpt_name, "checkpoint_hash_mismatch")
                        elif not is_standard:
                            print(f"[ModelRegistry] Advertencia al registrar modelo #{m.id_modelo} ({ckpt_name}): {err}")
                        else:
                            self._discard_invalid_standard_predictor(model_key)

            return active_predictor


def discover_and_register_checkpoints(
    registry: ModelRegistry,
    checkpoints_root: Optional[Path] = None,
    db: Optional[Any] = None,
) -> int:
    """
    Descubre y registra modelos entrenados binarios (.pt).
    1. Si hay base de datos disponible, sincroniza mediante register_from_db.
    2. Si no se estableció un modelo por defecto tras la DB, escanea checkpoints_root
       buscando fama_*_best.pt mayores a 1MB y los registra.
    """
    if checkpoints_root is None:
        checkpoints_root = get_checkpoints_dir()
    checkpoints_root = Path(checkpoints_root)

    count = 0
    active_found = False

    # 1. Intentar sincronización con Base de Datos
    if db is not None:
        try:
            active_pred = registry.register_from_db(db, checkpoints_root=checkpoints_root)
            if active_pred is not None:
                active_found = True
                count += 1
        except Exception as db_err:
            print(f"[ModelRegistry] Advertencia al sincronizar con BD: {db_err}")
    else:
        try:
            from app.database import SessionLocal
            session = SessionLocal()
            try:
                active_pred = registry.register_from_db(session, checkpoints_root=checkpoints_root)
                if active_pred is not None:
                    active_found = True
                    count += 1
            finally:
                session.close()
        except Exception:
            pass

    # 2. Respaldo por escaneo directo en checkpoints/
    if not active_found and checkpoints_root.exists() and checkpoints_root.is_dir():
        from app.services.predictors.trained_predictor import TrainedModelPredictor
        fama_checkpoints = sorted(
            [p for p in checkpoints_root.glob("fama_*_best.pt")
             if p.is_file() and p.stat().st_size > 1000000
             and p.name not in registry._db_checkpoint_names],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for ckpt in fama_checkpoints:
            try:
                is_def = (not active_found)
                pred = TrainedModelPredictor(
                    checkpoint_path=ckpt,
                    model_id=ckpt.stem,
                    name=f"Modelo Entrenado ({ckpt.stem})",
                    is_default=is_def,
                    lazy_load=not is_def,
                )
                registry.register(pred, is_default=is_def)
                count += 1
                if not active_found:
                    active_found = True
                    registry.set_default_model(ckpt.stem)
            except Exception as err:
                print(f"[ModelRegistry] Error al registrar checkpoint {ckpt}: {err}")

    return count


def discover_and_register_bundles(registry: ModelRegistry, checkpoints_root: Optional[Path] = None) -> int:
    """
    Escanea subdirectorios en checkpoints_root buscando manifest.json válidos
    y los registra automáticamente como BundleAudioPredictor.
    """
    if checkpoints_root is None:
        checkpoints_root = get_checkpoints_dir()

    checkpoints_root = Path(checkpoints_root)
    if not checkpoints_root.exists() or not checkpoints_root.is_dir():
        return 0

    from app.services.predictors.bundle_predictor import BundleAudioPredictor
    count = 0
    for child in checkpoints_root.iterdir():
        if child.is_dir() and (child / "manifest.json").exists():
            try:
                predictor = BundleAudioPredictor(bundle_dir=child, lazy_load=True)
                registry.register(predictor, is_default=predictor.metadata.is_default)
                count += 1
            except Exception as err:
                print(f"[ModelRegistry] Advertencia: omitiendo bundle en {child}: {err}")

    return count


def build_default_registry() -> ModelRegistry:
    """Construye el catálogo desde declaraciones de instalación y modelos SQL.

    Sin declaración no se añaden ensambles ni se descubren archivos. El default
    declarado es el inicial; una activación SQL posterior conserva su prioridad.
    /api/models reintenta la publicación desde BD si falla la conexión de arranque.
    """
    from app.configuration import declared_ensembles, get_configuration
    from app.database import SessionLocal

    reg = ModelRegistry()
    enabled, default = declared_ensembles(get_configuration().values)
    for model_id in enabled:
        if model_id == "chilean-birds-ensemble":
            from app.services.predictors.ensemble_predictor import ChileanBirdsEnsemblePredictor
            predictor = ChileanBirdsEnsemblePredictor(lazy_load=True)
        else:
            from app.services.predictors.engine_ensemble_predictor import EngineEnsemblePredictor
            predictor = EngineEnsemblePredictor(lazy_load=True)
        reg.register(predictor, is_default=(model_id == default))

    try:
        with SessionLocal() as db:
            reg.register_from_db(db)
    except Exception:
        # The HTTP catalogue reports database availability through publish_from_db.
        pass
    return reg


_global_model_registry: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """Proveedor de dependencias para FastAPI (Dependency Injection)."""
    global _global_model_registry
    if _global_model_registry is None:
        _global_model_registry = build_default_registry()
    return _global_model_registry


def set_global_model_registry(registry: Optional[ModelRegistry]) -> None:
    """Permite sobrescribir el registro global para propósitos de prueba."""
    global _global_model_registry
    _global_model_registry = registry
