"""
Servicio de Agregación del Dashboard MLOps (F.A.M.A.)
Consolida métricas operacionales de Ingesta, Entrenamiento, Predicción y Hardware.
"""
import threading
import time
from typing import Callable, Optional, List, Dict, Any
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.prediction import Prediccion
from app.models.dataset import ConjuntoDatos, Audio
from app.models.training import Modelo, MetricaEntrenamiento, ModelEvaluation
from app.models.triad_composition import TriadComposition
from app.services.training import training_service

STORAGE_PROBE_TTL_SECONDS = 60.0


def _configured_storage_probe() -> Dict[str, Any]:
    """Bounded read probe of the configured bucket (one listed object, short timeouts)."""
    from app.configuration import get_configuration
    from app.connections import _storage
    return _storage(get_configuration())


def _percent(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        return None
    return round(float(value) * 100, 2)


def _best_models(query, db) -> List[Dict[str, Any]]:
    """Best registered model per accessible dataset.

    A completed held-out (``test``) evaluation of the model's current weights ranks first;
    otherwise the training validation accuracy recorded on the model is used and labelled so.
    """
    models = [m for m in query(Modelo).filter(Modelo.id_conjunto_datos.isnot(None)).all()
              if m.arquitectura != "ImportedTriad"]
    if not models:
        return []
    by_id = {m.id_modelo: m for m in models}
    evaluated = {}
    rows = (db.query(ModelEvaluation)
            .filter(ModelEvaluation.id_modelo.in_(tuple(by_id)), ModelEvaluation.split == "test",
                    ModelEvaluation.status == "completed")
            .order_by(ModelEvaluation.id_evaluation.desc()).all())
    for row in rows:
        owner = by_id[row.id_modelo]
        if row.id_modelo in evaluated or row.checkpoint_sha256 != owner.hash_binario:
            continue
        metrics = row.report.get("metrics") if isinstance(row.report, dict) else None
        accuracy = _percent(metrics.get("accuracy")) if isinstance(metrics, dict) else None
        if accuracy is not None:
            evaluated[row.id_modelo] = (accuracy, _percent(metrics.get("f1_macro")))
    best = {}
    for m in models:
        if m.id_modelo in evaluated:
            candidate = (1, *evaluated[m.id_modelo], "test_evaluation")
        elif m.precision is not None:
            candidate = (0, round(float(m.precision), 2), None, "training_validation")
        else:
            continue
        current = best.get(m.id_conjunto_datos)
        if current is None or candidate[:2] > current[0][:2]:
            best[m.id_conjunto_datos] = (candidate, m)
    result = []
    for (_, accuracy, macro_f1, source), m in best.values():
        result.append({"dataset_id": m.id_conjunto_datos,
                       "dataset_name": m.conjunto_datos.nombre if m.conjunto_datos else None,
                       "model_id": m.id_modelo, "architecture": m.arquitectura,
                       "accuracy": accuracy, "macro_f1": macro_f1, "source": source})
    return sorted(result, key=lambda item: (item["dataset_name"] or "", item["dataset_id"]))


def _empty_super_ensemble() -> Dict[str, Any]:
    return {"ready": None, "active_mode": "none", "composition_id": None, "dataset_name": None,
            "version": None, "default": False, "models": []}


def _super_ensemble(query, db) -> Dict[str, Any]:
    """The default triad, or else the latest revision, with its members and registry readiness."""
    summary = _empty_super_ensemble()
    triad = (query(TriadComposition)
             .order_by(TriadComposition.activo.desc(), TriadComposition.created_at.desc(),
                       TriadComposition.id.desc()).first())
    if triad is None:
        return summary
    members = {m.id_modelo: m for m in db.query(Modelo).filter(Modelo.id_modelo.in_(
        (triad.first_model_id, triad.second_model_id, triad.third_model_id))).all()}
    dataset = db.get(ConjuntoDatos, triad.dataset_id)
    from app.services import registry
    from app.services.triad_compositions import triad_model_key
    loaded = registry._global_model_registry  # In-memory catalogue only; never loads or probes weights.
    summary.update(
        ready=loaded.has_model(triad_model_key(triad.id)) if loaded is not None else None,
        active_mode="triad", composition_id=triad.id, version=triad.version, default=bool(triad.activo),
        dataset_name=dataset.nombre if dataset else None,
        models=[{"name": members[model_id].arquitectura if model_id in members else f"Modelo {model_id}",
                 "model_id": model_id, "weight": weight, "ready": None,
                 "accuracy": (round(float(members[model_id].precision), 2)
                              if model_id in members and members[model_id].precision is not None else None)}
                for model_id, weight in ((triad.first_model_id, triad.first_weight),
                                         (triad.second_model_id, triad.second_weight),
                                         (triad.third_model_id, triad.third_weight))])
    return summary


class DashboardService:
    """Módulo profundo que centraliza las consultas y agregaciones para el Dashboard."""

    def __init__(self, storage_probe: Callable[[], Dict[str, Any]] = _configured_storage_probe,
                 clock: Callable[[], float] = time.monotonic):
        self._storage_probe = storage_probe
        self._clock = clock
        self._storage_lock = threading.Lock()
        self._storage_cache: Optional[tuple] = None

    def _storage_status(self) -> str:
        with self._storage_lock:
            now = self._clock()
            if self._storage_cache is None or now - self._storage_cache[0] >= STORAGE_PROBE_TTL_SECONDS:
                try:
                    result = self._storage_probe()
                    status = ("connected" if result.get("ok") else
                              "unknown" if result.get("code") == "storage_configuration_missing" else "unavailable")
                except Exception:
                    status = "unavailable"
                self._storage_cache = (now, status)
            return self._storage_cache[1]

    def get_stats(
        self,
        db: Optional[Session] = None,
        access=None,
    ) -> Dict[str, Any]:
        """
        Retorna la estructura unificada de estadísticas para el Dashboard:
        - KPIs principales
        - Curvas de entrenamiento de la última ejecución
        - Actividad registrada seleccionada (no auditoría completa)
        - Estado de la Tríada Super-Ensamble
        - Salud de los subsistemas
        """
        total_predictions = None
        avg_confidence = None
        total_datasets = None
        total_audios = None
        active_accuracy = None
        active_loss = None
        active_model_name = None
        metrics_source = None
        db_status = "unknown"

        recent_activity: List[Dict[str, Any]] = []
        training_curves: List[Dict[str, Any]] = []
        best_models: List[Dict[str, Any]] = []
        super_ens = _empty_super_ensemble()

        if db is not None:
            try:
                query = db.query if access is None else access.query
                # 1. Total de Predicciones y Confianza Promedio
                predictions = query(Prediccion)
                pred_count = predictions.count()
                total_predictions = pred_count

                if pred_count > 0:
                    avg_conf = predictions.with_entities(func.avg(Prediccion.confianza)).scalar()
                    if avg_conf is not None:
                        avg_confidence = round(float(avg_conf) * 100, 1)

                    # Obtener las últimas 4 predicciones para el feed
                    ultimas_predicciones = (
                        predictions
                        .order_by(Prediccion.id_prediccion.desc())
                        .limit(4)
                        .all()
                    )
                    for p in ultimas_predicciones:
                        ts_str = (
                            p.fecha_prediccion.strftime("%d/%m/%Y, %H:%M")
                            if p.fecha_prediccion
                            else "Reciente"
                        )
                        model_id_val = p.modelo_id
                        domain = {"AvesChilenas": "bioacoustic", "engine_diagnostics": "industrial"}.get(p.dataset_name)
                        domain_tag = {"bioacoustic": "Aves", "industrial": "Motores"}.get(domain)
                        badge_label = f"Inferencia ({domain_tag})" if domain_tag else "Inferencia"
                        recent_activity.append({
                            "id": f"pred-{p.id_prediccion}",
                            "type": "prediccion",
                            "title": f"Inferencia: {p.etiqueta_predicha}",
                            "description": f"Audio {Path(p.ruta_audio_prueba).name} clasificado con {round(p.confianza * 100, 1)}% de confianza",
                            "timestamp": ts_str,
                            "badge": badge_label,
                            "confidence": round(p.confianza * 100, 1),
                            "model_id": model_id_val,
                            "domain": domain,
                        })

                # 2. Datasets y Audios en la base de datos
                total_datasets = query(ConjuntoDatos).count()
                total_audios = query(Audio).count()

                # 3. Modelos y Curvas de Entrenamiento
                ultimo_modelo = (
                    query(Modelo)
                    .order_by(Modelo.id_modelo.desc())
                    .first()
                )

                if ultimo_modelo:
                    metrics_source = "latest_registered_model"
                    if ultimo_modelo.precision is not None:
                        active_accuracy = round(float(ultimo_modelo.precision), 2)
                    if ultimo_modelo.perdida is not None:
                        active_loss = round(float(ultimo_modelo.perdida), 4)
                    if ultimo_modelo.arquitectura:
                        active_model_name = ultimo_modelo.arquitectura

                    # Agregar evento de entrenamiento a actividad reciente
                    ts_m = (
                        ultimo_modelo.fecha_entrenamiento.strftime("%d/%m/%Y, %H:%M")
                        if ultimo_modelo.fecha_entrenamiento
                        else "Reciente"
                    )
                    recent_activity.append({
                        "id": f"mod-{ultimo_modelo.id_modelo}",
                        "type": "entrenamiento",
                        "title": f"Modelo {ultimo_modelo.arquitectura} registrado",
                        "description": (f"Precisión registrada: {round(ultimo_modelo.precision, 1)}% ({ultimo_modelo.epocas} épocas)"
                                        if ultimo_modelo.precision is not None else "Precisión registrada: No disponible"),
                        "timestamp": ts_m,
                        "badge": "Registro de modelo",
                    })

                    # Métricas de entrenamiento de ese modelo
                    metricas = (
                        db.query(MetricaEntrenamiento)
                        .filter(MetricaEntrenamiento.id_modelo == ultimo_modelo.id_modelo)
                        .order_by(MetricaEntrenamiento.epoca.asc())
                        .all()
                    )
                    if metricas:
                        training_curves = [
                            {
                                "epoch": m.epoca,
                                "accuracy": round(float(m.precision), 2),
                                "loss": round(float(m.perdida), 4),
                            }
                            for m in metricas
                        ]

                best_models = _best_models(query, db)
                super_ens = _super_ensemble(query, db)
                db_status = "operational"
            except Exception:
                db_status = "degraded"
                db.rollback()

        # Telemetría básica de hardware
        try:
            hw = training_service.get_hardware_status()
            device_label = hw.get("device_name") or "unknown"
        except Exception:
            device_label = "unknown"

        return {
            "kpis": {
                "accuracy": active_accuracy,
                "loss": active_loss,
                "total_datasets": total_datasets,
                "total_audios": total_audios,
                "total_predictions": total_predictions,
                "avg_confidence": avg_confidence,
                "active_model_name": active_model_name,
                "latest_model_name": active_model_name,
                "metrics_source": metrics_source,
            },
            "best_models": best_models,
            "training_curves": training_curves,
            "recent_activity": recent_activity[:6],
            "super_ensemble": super_ens,
            "system_health": {
                "database": db_status,
                "storage": self._storage_status(),
                "inference_engine": "unknown",
                "device": device_label,
            },
        }


dashboard_service = DashboardService()
