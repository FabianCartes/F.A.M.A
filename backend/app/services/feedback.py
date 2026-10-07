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
from app.services.feedback_sync import FeedbackSyncQueue
from dataset_references import resolve_reference, reference_from_path

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
            fecha_carga = pred.fecha_carga if pred else None
            if fecha_carga is not None:
                if fecha_carga.tzinfo is None:
                    # SQLite strips tzinfo from this UTC-only column on round-trip.
                    # Do not relabel an unknown naive value from another dialect.
                    fecha_carga = (fecha_carga.replace(tzinfo=timezone.utc)
                                   if db.get_bind().dialect.name == "sqlite" else None)
                if fecha_carga is not None:
                    fecha_carga = fecha_carga.astimezone(timezone.utc).isoformat()
            items.append({
                "id_retroalimentacion": fb.id_retroalimentacion,
                "id_prediccion": fb.id_prediccion,
                "dataset_name": pred.dataset_name if pred else None,
                "audio_filename": pred.nombre_original if pred else None,
                "fecha_carga": fecha_carga,
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

    def _safe_path(self, path: Path):
        """Reject symlinks in every ancestor, including configured raw ancestors."""
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("Ruta de dataset no válida")
        if not path.resolve().is_relative_to(self.raw_data_dir.resolve()):
            raise ValueError("Ruta fuera del dataset local")

    @staticmethod
    def _fsync_dir(path: Path):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _mkdir(self, path: Path):
        self._safe_path(path)
        if path.exists() and not path.is_dir():
            raise OSError("Dataset directory obstructed")
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        # Reconfirm the last existing entry too: a prior mkdir may have been
        # interrupted after creation but before fsync of its parent.
        self._fsync_dir(current.parent)
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True)
            self._fsync_dir(directory.parent)

    def _publish(self, path: Path, data: bytes, *, no_replace=False):
        """Durable staged publication; audio must never replace an existing inode."""
        staging = path.with_suffix(path.suffix + ".pending")
        self._safe_path(path)
        self._safe_path(staging)
        descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                             | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if no_replace:
            # Atomic no-clobber publication, unlike replace(check-then-write).
            os.link(staging, path)
            staging.unlink()
        else:
            staging.replace(path)
        self._fsync_dir(path.parent)

    @staticmethod
    def _class_key(label: str) -> str:
        return re.sub(r"[\s_]+", "_", unicodedata.normalize("NFC", label).casefold())

    def _read_canonical_metadata(self, dataset: Path):
        """Validate existing raw rows without rewriting or guessing historical paths."""
        metadata = dataset / "metadata.csv"
        self._safe_path(metadata)
        if not metadata.exists():
            return [], []
        with metadata.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            columns = reader.fieldnames
            if (not columns or len(set(columns)) != len(columns)
                    or not {"nombre_archivo", "clase", "file_path", "file_stage"}.issubset(columns)):
                raise ValueError("Índice no canónico; requiere conversión offline explícita")
            rows = list(reader)
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Fila de metadatos malformada")
            storage.validate_path_component(row["nombre_archivo"])
            storage.validate_path_component(row["clase"])
            if row["file_stage"] != "raw":
                raise ValueError("El índice de incorporación debe declarar etapa raw")
            try:
                resolve_reference(row["file_path"], row["file_stage"], {"raw": dataset})
            except ValueError:
                raise ValueError("Referencia raw no válida en los metadatos locales") from None
        return rows, columns

    def _resolve_local_class(self, dataset: Path, label: str) -> str:
        """Local directories and verified canonical metadata establish class identity."""
        rows, _ = self._read_canonical_metadata(dataset)
        directories = set()
        if dataset.exists():
            for child in dataset.iterdir():
                if child.name.startswith(".") or child.name in ("processed_wav", "metadata.csv.pending"):
                    continue
                if child.is_dir() or child.is_symlink():
                    storage.validate_path_component(child.name)
                    directories.add(child.name)
        key = self._class_key(label)
        matches = [name for name in directories if self._class_key(name) == key]
        if len(matches) > 1:
            return self._resolve_indexed_class(dataset, key, matches)
        if matches:
            self._safe_path(dataset / matches[0])
            return matches[0]
        metadata = dataset / "metadata.csv"
        self._safe_path(metadata)
        labels = set()
        for row in rows:
            labels.add(storage.validate_path_component(row["clase"]))
        matches = [name for name in labels if self._class_key(name) == key]
        if len(matches) > 1:
            raise ValueError("Clase ambigua en los metadatos locales")
        if matches:
            return matches[0]
        raise ValueError("Clase desconocida en el catálogo local")

    def _resolve_indexed_class(self, dataset: Path, key: str, matches: List[str]) -> str:
        """Resolve a collision only from unanimous, physically verified CSV evidence."""
        metadata = dataset / "metadata.csv"
        self._safe_path(metadata)
        if not metadata.is_file():
            raise ValueError("Clase ambigua sin metadatos locales verificables")
        for name in matches:
            directory = dataset / name
            self._safe_path(directory)
            if not directory.is_dir():
                raise ValueError("Directorio de clase no válido")
        selected = set()
        rows, _ = self._read_canonical_metadata(dataset)
        for row in rows:
            if self._class_key(row["clase"]) != key:
                continue
            relative = Path(row["file_path"])
            if len(relative.parts) < 2 or relative.parts[0] not in matches:
                raise ValueError("Referencia de audio fuera de los directorios de clase")
            selected.add(relative.parts[0])
        if len(selected) != 1:
            raise ValueError("Clase ambigua: los metadatos locales no identifican un único directorio")
        return selected.pop()

    def _incorporate_metadata(self, dataset, storage_class, filename, label, audio, digest):
        metadata = dataset / "metadata.csv"
        self._safe_path(metadata)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            sr = wav.getframerate()
            if sr <= 0 or wav.getnframes() <= 0:
                raise ValueError("Audio WAV vacío")
            duration = round(wav.getnframes() / sr, 3)
            if len(wav.readframes(wav.getnframes())) != wav.getnframes() * wav.getnchannels() * wav.getsampwidth():
                raise ValueError("Audio WAV incompleto")
        values = dict(nombre_archivo=filename, clase=label, frecuencia_muestreo=sr,
                      duracion_segundos=duration, tamano_bytes=len(audio), hash_archivo=digest,
                      xc_id=filename.removesuffix(".wav"), recordist="human_feedback",
                      licencia="", pais="", localidad="", lat="", lon="", calidad="",
                      file_path=f"{storage_class}/{filename}", file_stage="raw")
        rows, columns = self._read_canonical_metadata(dataset)
        columns = columns + [c for c in values if c not in columns]
        duplicates = [row for row in rows if row.get("nombre_archivo") == filename]
        if duplicates:
            if len(duplicates) != 1 or any(duplicates[0].get(k) != str(values[k])
                                          for k in ("clase", "hash_archivo", "xc_id", "file_path", "file_stage",
                                                    "frecuencia_muestreo", "duracion_segundos",
                                                    "tamano_bytes", "recordist")):
                raise ValueError("Conflicto de metadatos para el audio canónico")
            with metadata.open("rb") as stream:
                os.fsync(stream.fileno())
            self._fsync_dir(dataset)
            return
        rows.append(values)
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode("utf-8")

    def approve_feedback(self, db: Session, id_retroalimentacion: int,
                         dataset_name: Optional[str] = None) -> Dict[str, Any]:
        """Verify durable local audio/CSV, then commit processed + sync intent together.

        The filesystem intent survives rollback/crash and pins source, destination
        and digest. No synchronous cloud upload; replay verifies local evidence.
        """
        feedback = db.query(Retroalimentacion).filter_by(
            id_retroalimentacion=id_retroalimentacion).with_for_update().first()
        if not feedback:
            raise HTTPException(status_code=404, detail="Retroalimentación no encontrada.")
        queue = FeedbackSyncQueue()
        try:
            existing = queue.get(db, id_retroalimentacion)
            if feedback.procesado and existing is None:
                raise HTTPException(status_code=409, detail="La retroalimentación ya fue finalizada.")
            pred = feedback.prediccion
            stored_dataset = pred.dataset_name if pred else None
            if not stored_dataset:
                raise HTTPException(status_code=409, detail="Predicción sin dataset de almacenamiento verificable; permanece pendiente.")
            if dataset_name is not None:
                storage.validate_path_component(dataset_name)
                if dataset_name != stored_dataset:
                    raise HTTPException(status_code=409, detail="El destino no puede cambiar respecto a la inferencia.")
            label = pred.etiqueta_predicha if feedback.fue_correcta else feedback.etiqueta_corregida
            storage.validate_path_component(stored_dataset)
            storage.validate_path_component(label)
            dataset = self.raw_data_dir / stored_dataset
            self._safe_path(dataset)
            self._mkdir(self.raw_data_dir)
            intent_path = self._intent_path(id_retroalimentacion)
            self._safe_path(intent_path)
            # Retain the per-feedback lock through the DB commit, not just JSON creation.
            with _filesystem_lock(intent_path.with_suffix(".json.lock")):
                db.refresh(feedback)
                db.refresh(pred)
                current_label = pred.etiqueta_predicha if feedback.fue_correcta else feedback.etiqueta_corregida
                if pred.dataset_name != stored_dataset or current_label != label:
                    raise HTTPException(status_code=409, detail="La identidad cambió durante la aprobación. Reintente.")
                existing = queue.get(db, id_retroalimentacion)
                if feedback.procesado and existing is None:
                    raise HTTPException(status_code=409, detail="La retroalimentación ya fue finalizada.")
                identity = {"dataset": stored_dataset, "class": label, "source": pred.ruta_audio_prueba}
                recorded = json.loads(intent_path.read_text(encoding="utf-8")) if intent_path.exists() else None
                if recorded and any(recorded.get(k) != v for k, v in identity.items()):
                    raise ValueError("El destino, clase o fuente de la intención no pueden cambiar")
                if existing and (existing.dataset_name != stored_dataset or existing.class_label != label):
                    raise ValueError("Identidad de sincronización incompatible")
                storage_class = (existing.storage_class if existing else recorded["storage_class"]
                                 if recorded else self._resolve_local_class(dataset, label))
                storage.validate_path_component(storage_class)
                filename = f"feedback_{id_retroalimentacion}.wav"
                destination = dataset / storage_class / filename
                self._safe_path(destination)
                publish_intent = recorded is None or not recorded.get("sha256")
                if recorded is None:
                    recorded = {**identity, "storage_class": storage_class, "filename": filename}
                elif recorded.get("filename") != filename or recorded.get("storage_class") != storage_class:
                    raise ValueError("Intención legacy o incompatible; requiere recuperación explícita")
                digest = existing.sha256 if existing else recorded.get("sha256")
                if digest and destination.exists():
                    audio = destination.read_bytes()
                else:
                    audio = storage.download_prediction_audio(pred.ruta_audio_prueba)
                actual = hashlib.sha256(audio).hexdigest()
                if digest and actual != digest:
                    raise ValueError("Hash de audio incompatible con la intención")
                if not digest:
                    digest = actual
                    recorded["sha256"] = digest
                elif recorded.get("sha256") != digest:
                    raise ValueError("Hash de intención local incompatible con la cola")
                self._mkdir(dataset)
                # Serialize duplicate admission with intent/audio/CSV publication.
                with _filesystem_lock(dataset / ".metadata.lock"):
                    rows, _ = self._read_canonical_metadata(dataset)
                    canonical_path = f"{storage_class}/{filename}"
                    if any(row.get("hash_archivo") == digest
                           and row["file_path"] != canonical_path for row in rows):
                        raise HTTPException(
                            status_code=409,
                            detail="El audio exacto ya está incorporado en otra fila del dataset; permanece pendiente.",
                        )
                    if publish_intent:
                        self._publish(intent_path, json.dumps(recorded).encode("utf-8"))
                    # A prior replace may have succeeded before its directory fsync failed.
                    with intent_path.open("rb") as stream:
                        os.fsync(stream.fileno())
                    self._fsync_dir(self.raw_data_dir)
                    self._safe_path(destination)
                    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                        raise ValueError("El archivo canónico existente tiene contenido diferente")
                    # Validate WAV and CSV before publishing any new audio.
                    self._mkdir(destination.parent)
                    metadata_update = self._incorporate_metadata(dataset, storage_class, filename, label, audio, digest)
                    if not destination.exists():
                        self._publish(destination, audio, no_replace=True)
                    else:
                        with destination.open("rb") as stream:
                            os.fsync(stream.fileno())
                        self._fsync_dir(destination.parent)
                    # Publish verified audio before referring to it in a NEW CSV row.
                    reference_from_path(destination, "raw", {"raw": dataset})
                    if metadata_update is not None:
                        self._publish(dataset / "metadata.csv", metadata_update)
                    sync = queue.enqueue(db, id_retroalimentacion, dataset_name=stored_dataset,
                                         storage_class=storage_class, sha256=digest)
                    feedback.procesado = True
                    db.commit()
                return {"status": "approved", "id_retroalimentacion": id_retroalimentacion,
                        "destination_path": str(destination), "clase": label, "filename": filename,
                        "local_status": "incorporated", "sync_status": sync.status}
        except HTTPException:
            db.rollback()
            raise
        except ValueError as error:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(error))
        except Exception:
            db.rollback()
            logger.exception("Local feedback incorporation failed")
            raise HTTPException(status_code=503, detail="No se pudo confirmar la incorporación local. Reintente con la misma intención.")

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

        try:
            self._mkdir(self.raw_data_dir)
            intent_path = self._intent_path(id_retroalimentacion)
            self._safe_path(intent_path)
            with _filesystem_lock(intent_path.with_suffix(".json.lock")):
                db.refresh(feedback)
                if feedback.procesado or intent_path.exists():
                    raise HTTPException(status_code=409, detail="La retroalimentación fue finalizada o su incorporación ya fue iniciada.")
                feedback.procesado = True
                db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise HTTPException(status_code=503, detail="No se pudo confirmar el descarte. Reintente.")

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
