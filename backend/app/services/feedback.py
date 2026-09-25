"""
Servicio de Retroalimentación Activa y Telemetría de Errores (RF_06 / CU_INV_07).
Módulo profundo que encapsula la persistencia relacional en PostgreSQL (Tabla retroalimentacion)
y la sincronización de audios corregidos en Google Cloud Storage para mejora continua MLOps.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from app.models.prediction import Prediccion
from app.models.feedback import Retroalimentacion
from app.services.storage import upload_audio_to_gcp, DEFAULT_BUCKET_NAME


class FeedbackService:
    """Módulo profundo para la gestión del ciclo de retroalimentación de inferencias bioacústicas."""

    def record_feedback(
        self,
        db: Session,
        id_prediccion: int,
        fue_correcta: bool,
        etiqueta_corregida: Optional[str] = None,
        id_usuario: int = 1,
    ) -> Retroalimentacion:
        """
        Registra la validación experta o la corrección taxonómica de una predicción.
        - Valida la existencia de la predicción en PostgreSQL (HTTP 404).
        - Valida que exista etiqueta corregida si fue_correcta es False (HTTP 422).
        - Persiste o actualiza de forma idempotente en la tabla 'retroalimentacion'.
        - Despacha el audio hacia GCS (carpeta 'feedback/<especie>/') para futuros reentrenamientos.
        """
        # 1. Verificar existencia de la predicción
        prediccion = db.query(Prediccion).filter(Prediccion.id_prediccion == id_prediccion).first()
        if not prediccion:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Predicción con id {id_prediccion} no encontrada.",
            )

        # 2. Validación de consistencia de la corrección
        if not fue_correcta and not etiqueta_corregida:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Se requiere especificar 'etiqueta_corregida' cuando la predicción no fue correcta.",
            )

        # Si fue correcta, limpiar cualquier etiqueta de corrección
        if fue_correcta:
            etiqueta_corregida = None

        # 3. Buscar si ya existía retroalimentación previa para esta predicción (idempotencia)
        feedback_rec = db.query(Retroalimentacion).filter(
            Retroalimentacion.id_prediccion == id_prediccion
        ).first()

        now_utc = datetime.now(timezone.utc)

        if feedback_rec:
            feedback_rec.fue_correcta = fue_correcta
            feedback_rec.etiqueta_corregida = etiqueta_corregida
            feedback_rec.fecha_retroalimentacion = now_utc
            feedback_rec.id_usuario = id_usuario
        else:
            feedback_rec = Retroalimentacion(
                id_prediccion=id_prediccion,
                id_usuario=id_usuario,
                fue_correcta=fue_correcta,
                etiqueta_corregida=etiqueta_corregida,
                procesado=False,
                fecha_retroalimentacion=now_utc,
            )
            db.add(feedback_rec)

        db.commit()
        db.refresh(feedback_rec)

        # 4. Sincronización en segundo plano con Google Cloud Storage (CU_INV_07)
        # Si la predicción fue corregida, respaldar en bucket bajo feedback/<etiqueta>/
        if not fue_correcta and etiqueta_corregida:
            try:
                self._sync_feedback_audio_to_gcs(prediccion, etiqueta_corregida)
            except Exception as gcs_err:
                print(f"[FeedbackService] Advertencia al sincronizar audio con GCS: {gcs_err}")

        return feedback_rec

    def _sync_feedback_audio_to_gcs(self, prediccion: Prediccion, etiqueta_corregida: str) -> None:
        """
        Copia o indexa el audio mal clasificado en GCS bajo la jerarquía de corrección:
        gs://<bucket>/feedback/<etiqueta_corregida>/<filename>
        """
        raw_path = prediccion.ruta_audio_prueba or ""
        filename = Path(raw_path).name or f"audio_{prediccion.id_prediccion}.wav"
        
        # En caso de que exista localmente en audios_prueba o data
        local_candidates = [
            Path(raw_path),
            Path("audios_prueba") / filename,
            Path("../audios_prueba") / filename,
            Path("data") / filename,
        ]
        local_audio: Optional[Path] = None
        for cand in local_candidates:
            if cand.exists() and cand.is_file():
                local_audio = cand
                break

        if local_audio:
            from google.cloud import storage
            import os
            try:
                client = storage.Client()
                bucket_name = os.getenv("GCS_BUCKET_NAME", DEFAULT_BUCKET_NAME)
                bucket = client.bucket(bucket_name)
                dest_blob_name = f"feedback/{etiqueta_corregida}/{filename}"
                blob = bucket.blob(dest_blob_name)
                blob.upload_from_filename(str(local_audio), content_type="audio/wav")
                print(f"[FeedbackService] Audio corregido subido a GCS: {dest_blob_name}")
            except Exception as e:
                # Si estamos sin conexión o mock, omitir silenciosamente
                pass

    def get_feedback_by_prediction(self, db: Session, id_prediccion: int) -> Optional[Retroalimentacion]:
        """Obtiene la retroalimentación existente para una predicción específica."""
        return db.query(Retroalimentacion).filter(
            Retroalimentacion.id_prediccion == id_prediccion
        ).first()

    def get_feedback_stats(self, db: Session) -> Dict[str, Any]:
        """
        Calcula la telemetría consolidada de retroalimentación de campo:
        - total_validated: número total de predicciones con feedback registrado.
        - correct_count: predicciones confirmadas como acertadas.
        - corrected_count: predicciones corregidas por el investigador.
        - accuracy_rate: tasa porcentual de aciertos sobre el total validado.
        - corrections_breakdown: especies corregidas más frecuentes.
        """
        total_validated = db.query(Retroalimentacion).count()

        if total_validated == 0:
            return {
                "total_validated": 0,
                "correct_count": 0,
                "corrected_count": 0,
                "accuracy_rate": 0.0,
                "corrections_breakdown": [],
            }

        correct_count = db.query(Retroalimentacion).filter(
            Retroalimentacion.fue_correcta == True
        ).count()

        corrected_count = total_validated - correct_count
        accuracy_rate = round((correct_count / total_validated) * 100.0, 2)

        # Conteo agrupado de correcciones por especie
        breakdown_query = (
            db.query(
                Retroalimentacion.etiqueta_corregida,
                func.count(Retroalimentacion.id_retroalimentacion).label("total"),
            )
            .filter(Retroalimentacion.fue_correcta == False)
            .group_by(Retroalimentacion.etiqueta_corregida)
            .order_by(func.count(Retroalimentacion.id_retroalimentacion).desc())
            .all()
        )

        corrections_breakdown = [
            {"species": b[0], "count": b[1]} for b in breakdown_query if b[0]
        ]

        return {
            "total_validated": total_validated,
            "correct_count": correct_count,
            "corrected_count": corrected_count,
            "accuracy_rate": accuracy_rate,
            "corrections_breakdown": corrections_breakdown,
        }


feedback_service = FeedbackService()
