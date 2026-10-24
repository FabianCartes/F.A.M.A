"""
Servicio de Agregación del Dashboard MLOps (F.A.M.A.)
Consolida métricas operacionales de Ingesta, Entrenamiento, Predicción y Hardware.
"""
from typing import Optional, List, Dict, Any
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.prediction import Prediccion
from app.models.dataset import ConjuntoDatos, Audio
from app.models.training import Modelo, MetricaEntrenamiento
from app.services.training import training_service


class DashboardService:
    """Módulo profundo que centraliza las consultas y agregaciones para el Dashboard."""

    def get_stats(
        self,
        db: Optional[Session] = None,
        ensemble_status: Optional[Dict[str, Any]] = None,
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

                db_status = "operational"
            except Exception:
                db_status = "degraded"
                db.rollback()

        # Información del Super-Ensamble
        super_ens = {
            "ready": None,
            "active_mode": "unknown",
            "models": [],
        }
        if ensemble_status:
            super_ens["ready"] = ensemble_status.get("ensemble_ready")
            super_ens["active_mode"] = ensemble_status.get("active_mode", "unknown")
            if "triad_status" in ensemble_status:
                super_ens["models"] = ensemble_status["triad_status"]

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
            "domain_champions": {
                "bioacoustic": {
                    "source": "historical_reference",
                    "id": "chilean-birds-ensemble",
                    "title": "Campeón Bioacústica Silvestre",
                    "dataset": "Aves Chilenas",
                    "architecture": "Super-Ensamble Tri-Modelo (EffNet 55% + ConvNeXt 30% + ResNet 15%)",
                    "accuracy": 88.31,
                    "macro_f1": 88.68,
                    "classes_count": 15,
                    "badge": "Récord F.A.M.A.",
                },
                "industrial": {
                    "source": "historical_reference",
                    "id": "car-engine-diagnostics-super-ensemble",
                    "title": "Campeón Diagnóstico Automotriz",
                    "dataset": "Motores Vehiculares",
                    "architecture": "Super-Ensamble Tri-Modelo All-RMS-Balanced (ResNet 60% + EffNet 10% + PANNs 30%)",
                    "accuracy": 81.16,
                    "macro_f1": 80.33,
                    "classes_count": 13,
                    "badge": "Fase 11 RDD",
                },
            },
            "training_curves": training_curves,
            "recent_activity": recent_activity[:6],
            "super_ensemble": super_ens,
            "system_health": {
                "database": db_status,
                "storage": "unknown",
                "inference_engine": "unknown",
                "device": device_label,
            },
        }


dashboard_service = DashboardService()
