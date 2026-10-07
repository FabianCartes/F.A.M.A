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
        return self.get(self._default_model_id)

    def get(self, model_id: Optional[str] = None) -> AudioPredictor:
        """
        Recupera una estrategia predictora según su ID.
        Si model_id es None o 'default', retorna el modelo por defecto.
        """
        if not self._predictors:
            raise ModelNotFoundError("El catálogo de modelos está vacío.")

        target_id = model_id if (model_id and model_id != "default") else self._default_model_id

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
    ) -> List[Dict[str, Any]]:
        """Reconcile and publish persisted predictors without activation or DB writes.

        Lazy initialization deserializes metadata once without building inference.
        Failures are returned as public codes; exception text and paths stay private.
        Concurrent catalogue requests cannot replace an already published predictor.
        """
        from app.models.training import Modelo
        from app.services.predictors.trained_predictor import TrainedModelPredictor

        root = Path(checkpoints_root) if checkpoints_root is not None else Path(__file__).resolve().parents[2] / "checkpoints"
        errors = []
        with self._publication_lock:
            try:
                models = db.query(Modelo).order_by(Modelo.id_modelo.desc()).all()
            except Exception:
                return [{"code": "database_unavailable"}]
            self._reconcile_db_models(models)
            for model in models:
                key = f"fama_trained_model_{model.id_modelo}"
                if self.has_model(key):
                    continue
                code = "checkpoint_unreadable"
                try:
                    uri = urlparse(model.ruta_binario_gcp)
                    basename = Path(unquote(uri.path) if uri.scheme else model.ruta_binario_gcp).name
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
                        name=f"{model.arquitectura} (Entrenado #{model.id_modelo})",
                        is_default=False,
                        lazy_load=True,
                        dataset_name=_verified_dataset_name(model.conjunto_datos, self._raw_data_root),
                    )
                    # register() selects a default on an empty catalogue. Publication
                    # deliberately preserves even an unset default instead.
                    self._predictors[key] = pred
                    self._db_predictors[key] = pred
                    for alias in (basename, Path(basename).stem, str(model.id_modelo)):
                        self._predictors.setdefault(alias, pred)
                except Exception:
                    errors.append({"model_id": key, "code": code})
        return errors

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
            backend_root = Path(__file__).resolve().parent.parent.parent
            checkpoints_root = backend_root / "checkpoints"
        else:
            checkpoints_root = Path(checkpoints_root)

        from app.models.training import Modelo
        from app.services.predictors.trained_predictor import TrainedModelPredictor

        with self._publication_lock:
            db_models = db.query(Modelo).order_by(Modelo.id_modelo.desc()).all()
            self._reconcile_db_models(db_models)
            active_predictor = None

            for m in db_models:
                ckpt_name = Path(m.ruta_binario_gcp).name
                candidate_paths = [
                    checkpoints_root / ckpt_name,
                    checkpoints_root.parent / "checkpoints" / ckpt_name,
                ]
                ckpt_file = next((p for p in candidate_paths if p.exists()), None)
                # Solo registrar si el archivo existe físicamente y contiene pesos reales (> 10KB)
                if ckpt_file and ckpt_file.stat().st_size > 10000:
                    try:
                        model_key = f"fama_trained_model_{m.id_modelo}"
                        is_active = bool(m.activo)
                        pred = TrainedModelPredictor(
                            checkpoint_path=ckpt_file,
                            model_id=model_key,
                            name=f"{m.arquitectura} (Entrenado #{m.id_modelo})",
                            is_default=is_active,
                            lazy_load=not is_active,
                            dataset_name=_verified_dataset_name(m.conjunto_datos, self._raw_data_root),
                        )
                        self.register(pred, is_default=is_active)
                        self._db_predictors[model_key] = pred
                        # Registrar alias útiles para consultas directas
                        self._predictors[ckpt_file.name] = pred
                        self._predictors[ckpt_file.stem] = pred
                        self._predictors[str(m.id_modelo)] = pred

                        if m.activo:
                            active_predictor = pred
                            self.set_default_model(model_key)
                    except Exception as err:
                        print(f"[ModelRegistry] Advertencia al registrar modelo #{m.id_modelo} ({ckpt_name}): {err}")

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
        backend_root = Path(__file__).resolve().parent.parent.parent
        checkpoints_root = backend_root / "checkpoints"
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
            [p for p in checkpoints_root.glob("fama_*_best.pt") if p.is_file() and p.stat().st_size > 1000000],
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
        backend_root = Path(__file__).resolve().parent.parent.parent
        checkpoints_root = backend_root / "checkpoints"

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
    """Construye el catálogo productivo exclusivamente desde modelos persistidos.

    Un catálogo vacío o una BD inaccesible no habilitan semillas ni descubrimiento
    de archivos. El registro explícito y los descubridores siguen disponibles para
    callers que los soliciten; /api/models reintenta la publicación desde BD.
    """
    from app.database import SessionLocal

    reg = ModelRegistry()
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
