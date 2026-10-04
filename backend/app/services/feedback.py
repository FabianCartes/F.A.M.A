"""
Servicio de Retroalimentación Activa y Telemetría de Errores (RF_06 / CU_INV_07).
Módulo profundo que encapsula la persistencia relacional en PostgreSQL (Tabla retroalimentacion),
la curación semi-manual de feedback (aprobación / rechazo), y la sincronización con Google Cloud Storage.
"""
import csv
import fcntl
import os
from contextlib import contextmanager
import io
import json
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
from app.services import storage

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


@contextmanager
def _filesystem_lock(path: Path):
    """Lock a stable sidecar inode across processes; never lock a replaced file."""
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        # Closing also releases the lock on errors or process exit.
        os.close(descriptor)


class FeedbackService:
    """Módulo profundo para la gestión del ciclo de retroalimentación de inferencias bioacústicas."""

    def __init__(self, raw_data_dir: Optional[Path] = None):
        self.raw_data_dir = raw_data_dir or (_BACKEND_ROOT / "data" / "raw")

    def _intent_path(self, feedback_id: int) -> Path:
        return self.raw_data_dir / f".feedback_{feedback_id}.json"

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
        - Keeps audio outside the dataset until human approval.
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
        ).with_for_update().first()

        now_utc = datetime.now(timezone.utc)

        if feedback_rec:
            if feedback_rec.procesado or self._intent_path(feedback_rec.id_retroalimentacion).exists():
                raise HTTPException(status_code=409, detail="La retroalimentación fue finalizada o su incorporación ya fue iniciada.")
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

        return feedback_rec

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
                "dataset_name": pred.dataset_name if pred else None,
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
        dataset_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Approve and ingest the feedback audio recording into the raw training dataset,
        update metadata.csv if present, and mark the feedback record as processed.
        """
        feedback = db.query(Retroalimentacion).filter(
            Retroalimentacion.id_retroalimentacion == id_retroalimentacion
        ).with_for_update().first()

        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Retroalimentación con ID {id_retroalimentacion} no encontrada.",
            )

        if feedback.procesado:
            raise HTTPException(status_code=409, detail="La retroalimentación ya fue finalizada.")

        prediccion = db.query(Prediccion).filter(
            Prediccion.id_prediccion == feedback.id_prediccion
        ).first()

        stored_dataset = prediccion.dataset_name if prediccion else None
        if not stored_dataset:
            raise HTTPException(status_code=409, detail="Predicción sin dataset de almacenamiento verificable; permanece pendiente.")
        if dataset_name is not None:
            try:
                storage.validate_path_component(dataset_name)
            except ValueError:
                raise HTTPException(status_code=422, detail="Dataset no válido.")
            if dataset_name != stored_dataset:
                raise HTTPException(status_code=409, detail="El destino no puede cambiar respecto a la inferencia.")
        dataset_name = stored_dataset

        target_class = (
            feedback.etiqueta_corregida
            if not feedback.fue_correcta and feedback.etiqueta_corregida
            else (prediccion.etiqueta_predicha if prediccion else "General")
        )

        try:
            storage.validate_path_component(dataset_name)
            storage.validate_path_component(target_class)
        except ValueError:
            raise HTTPException(status_code=422, detail="Dataset o clase no válidos.")
        class_slug = self._normalize_class_slug(target_class)
        canonical_filename = f"{class_slug}_fb_{feedback.id_retroalimentacion}.wav"
        dataset_dir = self.raw_data_dir / dataset_name
        metadata_file = dataset_dir / "metadata.csv"
        intent_file = self._intent_path(feedback.id_retroalimentacion)
        intent = {"dataset": dataset_name, "class": target_class,
                  "source": prediccion.ruta_audio_prueba}
        # A retry uses the pinned directory even if the cloud catalogue changes.
        try:
            if intent_file.is_symlink():
                raise ValueError("Invalid incorporation intent path")
            if intent_file.exists():
                recorded = json.loads(intent_file.read_text(encoding="utf-8"))
                if {key: recorded.get(key) for key in intent} != intent:
                    raise ValueError("Incorporation target cannot change after an attempt")
                storage_class = recorded.get("storage_class", recorded["class"])
            else:
                storage_class = storage.resolve_dataset_class(dataset_name, target_class)
            storage.validate_path_component(storage_class)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err))
        except Exception:
            raise HTTPException(status_code=503, detail="Catálogo de almacenamiento no disponible. Reintente.")
        dest_file = dataset_dir / storage_class / canonical_filename
        for path in (self.raw_data_dir, dataset_dir, dest_file.parent, dest_file, metadata_file):
            if path.is_symlink():
                raise HTTPException(status_code=422, detail="Ruta de dataset no válida.")
        try:
            self.raw_data_dir.mkdir(parents=True, exist_ok=True)
            intent_file = self._intent_path(feedback.id_retroalimentacion)
            if intent_file.is_symlink():
                raise ValueError("Invalid incorporation intent path")
            with _filesystem_lock(intent_file.with_suffix(".json.lock")):
                if intent_file.exists():
                    recorded = json.loads(intent_file.read_text(encoding="utf-8"))
                    if ({key: recorded.get(key) for key in intent} != intent
                            or recorded.get("storage_class", recorded["class"]) != storage_class):
                        raise ValueError("Incorporation target cannot change after an attempt")
                else:
                    staging_intent = intent_file.with_suffix(".json.pending")
                    if staging_intent.is_symlink():
                        raise ValueError("Invalid incorporation staging path")
                    with staging_intent.open("w", encoding="utf-8") as stream:
                        json.dump({**intent, "storage_class": storage_class}, stream)
                    staging_intent.replace(intent_file)
            audio = storage.download_prediction_audio(prediccion.ruta_audio_prueba if prediccion else "")
            if not storage.upload_audio_to_gcp_sync(
                audio, canonical_filename,
                destination_folder=f"datasets/{dataset_name}/{storage_class}",
            ):
                raise OSError("Dataset upload was not confirmed")
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_bytes(audio)
            # Hold the dataset lock from reading through replacement, including
            # duplicate detection and the shared staging file used by retries.
            with _filesystem_lock(dataset_dir / ".metadata.lock"):
                if metadata_file.exists():
                    with metadata_file.open(newline="", encoding="utf-8") as stream:
                        rows = list(csv.reader(stream))
                    if not any(row and row[0] == canonical_filename for row in rows):
                        sr, duration = "", ""
                        try:
                            with wave.open(io.BytesIO(audio), "rb") as wf:
                                sr = wf.getframerate()
                                duration = round(wf.getnframes() / sr, 3)
                        except (wave.Error, EOFError):
                            pass
                        rows.append([canonical_filename, target_class, sr, duration, len(audio),
                                     hashlib.sha256(audio).hexdigest(), f"feedback_{feedback.id_retroalimentacion}",
                                     "human_feedback", "", "", "", "", "", ""])
                        # Atomic replacement prevents truncated metadata on an interrupted write.
                        staging = metadata_file.with_suffix(".csv.pending")
                        if staging.is_symlink():
                            raise ValueError("Invalid metadata staging path")
                        with staging.open("w", newline="", encoding="utf-8") as stream:
                            csv.writer(stream).writerows(rows)
                        staging.replace(metadata_file)
        except Exception:
            db.rollback()
            logger.exception("Feedback incorporation failed")
            raise HTTPException(status_code=503, detail="No se pudo incorporar el audio real en GCS y local. Reintente.")

        try:
            feedback.procesado = True
            db.commit()
            db.refresh(feedback)
        except Exception:
            db.rollback()
            logger.exception("Feedback finalization failed")
            raise HTTPException(status_code=503, detail="No se pudo finalizar la incorporación. Reintente.")

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
        ).with_for_update().first()

        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Retroalimentación con ID {id_retroalimentacion} no encontrada.",
            )

        if feedback.procesado:
            raise HTTPException(status_code=409, detail="La retroalimentación ya fue finalizada.")
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
