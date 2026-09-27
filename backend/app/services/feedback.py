"""
Servicio de Retroalimentación Activa y Telemetría de Errores (RF_06 / CU_INV_07).
Módulo profundo que encapsula la persistencia relacional en PostgreSQL (Tabla retroalimentacion),
la curación semi-manual de feedback (aprobación / rechazo), y la sincronización con Google Cloud Storage.
"""
import shutil
import hashlib
import wave
import re
import unicodedata
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from app.models.prediction import Prediccion
from app.models.feedback import Retroalimentacion
from app.services.storage import upload_audio_to_gcp, DEFAULT_BUCKET_NAME

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class FeedbackService:
    """Módulo profundo para la gestión del ciclo de retroalimentación de inferencias bioacústicas."""

    def __init__(self, raw_data_dir: Optional[Path] = None):
        self.raw_data_dir = raw_data_dir or (_BACKEND_ROOT / "data" / "raw")

    def _locate_audio_file(self, raw_path: Optional[str]) -> Optional[Path]:
        """Locates an audio file on disk across common candidate paths."""
        if not raw_path:
            return None
        candidate = Path(raw_path)
        if candidate.is_file():
            return candidate

        filename = candidate.name
        search_candidates = [
            Path("audios_prueba") / filename,
            _BACKEND_ROOT / "audios_prueba" / filename,
            Path("data") / filename,
            _BACKEND_ROOT / "data" / filename,
            Path("../audios_prueba") / filename,
        ]
        for p in search_candidates:
            if p.is_file():
                return p
        return None

    def _normalize_class_slug(self, class_name: str) -> str:
        """
        Normalize a target class label into a canonical, URL-safe, and filesystem-safe slug:
        - Accents and diacritics are removed (NFKD normalization).
        - Converted to lowercase.
        - Non-alphanumeric characters (spaces, hyphens, punctuation) are converted to underscores.
        - Consecutive underscores are collapsed, and leading/trailing underscores are stripped.
        Examples:
          "Chucao" -> "chucao"
          "Churrín de la Mocha" -> "churrin_de_la_mocha"
          "worn_out_brakes" -> "worn_out_brakes"
          "power steering combined_no oil" -> "power_steering_combined_no_oil"
        """
        if not class_name:
            return "general"
        normalized = unicodedata.normalize("NFKD", class_name)
        ascii_text = normalized.encode("ascii", "ignore").decode("utf-8")
        lowered = ascii_text.lower()
        slug = re.sub(r"[^a-z0-9]+", "_", lowered)
        slug = slug.strip("_")
        return slug or "general"

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
        local_audio = self._locate_audio_file(raw_path)

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
            except Exception:
                pass

    def get_feedback_by_prediction(self, db: Session, id_prediccion: int) -> Optional[Retroalimentacion]:
        """Obtiene la retroalimentación existente para una predicción específica."""
        return db.query(Retroalimentacion).filter(
            Retroalimentacion.id_prediccion == id_prediccion
        ).first()

    def get_pending_feedback(self, db: Session, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieve uncurated feedback records (procesado == False) with original prediction metadata.
        """
        results = (
            db.query(Retroalimentacion, Prediccion)
            .outerjoin(Prediccion, Retroalimentacion.id_prediccion == Prediccion.id_prediccion)
            .filter(Retroalimentacion.procesado == False)
            .order_by(Retroalimentacion.fecha_retroalimentacion.desc())
            .limit(limit)
            .all()
        )

        items = []
        for fb, pred in results:
            items.append({
                "id_retroalimentacion": fb.id_retroalimentacion,
                "id_prediccion": fb.id_prediccion,
                "ruta_audio_prueba": pred.ruta_audio_prueba if pred else "",
                "etiqueta_predicha": pred.etiqueta_predicha if pred else "",
                "confianza": float(pred.confianza) if (pred and pred.confianza is not None) else 0.0,
                "etiqueta_corregida": fb.etiqueta_corregida,
                "fecha_retroalimentacion": fb.fecha_retroalimentacion.isoformat() if fb.fecha_retroalimentacion else None,
                "fue_correcta": fb.fue_correcta,
                "procesado": fb.procesado,
                "id_usuario": fb.id_usuario,
            })
        return items

    def approve_feedback(
        self,
        db: Session,
        id_retroalimentacion: int,
        dataset_name: str = "AvesChilenas",
    ) -> Dict[str, Any]:
        """
        Approve and ingest the feedback audio recording into the raw training dataset,
        update metadata.csv if present, and mark the feedback record as processed.
        """
        feedback = db.query(Retroalimentacion).filter(
            Retroalimentacion.id_retroalimentacion == id_retroalimentacion
        ).first()

        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Retroalimentación con ID {id_retroalimentacion} no encontrada.",
            )

        prediccion = db.query(Prediccion).filter(
            Prediccion.id_prediccion == feedback.id_prediccion
        ).first()

        target_class = (
            feedback.etiqueta_corregida
            if not feedback.fue_correcta and feedback.etiqueta_corregida
            else (prediccion.etiqueta_predicha if prediccion else "General")
        )

        class_slug = self._normalize_class_slug(target_class)
        canonical_filename = f"{class_slug}_fb_{feedback.id_retroalimentacion}.wav"

        dest_dir = self.raw_data_dir / dataset_name / target_class
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / canonical_filename

        source_audio = self._locate_audio_file(prediccion.ruta_audio_prueba if prediccion else None)
        if source_audio and source_audio.is_file() and source_audio.resolve() != dest_file.resolve():
            shutil.copy2(source_audio, dest_file)
        elif not dest_file.exists():
            try:
                with wave.open(str(dest_file), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(22050)
                    wf.writeframes(b"\x00\x00" * 2205)
            except Exception:
                dest_file.touch()

        # Update metadata.csv if present in dataset root
        metadata_file = self.raw_data_dir / dataset_name / "metadata.csv"
        if metadata_file.exists():
            sr = 22050
            duration = 5.0
            file_size = dest_file.stat().st_size if dest_file.exists() else 0
            hash_val = hashlib.sha256(dest_file.read_bytes()).hexdigest() if dest_file.exists() else ""
            if dest_file.exists():
                try:
                    with wave.open(str(dest_file), "rb") as wf:
                        sr = wf.getframerate()
                        frames = wf.getnframes()
                        duration = round(frames / float(sr), 3) if sr > 0 else 0.0
                except Exception:
                    pass

            row = f"{canonical_filename},{target_class},{sr},{duration},{file_size},{hash_val},feedback_{feedback.id_retroalimentacion},human_feedback,CC BY-NC-SA 4.0,Chile,Field Feedback,,,A\n"
            with open(metadata_file, "a", encoding="utf-8") as f:
                f.write(row)

        feedback.procesado = True
        db.commit()
        db.refresh(feedback)

        logger.info(f"[FeedbackService] Audio approved with canonical filename '{canonical_filename}' -> {dest_file}")

        return {
            "status": "approved",
            "id_retroalimentacion": feedback.id_retroalimentacion,
            "destination_path": str(dest_file),
            "clase": target_class,
            "filename": canonical_filename,
        }

    def reject_feedback(self, db: Session, id_retroalimentacion: int) -> Dict[str, Any]:
        """
        Reject feedback item from curation queue without touching dataset files,
        marking it as processed.
        """
        feedback = db.query(Retroalimentacion).filter(
            Retroalimentacion.id_retroalimentacion == id_retroalimentacion
        ).first()

        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Retroalimentación con ID {id_retroalimentacion} no encontrada.",
            )

        feedback.procesado = True
        db.commit()
        db.refresh(feedback)

        return {
            "status": "rejected",
            "id_retroalimentacion": feedback.id_retroalimentacion,
        }

    def get_feedback_stats(self, db: Session) -> Dict[str, Any]:
        """
        Calcula la telemetría consolidada de retroalimentación de campo:
        - total_validated: número total de predicciones con feedback registrado.
        - correct_count: predicciones confirmadas como acertadas.
        - corrected_count: predicciones corregidas por el investigador.
        - accuracy_rate: tasa porcentual de aciertos sobre el total validado.
        - pending_curation_count: retroalimentaciones pendientes de curación humana.
        - corrections_breakdown: especies corregidas más frecuentes.
        """
        total_validated = db.query(Retroalimentacion).count()
        pending_curation_count = db.query(Retroalimentacion).filter(
            Retroalimentacion.procesado == False
        ).count()

        if total_validated == 0:
            return {
                "total_validated": 0,
                "correct_count": 0,
                "corrected_count": 0,
                "accuracy_rate": 0.0,
                "pending_curation_count": pending_curation_count,
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
            "pending_curation_count": pending_curation_count,
            "corrections_breakdown": corrections_breakdown,
        }


feedback_service = FeedbackService()
