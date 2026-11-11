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

    def __init__(self, raw_data_root: Optional[Path] = None, *, triad_records=None):
        # Deployment uses the canonical resolver; isolated catalogues can supply
        # their actual filesystem root without replacing internal collaborators.
        self._raw_data_root = raw_data_root
        self.triad_records = triad_records
        self._predictors: Dict[str, AudioPredictor] = {}
        # Track provenance, not ID spelling: explicit registrations are not DB-owned.
        self._db_predictors: Dict[str, AudioPredictor] = {}
        # Latest standard triad compositions, keyed ``fama_triad_<id>``; derived from the
        # component entries of ``_db_predictors`` and never persisted by the registry.
        self._triad_predictors: Dict[str, AudioPredictor] = {}
        self._default_model_id: Optional[str] = None
        self._blocked_db_aliases: Dict[str, str] = {}
        self._blocked_default_error: Optional[str] = None
        self._db_checkpoint_names: set[str] = set()
        self._publication_lock = RLock()
        self._imported_owners: Dict[str, int] = {}
        self._private_aliases: set[str] = set()

    def _is_triad(self, model):
        key = f"fama_trained_model_{model.id_modelo}"
        return (getattr(model, 'arquitectura', None) == 'ImportedTriad'
                or str(getattr(model, 'estado', None) or '').startswith('imported_triad_')
                or getattr(self._db_predictors.get(key), 'composition_admission', None) is not None)

    def _hide_model_aliases(self, model):
        route = urlparse(model.ruta_binario_gcp)
        basename = Path(unquote(route.path) if route.scheme else model.ruta_binario_gcp).name
        self._private_aliases.update({f"fama_trained_model_{model.id_modelo}",
                                     str(model.id_modelo), basename, Path(basename).stem})

    def _visible(self, predictor, owner_id=None):
        owner = self._imported_owners.get(predictor.model_id)
        return owner is None or (type(owner_id) is int and owner_id > 0 and owner_id == owner)

    def _legacy_rejection_identity(self, model, root, expected_hash, source_owner):
        """Prove a public legacy identity for rejection only, never publication."""
        key = f"fama_trained_model_{model.id_modelo}"
        cached = self._db_predictors.get(key)
        if (source_owner is not None or key in self._imported_owners or
                getattr(cached, "imported_source", None) is not None):
            return False
        dataset_id = getattr(model, "id_conjunto_datos", None)
        dataset = model.conjunto_datos
        if (type(dataset_id) is int and dataset_id > 0 and dataset is not None and
                dataset.id_conjunto_datos == dataset_id):
            return True
        if str(getattr(model, 'estado', None) or '').startswith('standard_'):
            from app.services.standard_evaluation_guard import inspect_checkpoint
            route = urlparse(model.ruta_binario_gcp)
            basename = Path(unquote(route.path) if route.scheme else model.ruta_binario_gcp).name
            try:
                inspection = inspect_checkpoint(root, Path(root) / basename, expected_hash)
            except Exception:
                return False
            return inspection.payload.get('imported_source') is None
        return False

    def _metadata_candidate(self, model, root, display, expected_hash):
        """Classify through the ML adapter only after root/hash verification.

        A checkpoint marker can deny publication, never authorize an owner.
        Reuse validated cached metadata or the fresh lazy candidate at publication.
        """
        from app.services.checkpoint_digest import file_sha256
        from app.services.predictors.trained_predictor import TrainedModelPredictor
        route = urlparse(model.ruta_binario_gcp)
        basename = Path(unquote(route.path) if route.scheme else model.ruta_binario_gcp).name
        physical_root = Path(root).resolve()
        checkpoint = (physical_root / basename).resolve()
        if not checkpoint.is_relative_to(physical_root):
            raise ModelWeightsError("checkpoint_outside_root")
        if not checkpoint.is_file():
            raise ModelWeightsError("checkpoint_missing")
        if checkpoint.stat().st_size <= 10000:
            raise ModelWeightsError("checkpoint_too_small")
        if file_sha256(checkpoint) != expected_hash:
            raise ModelWeightsError("checkpoint_hash_mismatch")
        key = f"fama_trained_model_{model.id_modelo}"
        cached = self._db_predictors.get(key)
        if cached is not None and cached.expected_checkpoint_sha256 == expected_hash:
            return cached
        return TrainedModelPredictor(
            checkpoint_path=checkpoint, model_id=key, name=display["name"],
            is_default=False, lazy_load=True,
            dataset_name=_verified_dataset_name(model.conjunto_datos, self._raw_data_root),
            expected_checkpoint_sha256=expected_hash,
        )

    def prewarm_from_db(self, db: Any, checkpoints_root: Optional[Path] = None) -> int:
        """Cache standard checkpoint metadata without publishing or loading inference.

        Returns an aggregate failure count. Publication still verifies checkpoint
        identity and evaluation reports. No database writes are performed.
        """
        from app.models.training import Modelo
        from app.services.model_names import model_display_names

        root = (Path(checkpoints_root) if checkpoints_root is not None else
                Path(__file__).resolve().parent.parent.parent / "checkpoints")
        failures = 0
        with self._publication_lock:
            models = db.query(Modelo).order_by(Modelo.id_modelo.desc()).all()
            names = model_display_names(models)
            for model in models:
                try:
                    if self._is_triad(model):
                        continue
                    expected_hash, error = _persisted_checkpoint_hash(model)
                    if error:
                        failures += 1
                        continue
                    candidate = self._metadata_candidate(
                        model, root, names[model.id_modelo], expected_hash)
                    self._db_predictors[candidate.model_id] = candidate
                except Exception:
                    failures += 1
        return failures

    def _hide_unknown_identity(self, model):
        self._hide_model_aliases(model)
        self._discard_invalid_standard_predictor(f"fama_trained_model_{model.id_modelo}")
        if bool(model.activo):
            self._blocked_default_error = "Modelo persistido no disponible."

    def register(self, predictor: AudioPredictor, is_default: bool = False) -> None:
        """
        Registra una estrategia predictora en el catálogo.

        Parámetros:
            predictor: Instancia de AudioPredictor.
            is_default: Si es True, designa a este modelo como el fallback por defecto.
        """
        model_id = predictor.model_id
        if (getattr(predictor, "composition_admission", None) is not None
                or type(predictor).__name__ == "ImportedTriadPredictor"
                or model_id in self._imported_owners
                or getattr(predictor, "imported_source", None) is not None):
            raise ValueError("Imported predictors are not supported by the standard registry")
        self._predictors[model_id] = predictor
        if is_default or self._default_model_id is None:
            self.set_default_model(model_id)

    def set_default_model(self, model_id: str) -> None:
        """Establece un modelo registrado como el modelo por defecto y actualiza metadatos."""
        if model_id in self._predictors and self._predictors[model_id].model_id in self._imported_owners:
            raise ValueError("Imported models cannot be global defaults")
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

    def get(self, model_id: Optional[str] = None, *, owner_id=None) -> AudioPredictor:
        """
        Recupera una estrategia predictora según su ID.
        Si model_id es None o 'default', retorna el modelo por defecto.
        """
        is_default_request = not model_id or model_id == "default"
        if is_default_request and self._blocked_default_error:
            raise ModelWeightsError(self._blocked_default_error)

        target_id = self._default_model_id if is_default_request else model_id
        if target_id in self._private_aliases and target_id not in self._predictors:
            raise ModelNotFoundError("Modelo no disponible.")
        if target_id in self._predictors and not self._visible(self._predictors[target_id], owner_id):
            raise ModelNotFoundError("Modelo no disponible.")
        if target_id:
            blocked_error = self._blocked_db_aliases.get(target_id)
            if blocked_error:
                raise ModelWeightsError(blocked_error)
        if not self._predictors:
            raise ModelNotFoundError("El catálogo de modelos está vacío.")

        if not target_id or target_id not in self._predictors:
            disponibles = [alias for alias, pred in self._predictors.items()
                           if self._visible(pred)]
            raise ModelNotFoundError(
                f"Modelo '{model_id}' no encontrado en el catálogo. Modelos disponibles: {disponibles}"
            )

        return self._predictors[target_id]

    def list_models(self, only_with_weights: bool = False, *, owner_id=None, private_only: bool = False) -> List[ModelMetadata]:
        """Retorna la lista de metadatos de todos los modelos registrados de forma única."""
        models = []
        seen_ids = set()
        for predictor in self._predictors.values():
            if private_only and (type(owner_id) is not int or owner_id <= 0 or
                                 self._imported_owners.get(predictor.model_id) != owner_id):
                continue
            if not self._visible(predictor, owner_id):
                continue
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
            self._default_model_id = next(
                (key for key, pred in self._predictors.items() if self._visible(pred)), None
            )

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
        *, owner_id=None, access=None,
    ) -> List[Dict[str, Any]]:
        """Reconcile and publish persisted predictors without activation or DB writes.

        Lazy initialization deserializes metadata once without building inference.
        Failures are returned as public codes; exception text and paths stay private.
        Concurrent catalogue requests cannot replace an already published predictor.
        """
        from app.models.training import Modelo

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
                if access is not None and not access.administrator and model.id_conjunto_datos not in access.ids:
                    continue
                if self._is_triad(model):
                    self._discard_invalid_standard_predictor(key)
                    continue
                source_owner = None
                uri = urlparse(model.ruta_binario_gcp)
                basename = Path(unquote(uri.path) if uri.scheme else model.ruta_binario_gcp).name
                expected_hash, hash_error = _persisted_checkpoint_hash(model)
                if hash_error:
                    if (source_owner is None and not self._legacy_rejection_identity(
                            model, root, expected_hash, source_owner)):
                        self._hide_unknown_identity(model)
                        continue
                    self._block_db_model(model, key, basename, hash_error)
                    errors.append({"model_id": key, "code": hash_error})
                    continue
                cached = self._db_predictors.get(key)
                if (cached is not None and self.has_model(key) and source_owner is None and
                        not str(getattr(model, 'estado', None) or "").startswith("standard_") and
                        key not in self._imported_owners and
                        getattr(cached, "imported_source", None) is None and
                        cached.expected_checkpoint_sha256 == expected_hash and
                        not any(alias in self._private_aliases for alias, predictor
                                in self._predictors.items() if predictor is cached)):
                    # Previously published public legacy metadata is observational:
                    # expose current digest/availability without loading weights.
                    self._apply_display_name(cached, names[model.id_modelo])
                    continue
                try:
                    pred = self._metadata_candidate(model, root, names[model.id_modelo], expected_hash)
                except Exception as err:
                    verified_legacy = self._legacy_rejection_identity(model, root, expected_hash, source_owner)
                    self._discard_invalid_standard_predictor(key)
                    if source_owner is None and not verified_legacy:
                        self._hide_unknown_identity(model)
                        continue
                    code = str(err) if str(err) in {
                        "checkpoint_outside_root", "checkpoint_missing", "checkpoint_too_small",
                        "checkpoint_hash_mismatch",
                    } else ("checkpoint_unreadable" if isinstance(err, PermissionError) else "checkpoint_invalid")
                    if bool(model.activo):
                        self._blocked_default_error = "Modelo persistido no disponible."
                    if verified_legacy and str(getattr(model, 'estado', None) or "").startswith("standard_"):
                        # Preserve rejection precedence, never guard success as
                        # permission to publish a predictor the adapter rejected.
                        publication_error = {"model_id": key, "code": "standard_evaluation_invalid"}
                        try:
                            from app.services.standard_evaluation_guard import (
                                StandardEvaluationError, select_admitted_standard_pair,
                            )
                        except Exception:
                            errors.append(publication_error)
                            continue
                        try:
                            select_admitted_standard_pair(model, db, root)
                        except StandardEvaluationError as guard_error:
                            if guard_error.reason is not None:
                                publication_error["reason"] = guard_error.reason.value
                            errors.append(publication_error)
                            continue
                        except Exception:
                            errors.append(publication_error)
                            continue
                    if code == "checkpoint_hash_mismatch":
                        self._block_db_model(model, key, basename, code)
                    errors.append({"model_id": key, "code": code})
                    continue
                if getattr(pred, "imported_source", None) is not None and source_owner is None:
                    self._hide_unknown_identity(model)
                    continue
                admitted_pair = None
                if source_owner is not None or str(getattr(model, 'estado', None) or "").startswith("standard_"):
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
                if cached is not None and self.has_model(key):
                    if getattr(cached, "expected_checkpoint_sha256", None) == expected_hash:
                        self._apply_display_name(cached, names[model.id_modelo])
                        if admitted_pair is not None and admitted_pair_ids is not None:
                            admitted_pair_ids[key] = (admitted_pair.val_id, admitted_pair.test_id)
                        continue
                    self._discard_invalid_standard_predictor(key)
                elif self.has_model(key):
                    continue
                code = "checkpoint_invalid"
                try:
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
            self._publish_triads(db, access, errors)
        return errors

    def _discard_triad(self, key: str) -> None:
        predictor = self._triad_predictors.pop(key, None)
        if predictor is not None and self._predictors.get(key) is predictor:
            del self._predictors[key]
        if self._default_model_id == key and key not in self._predictors:
            self._default_model_id = None

    def _publish_triads(self, db: Any, access: Any, errors: List[Dict[str, Any]]) -> None:
        """Publish the latest composition of each job as one metadata-only model.

        Call under the publication lock after the individual models. Components are the
        already published, lazily loaded predictors, so hash caching is shared. A composition
        whose component is blocked or unavailable is blocked as well; older versions are not
        listed. Without the composition table, individual models are unaffected.
        """
        from app.services.predictors.triad_predictor import TriadPredictor
        from app.services.triad_compositions import component_ids, component_weights, latest_compositions, triad_model_key
        try:
            compositions = latest_compositions(db)
        except Exception:
            db.rollback()
            errors.append({"model_id": "fama_triad", "code": "triad_compositions_unavailable"})
            return
        latest_keys = {triad_model_key(composition.id) for composition in compositions}
        for key in [key for key in self._triad_predictors if key not in latest_keys]:
            self._discard_triad(key)
        for composition in compositions:
            key = triad_model_key(composition.id)
            if access is not None and not access.administrator and composition.dataset_id not in access.ids:
                continue
            keys = [f"fama_trained_model_{model_id}" for model_id in component_ids(composition)]
            components = [self._db_predictors.get(component_key) for component_key in keys]
            if any(component_key in self._blocked_db_aliases for component_key in keys) or None in components:
                self._discard_triad(key)
                self._blocked_db_aliases[key] = (
                    f"La composición '{key}' está bloqueada: un componente no está disponible o su hash no es válido.")
                errors.append({"model_id": key, "code": "triad_component_blocked"})
                continue
            cached = self._triad_predictors.get(key)
            if cached is not None and self.has_model(key) and cached.components == tuple(components):
                continue  # Composition rows are immutable; the same components keep the same fusion.
            try:
                dataset_names = {component.dataset_name for component in components}
                if len(dataset_names) != 1:
                    raise ModelWeightsError("Component datasets do not match")
                predictor = TriadPredictor(
                    components, component_weights(composition), list(components[0].classes), key,
                    name=f"Tríada combinada (versión {composition.version})", dataset_name=dataset_names.pop())
            except Exception:
                self._discard_triad(key)
                errors.append({"model_id": key, "code": "triad_invalid"})
                continue
            self._discard_triad(key)
            self._predictors[key] = predictor
            self._triad_predictors[key] = predictor

    @staticmethod
    def _apply_display_name(predictor, display):
        predictor.custom_name = display["name"]
        metadata = predictor.metadata
        for field, value in display.items():
            setattr(metadata, field, value)

    def register_from_db(
        self,
        db: Any,
        checkpoints_root: Optional[Path] = None,
        *, metadata_only: bool = False,
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

        with self._publication_lock:
            db_models = db.query(Modelo).order_by(Modelo.id_modelo.desc()).all()
            from app.services.model_names import model_display_names
            names = model_display_names(db_models)
            self._reconcile_db_models(db_models)
            self._reset_db_identity_errors(db_models)
            active_predictor = None

            for m in db_models:
                model_key = f"fama_trained_model_{m.id_modelo}"
                if self._is_triad(m):
                    self._hide_model_aliases(m)
                    self._imported_owners[model_key] = m.id_usuario or -1
                    continue
                has_sources = True
                uri = urlparse(m.ruta_binario_gcp)
                ckpt_name = Path(unquote(uri.path) if uri.scheme else m.ruta_binario_gcp).name
                expected_hash, hash_error = _persisted_checkpoint_hash(m)
                if hash_error:
                    if not has_sources:
                        self._hide_unknown_identity(m)
                        continue
                    self._block_db_model(m, model_key, ckpt_name, hash_error)
                    continue

                candidate_paths = [
                    checkpoints_root / ckpt_name,
                    checkpoints_root.parent / "checkpoints" / ckpt_name,
                ]
                ckpt_file = next((path for path in candidate_paths if path.exists()), None)
                try:
                    pred = self._metadata_candidate(m, ckpt_file.parent if ckpt_file else checkpoints_root,
                                                    names[m.id_modelo], expected_hash)
                except Exception as err:
                    self._discard_invalid_standard_predictor(model_key)
                    if not has_sources:
                        self._hide_unknown_identity(m)
                    elif str(err) == "checkpoint_hash_mismatch":
                        self._block_db_model(m, model_key, ckpt_name, "checkpoint_hash_mismatch")
                    continue
                if getattr(pred, "imported_source", None) is not None:
                    self._hide_unknown_identity(m)
                    continue
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
                if cached is not None and self.has_model(model_key):
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
                        if is_active and not metadata_only:
                            pred.load_weights()
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


def build_default_registry(*, metadata_only: bool = False) -> ModelRegistry:
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
            if metadata_only:
                reg.register_from_db(db, metadata_only=True)
            else:
                reg.register_from_db(db)
    except Exception:
        # The HTTP catalogue reports database availability through publish_from_db.
        pass
    return reg


_global_model_registry: Optional[ModelRegistry] = None
_model_registry_initialization_lock = RLock()


def get_model_registry() -> ModelRegistry:
    """Proveedor de dependencias para FastAPI (Dependency Injection)."""
    return initialize_model_registry()


def initialize_model_registry(*, metadata_only: bool = False) -> ModelRegistry:
    """Initialize the shared singleton once; isolated startup never loads weights.

    Metadata-only initialization preserves persisted public defaults and aliases
    from the existing factory. Private prewarming remains nonpublishing. Later
    dependency calls reuse this exact instance without upgrading it eagerly.
    """
    global _global_model_registry
    # Serialize check/build/assignment, including callers with different modes.
    # The first initialization wins; later calls never upgrade or unload it.
    with _model_registry_initialization_lock:
        if _global_model_registry is None:
            _global_model_registry = (build_default_registry(metadata_only=True)
                                      if metadata_only else build_default_registry())
        return _global_model_registry


def set_global_model_registry(registry: Optional[ModelRegistry]) -> None:
    """Permite sobrescribir el registro global para propósitos de prueba."""
    global _global_model_registry
    _global_model_registry = registry
