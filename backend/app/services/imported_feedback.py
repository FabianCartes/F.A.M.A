"""Reviewed, nonarchive local admission. No training, grouping or cloud execution."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
import uuid
import wave

from fastapi import HTTPException
from app.models.dataset_import import DatasetImport, ImportedDataset
from app.models.dataset_import_metadata import (DatasetMember, DatasetSummary,
    ImportClass, ImportFile, ImportSummary)
from app.models.imported_training_source import ImportedModelSource
from app.services.dataset_imports import DatasetImports
from app.services.dataset_import_records import required_summary, dataset_quota, quota_issues
from app.services.feedback_sync import FeedbackSyncQueue
from app.services import storage


def imported_model_id(value):
    """Persisted private model identity accepts only numeric or canonical IDs."""
    value = str(value) if type(value) in (str, int) else ''
    match = re.fullmatch(r'(?:fama_trained_model_)?([1-9][0-9]{0,18})', value)
    return int(match[1]) if match else None


def source_for_prediction(db, prediction):
    """Return DB provenance, None for legacy; malformed imported bindings are 404."""
    if prediction is None:
        return None
    model_id = imported_model_id(prediction.modelo_id)
    from sqlalchemy import inspect
    source = (db.get(ImportedModelSource, model_id) if model_id
              and inspect(db.get_bind()).has_table('imported_model_source') else None)
    imported = (prediction.dataset_name or '').startswith('imported:')
    if source is None:
        if imported:
            raise HTTPException(404, 'Predicción no encontrada.')
        return None
    dataset = db.get(ImportedDataset, source.dataset_id)
    if (dataset is None or dataset.owner_id != source.owner_id
            or prediction.dataset_name != 'imported:' + source.dataset_id):
        raise HTTPException(404, 'Predicción no encontrada.')
    return source


def approve(service, db, feedback, *, owner_id, dataset_name, curation_source_id):
    """Commit membership/revision/processed/queue together under both writer locks."""
    source = source_for_prediction(db, feedback.prediccion)
    if type(owner_id) is not int or owner_id != source.owner_id:
        raise HTTPException(404, 'Predicción no encontrada.')
    if curation_source_id is not None:
        raise HTTPException(422, 'Completa la procedencia al preparar el siguiente entrenamiento.')
    if dataset_name is not None and dataset_name != feedback.prediccion.dataset_name:
        raise HTTPException(409, 'El destino no puede cambiar respecto a la inferencia.')
    root = service.import_root or os.environ.get('FAMA_IMPORT_ROOT')
    if not root:
        raise HTTPException(503, 'Configura el almacenamiento de importaciones.')
    imports = DatasetImports(Path(root))
    from app.services.feedback import FeedbackService, _filesystem_lock
    objects = FeedbackService(Path(root))
    queue = FeedbackSyncQueue()
    # This is the same raw intent used by reject/record: neither can race past
    # a durable admission intention. Imported mutation remains held through commit.
    service._mkdir(service.raw_data_dir)
    intent = service._intent_path(feedback.id_retroalimentacion)
    service._safe_path(intent)
    service._safe_path(intent.with_suffix('.json.lock'))
    with _filesystem_lock(intent.with_suffix('.json.lock')):
        with imports.mutation(db):
            from app.services.dataset_import_jobs import _gate
            _gate(db)
            db.refresh(feedback)
            pred = feedback.prediccion
            db.refresh(pred)
            current = source_for_prediction(db, pred)
            if current.owner_id != owner_id:
                raise HTTPException(404, 'Predicción no encontrada.')
            dataset = imports.dataset(db, owner_id, current.dataset_id)
            label = pred.etiqueta_predicha if feedback.fue_correcta else feedback.etiqueta_corregida
            storage.validate_path_component(label)
            filename = f'feedback_{feedback.id_retroalimentacion}.wav'
            identity = dict(dataset=pred.dataset_name, class_name=label, source=pred.ruta_audio_prueba,
                            owner_id=owner_id, dataset_id=dataset.id, model_id=current.model_id)
            recorded = json.loads(intent.read_text()) if intent.exists() else None
            if recorded and any(recorded.get(k) != v for k, v in identity.items()):
                raise HTTPException(409, 'La identidad de incorporación cambió.')
            existing = queue.get(db, feedback.id_retroalimentacion)
            if feedback.procesado and existing is None:
                raise HTTPException(409, 'La retroalimentación ya fue finalizada.')
            origin_id = recorded['origin_id'] if recorded else uuid.uuid4().hex
            storage.validate_path_component(origin_id)
            destination = service.raw_data_dir / pred.dataset_name / label / filename
            service._safe_path(destination)
            object_path = imports.root / 'objects' / origin_id / filename
            objects._safe_path(object_path)
            if recorded and object_path.exists():
                audio = object_path.read_bytes()
            elif pred.ruta_audio_prueba.startswith('local_predictions/'):
                from app.services.local_prediction_audio import LocalPredictionAudio
                audio = LocalPredictionAudio(root).read(owner_id, pred.ruta_audio_prueba)
            else:
                # Existing managed cloud sources remain readable unchanged.
                audio = storage.download_prediction_audio(pred.ruta_audio_prueba)
            digest = hashlib.sha256(audio).hexdigest()
            if recorded and digest != recorded['sha256']:
                raise HTTPException(409, 'El audio cambió respecto a la intención.')
            with wave.open(io.BytesIO(audio), 'rb') as wav:
                rate, frames = wav.getframerate(), wav.getnframes()
                if rate <= 0 or frames <= 0 or len(wav.readframes(frames)) != frames * wav.getnchannels() * wav.getsampwidth():
                    raise ValueError('Audio WAV vacío o incompleto')
                duration = frames / rate
            prior = db.query(DatasetMember).filter_by(dataset_id=dataset.id, sha256=digest).first()
            if prior and prior.source_import_id != origin_id:
                raise HTTPException(409, 'El audio exacto ya pertenece al dataset.')
            quota = dataset_quota(db, dataset, len(audio) if prior is None else 0,
                                  int(prior is None), imports.limits)
            if quota_issues(quota):
                raise HTTPException(409, 'El audio supera la cuota del dataset.')
            if prior is None:
                imports.space(len(audio))
            if not recorded:
                recorded = dict(identity, origin_id=origin_id, sha256=digest)
                service._publish(intent, json.dumps(recorded).encode())
            # Never delete a retry object or overwrite a conflicting destination.
            for publisher, path in ((objects, object_path), (service, destination)):
                publisher._mkdir(path.parent)
                if path.exists():
                    if path.read_bytes() != audio:
                        raise HTTPException(409, 'Integridad local incompatible.')
                    with path.open('rb') as stream:
                        os.fsync(stream.fileno())
                    publisher._fsync_dir(path.parent)
                else:
                    publisher._publish(path, audio, no_replace=True)
            if prior is None:
                origin = dict(kind='feedback', feedback_id=feedback.id_retroalimentacion,
                              prediction_id=pred.id_prediccion)
                db.add(DatasetImport(id=origin_id, owner_id=owner_id,
                    request_key=f'feedback:{feedback.id_retroalimentacion}',
                    request=dict(origin=origin, target_id=dataset.id), status='imported',
                    sync_status='pending', created_at=time.time(), archive_sha256=None,
                    preview_token=None, dataset_id=dataset.id, added_count=1))
                db.flush()
                metadata = dict(source_import_id=origin_id, class_name=label,
                    original_path=filename, selected_root='', relative_path=f'{label}/{filename}',
                    sha256=digest, size_bytes=len(audio), stored_name=filename,
                    sample_rate=rate, duration_seconds=duration, sync_status='pending',
                    legacy_metadata=dict(origin=origin))
                dataset.revision += 1
                db.add(DatasetMember(id=uuid.uuid4().hex, dataset_id=dataset.id,
                    dataset_revision=dataset.revision, **metadata))
                db.add(ImportFile(id=uuid.uuid4().hex, import_id=origin_id, ordinal=0,
                    duplicate=False, existing=False, **metadata))
                db.add(ImportClass(id=uuid.uuid4().hex, import_id=origin_id, ordinal=0, class_name=label))
                db.add(ImportSummary(import_id=origin_id, preview=dict(origin=origin),
                    file_count=1, class_count=1, error_count=0, warning_count=0,
                    total_size_bytes=len(audio)))
                summary = required_summary(db, DatasetSummary, dataset.id)
                summary.revision = dataset.revision
                summary.file_count += 1
                summary.total_size_bytes += len(audio)
                db.flush()
                summary.class_count = db.query(DatasetMember.class_name).filter_by(dataset_id=dataset.id).distinct().count()
            sync = queue.enqueue(db, feedback.id_retroalimentacion, dataset_name=pred.dataset_name,
                                 storage_class=label, sha256=digest)
            feedback.procesado = True
            db.commit()
            return dict(status='approved', id_retroalimentacion=feedback.id_retroalimentacion,
                destination_path=str(destination), clase=label, filename=filename,
                local_status='incorporated', sync_status=sync.status)
