"""Cola record-only: el llamador verifica local y confirma su propia transacción."""
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import unicodedata

from app.models.feedback import Retroalimentacion
from app.models.feedback_sync import FeedbackSync


@dataclass(frozen=True)
class SyncIntent:
    id_retroalimentacion: int
    dataset_name: str
    storage_class: str
    class_label: str
    object_key: str
    local_relative_path: str
    sha256: str
    status: str
    attempts: int
    error_code: str | None
    incorporated_by: int | None
    incorporated_at: datetime | None


def _snapshot(row):
    return SyncIntent(**{name: getattr(row, name) for name in SyncIntent.__dataclass_fields__})


def _validate_component(value):
    # No storage import: record-only operations must not initialize cloud clients.
    if (not isinstance(value, str) or not value or value != value.strip()
            or value in (".", "..") or len(value) > 100
            or any(c in value for c in "/\\\\")
            or any(unicodedata.category(c).startswith("C") for c in value)):
        raise ValueError("Invalid storage path component")


class FeedbackSyncQueue:
    """No IO externo, commit ni rollback; las identidades retornadas son inmutables."""

    def enqueue(self, db, feedback_id, *, dataset_name, storage_class, sha256,
                incorporated_by=None, incorporated_at=None):
        if type(feedback_id) is not int or feedback_id <= 0:
            raise ValueError("Expected positive integer feedback ID")
        _validate_component(dataset_name)
        _validate_component(storage_class)
        if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ValueError("Expected lowercase SHA-256")
        feedback = db.query(Retroalimentacion).filter_by(
            id_retroalimentacion=feedback_id).with_for_update().first()
        if feedback is None:
            raise ValueError("Feedback not found")
        label = (feedback.prediccion.etiqueta_predicha if feedback.fue_correcta
                 else feedback.etiqueta_corregida)
        if dataset_name != feedback.prediccion.dataset_name:
            raise ValueError("Dataset differs from persisted prediction")
        _validate_component(label)
        existing = db.get(FeedbackSync, feedback_id)
        if existing:
            if (existing.dataset_name, existing.storage_class, existing.class_label,
                    existing.sha256) != (dataset_name, storage_class, label, sha256):
                raise ValueError("Conflicting synchronization identity")
            return _snapshot(existing)
        relative = f"{dataset_name}/{storage_class}/feedback_{feedback_id}.wav"
        row = FeedbackSync(id_retroalimentacion=feedback_id, dataset_name=dataset_name,
                           storage_class=storage_class, class_label=label,
                           object_key=f"datasets/{relative}", local_relative_path=relative,
                           sha256=sha256, incorporated_by=incorporated_by,
                           incorporated_at=incorporated_at)
        db.add(row)
        db.flush()
        return _snapshot(row)

    def get(self, db, feedback_id):
        row = db.get(FeedbackSync, feedback_id)
        return _snapshot(row) if row else None

    def mark_outcome(self, db, feedback_id, *, success, error_code=None):
        if type(success) is not bool or (success and error_code is not None) or (
                not success and error_code not in ("upload_failed", "integrity_mismatch")):
            raise ValueError("Invalid synchronization outcome")
        row = db.query(FeedbackSync).filter_by(
            id_retroalimentacion=feedback_id).with_for_update().first()
        if row is None:
            raise ValueError("Synchronization intent not found")
        if row.status == "synced":
            if not success:
                raise ValueError("Synced is terminal")
            return _snapshot(row)
        row.attempts += 1
        row.status = "synced" if success else "pending"
        row.error_code = error_code
        db.flush()
        return _snapshot(row)

    def recent(self, db, limit=50, access=None):
        """Read-only accepted milestones, newest feedback first; no file/cloud IO."""
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Limit must be between 1 and 500")
        query = db.query(FeedbackSync, Retroalimentacion.id_prediccion, Retroalimentacion.id_usuario)
        if access is not None and not access.administrator:
            query = query.filter(Retroalimentacion.id_prediccion.in_(access.prediction_ids()),
                                 FeedbackSync.dataset_name.in_(access.names))
        rows = (query
                .join(Retroalimentacion, FeedbackSync.id_retroalimentacion ==
                      Retroalimentacion.id_retroalimentacion)
                .filter(Retroalimentacion.procesado.is_(True))
                .order_by(FeedbackSync.id_retroalimentacion.desc()).limit(limit).all())
        from app.models.dataset import Audio, ConjuntoDatos
        names = {row.dataset_name for row, _, _ in rows}
        filenames = {f"feedback_{row.id_retroalimentacion}.wav" for row, _, _ in rows}
        registered = set(db.query(ConjuntoDatos.nombre, Audio.nombre_archivo, Audio.hash_archivo)
                         .join(Audio, Audio.id_conjunto_datos == ConjuntoDatos.id_conjunto_datos)
                         .filter(ConjuntoDatos.nombre.in_(names), Audio.nombre_archivo.in_(filenames)).all()) if rows else set()

        def timestamp(value):
            if value is not None and value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc) if db.get_bind().dialect.name == 'sqlite' else None
            return value

        return [dict(id_retroalimentacion=row.id_retroalimentacion,
                     id_prediccion=prediction_id, dataset_name=row.dataset_name,
                     storage_class=row.storage_class, class_label=row.class_label,
                     local_status="incorporated", sync_status=row.status,
                     attempts=row.attempts, error_code=row.error_code,
                     proposed_by=proposed_by,
                     incorporated_by=row.incorporated_by, incorporated_at=timestamp(row.incorporated_at),
                     db_persisted=(row.dataset_name, f"feedback_{row.id_retroalimentacion}.wav", row.sha256) in registered)
                for row, prediction_id, proposed_by in rows]

    def pending(self, db, limit=50):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Limit must be between 1 and 500")
        return [_snapshot(row) for row in db.query(FeedbackSync)
                .filter_by(status="pending").order_by(
                    FeedbackSync.attempts, FeedbackSync.id_retroalimentacion)
                .limit(limit).all()]
