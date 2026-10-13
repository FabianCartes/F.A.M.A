import os
import random
import sys
import time
import uuid
import hashlib
import json
import soundfile as sf
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

import numpy as np
import torch
import psutil
from sqlalchemy.orm import Session

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.database import SessionLocal
from app.models.dataset import ConjuntoDatos, Audio
from app.models.training import Modelo, MetricaEntrenamiento, ModelEvaluation
from app.services.evaluations import EvaluationService
from app.services.recording_evaluator import (
    LabelledRecording, RecordingEvaluator, validate_recording_splits, REJECTION_LABEL,
)
from app.services.predictors import trained_predictor as published_predictor
from app.schemas.evaluation import strict_json
import pandas as pd
import gc
from torch.utils.data import DataLoader
from poc.preprocess import (
    GPUAudioFrontEnd, GPUSpecAugment, build_gpu_audio_frontend_contract,
)
from poc.train import BioacousticModel, AudioCNN, AudioDataset, FocalLoss, apply_mixup
from training.prepare_data import load_prepared_dataset
from training.paths import (
    get_raw_data_dir, get_dataset_roots, get_training_raw_read_root,
    get_training_prepared_read_dir,
)
from training.schemas.config import AudioConfig
from training.pipelines.dataset import GenericAudioDataset
from dataset_references import resolve_reference

ARCHITECTURE_PRESETS: Dict[str, Dict[str, Any]] = {
    "EfficientNet-B0": {"lr": 0.001, "epochs": 10, "batch": 16},
    "ConvNeXt-Nano": {"lr": 0.0005, "epochs": 12, "batch": 16},
    "ResNet-34d": {"lr": 0.0003, "epochs": 15, "batch": 8},
    "PANNs-CNN14": {"lr": 0.0005, "epochs": 15, "batch": 16},
    "AudioCNN": {"lr": 0.001, "epochs": 20, "batch": 32},
}

TRIAD_ARCHITECTURES: List[str] = ["EfficientNet-B0", "ConvNeXt-Nano", "ResNet-34d"]
ENGINE_TRIAD_ARCHITECTURES: List[str] = ["ResNet-34d", "EfficientNet-B0", "PANNs-CNN14"]
SUPPORTED_DATASETS = frozenset({"AvesChilenas", "engine_diagnostics"})


def _json_config(value):
    if value is None:
        return None
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    elif not isinstance(value, dict):
        value = vars(value)
    return strict_json(value)


class _AcceptedAudioDataset(AudioDataset):
    """Keep bioacoustic transforms and revalidate canonical references on access."""

    def __init__(self, *args, roots, **kwargs):
        self.roots = dict(roots)
        super().__init__(*args, roots=self.roots, **kwargs)

    def _resolve_file_path(self, row: pd.Series) -> Path:
        return resolve_reference(row["file_path"], row["file_stage"], self.roots)


class TrainingService:
    """
    Servicio profundo de orquestación del ciclo de entrenamiento bioacústico (RF_04).
    Cumple con los Casos de Uso CU_INV_02, CU_INV_03, CU_INV_04 y CU_INV_05 de la tesis:
    - Ejecuta pipelines de entrenamiento asíncronos en segundo plano sin bloquear FastAPI.
    - Soporta parada segura (graceful stop / abort) requerida por CU_INV_03.
    - Reporta telemetría de hardware en tiempo real (GPU CUDA / VRAM / CPU / RAM).
    - Persiste modelos y curvas de métricas época a época en PostgreSQL (Tablas 6.6 y 6.7).
    - Saves durable local checkpoints (.pt); does not upload checkpoints to GCS.
    """

    def __init__(self, checkpoints_dir: Optional[Path] = None):
        self.checkpoints_dir = Path(checkpoints_dir or (_BACKEND_DIR / "checkpoints"))
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        # Estado global del entrenamiento
        self._lock = threading.Lock()
        self.status = "idle"  # idle | training | evaluating | completed | failed | stopped
        self.current_job_id: Optional[str] = None
        self.current_epoch: int = 0
        self.total_epochs: int = 0
        self.current_train_loss: float = 0.0
        self.current_val_loss: float = 0.0
        self.current_train_acc: float = 0.0
        self.current_val_acc: float = 0.0
        self.metrics_history: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []
        self.error_message: Optional[str] = None
        self.start_timestamp: Optional[float] = None
        self._stop_requested: bool = False

    def _add_log(self, level: str, message: str) -> None:
        entry = {
            "id": uuid.uuid4().hex[:8],
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        self.logs.append(entry)
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def get_hardware_status(self) -> Dict[str, Any]:
        """
        Retorna la telemetría de hardware para el monitor de entrenamiento (Figura 6.8).
        Detecta dinámicamente si CUDA está disponible o si opera en CPU con memoria RAM física.
        Calcula el nivel de carga real de RAM y CPU para advertir de sobrecarga.
        """
        cuda_avail = torch.cuda.is_available()
        cpu_pct = psutil.cpu_percent(interval=None) or 0.0
        cpu_cores = psutil.cpu_count(logical=True) or 1
        mem = psutil.virtual_memory()
        host_ram_total = mem.total / (1024**3)
        host_ram_used = mem.used / (1024**3)
        host_ram_pct = mem.percent

        temp_c = None
        if cuda_avail:
            device_name = torch.cuda.get_device_name(0)
            total_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            allocated = torch.cuda.memory_allocated(0) / (1024**3)
            reserved = torch.cuda.memory_reserved(0) / (1024**3)
            used_mem = max(allocated, reserved)
            mem_pct = round((used_mem / total_mem) * 100, 1) if total_mem > 0 else 0.0
            try:
                import pynvml
                pynvml.nvmlInit()
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                temp_c = int(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
            except Exception:
                temp_c = None
        else:
            device_name = f"CPU Node Host ({cpu_cores} núcleos)"
            total_mem = host_ram_total
            used_mem = host_ram_used
            mem_pct = host_ram_pct
            temp_c = None

        # Nivel de saturación de hardware (Punto 5)
        if mem_pct >= 90.0 or cpu_pct >= 90.0:
            load_status = "Sobresaturado"
            load_level = "danger"
        elif mem_pct >= 75.0 or cpu_pct >= 75.0:
            load_status = "Carga Alta"
            load_level = "warning"
        else:
            load_status = "Carga Normal"
            load_level = "normal"

        return {
            "cuda_available": cuda_avail,
            "device_name": device_name,
            "vram_total_gb": round(total_mem, 2),
            "vram_used_gb": round(used_mem, 2),
            "vram_percent": round(mem_pct, 1),
            "cpu_percent": round(cpu_pct, 1),
            "cpu_cores": cpu_cores,
            "host_ram_total_gb": round(host_ram_total, 2),
            "host_ram_used_gb": round(host_ram_used, 2),
            "host_ram_percent": round(host_ram_pct, 1),
            "temperature_c": temp_c,
            "load_status": load_status,
            "load_level": load_level,
            "status": "ready" if self.status != "training" else "busy",
        }

    def get_available_datasets(self, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """
        Lista los datasets disponibles para seleccionar como origen de entrenamiento (CU_INV_02).
        Only registered, supported identities are offered; start still validates local data.
        """
        raw_dir = get_raw_data_dir()
        datasets = []

        # 1. Consultar base de datos PostgreSQL si está conectada
        if db is not None:
            try:
                db_datasets = db.query(ConjuntoDatos).all()
                for ds in db_datasets:
                    if ds.nombre not in SUPPORTED_DATASETS:
                        continue
                    classes = []
                    try:
                        classes_query = db.query(Audio.clase).filter(Audio.id_conjunto_datos == ds.id_conjunto_datos).distinct().all()
                        classes = [c[0] for c in classes_query if c[0]]
                    except Exception:
                        pass

                    if not classes:
                        ds_raw_folder = raw_dir / ds.nombre
                        if ds_raw_folder.is_dir():
                            classes = [p.name for p in ds_raw_folder.iterdir() if p.is_dir()]

                    if not classes and ds.nombre == "AvesChilenas":
                        classes = ["Canastero", "Chercán", "Chincol", "Chucao", "Churrín de la Mocha",
                                   "Churrín del sur", "Colilarga", "Fío-fío", "Picaflor chico", "Rayadito",
                                   "Tapaculo", "Tijeral", "Tordo", "Turca", "Zorzal patagónico"]

                    datasets.append({
                        "id": ds.nombre,
                        "name": f"{ds.nombre} ({ds.cantidad_audios} audios)",
                        "audio_count": ds.cantidad_audios,
                        "class_count": len(classes) or 15,
                        "classes": classes,
                        "size_mb": round((ds.tamano_total_bytes or 0) / (1024 * 1024), 1),
                        "estado": ds.estado,
                        "db_id": ds.id_conjunto_datos,
                    })
            except Exception:
                pass

        return datasets

    def get_progress(self) -> Dict[str, Any]:
        """
        Retorna una instantánea del progreso del entrenamiento en tiempo real para el sondeo de la UI.
        """
        with self._lock:
            elapsed = round(time.time() - self.start_timestamp, 1) if self.start_timestamp else 0.0
            return {
                "status": self.status,
                "job_id": self.current_job_id,
                "is_tri_model": getattr(self, "is_tri_model", False),
                "current_model_index": getattr(self, "current_model_index", 1),
                "total_models": getattr(self, "total_models", 1),
                "current_architecture": getattr(self, "current_architecture", ""),
                "models_config": getattr(self, "models_config", []),
                "epoch": self.current_epoch,
                "total_epochs": self.total_epochs,
                "train_loss": self.current_train_loss,
                "val_loss": self.current_val_loss,
                "train_acc": self.current_train_acc,
                "val_acc": self.current_val_acc,
                "metrics_history": list(self.metrics_history),
                "logs": list(self.logs),
                "elapsed_seconds": elapsed,
                "error_message": self.error_message,
            }

    def stop_training(self) -> Dict[str, Any]:
        """
        Solicita la interrupción cooperativa segura del entrenamiento en ejecución (CU_INV_03 Paso 2.a).
        """
        with self._lock:
            if self.status != "training":
                return {"status": self.status, "message": "No hay ningún entrenamiento activo para detener."}
            self._stop_requested = True
            self._add_log("WARN", "Solicitud de detención manual recibida. Abortando entrenamiento...")
            return {"status": "stopping", "message": "Detención solicitada. El proceso finalizará de forma segura."}

    def _prepare_source(self, dataset_name: str) -> Dict[str, Any]:
        """Validate and freeze partitions before a job is admitted."""
        roots = get_dataset_roots(dataset_name)
        roots["raw"] = get_training_raw_read_root(dataset_name)
        raw_dir = roots["raw"]
        prepared_dir = get_training_prepared_read_dir(dataset_name)
        try:
            train_df, val_df, test_df = load_prepared_dataset(
                prepared_dir, roots=roots, dataset_name=dataset_name)
        except (ValueError, OSError) as exc:
            raise ValueError(
                f"Dataset '{dataset_name}': preparación ausente o inválida en {prepared_dir}: {exc}"
            ) from exc

        recordings = {}
        for split, frame in (("train", train_df), ("val", val_df), ("test", test_df)):
            if frame.empty or "clase" not in frame or frame["clase"].isna().any():
                raise ValueError(f"Dataset '{dataset_name}': partición {split} vacía o sin clases válidas.")
            if REJECTION_LABEL in set(frame['clase']):
                raise ValueError('La etiqueta reservada de rechazo no puede ser una clase real.')
            if not frame["clase"].map(lambda c: isinstance(c, str) and bool(c.strip())).all():
                raise ValueError(f"Dataset '{dataset_name}': clases inválidas en {split}.")
            if not {"file_path", "file_stage"}.issubset(frame.columns):
                raise ValueError("Índice histórico: se requieren file_path y file_stage; use conversión offline.")
            admitted = []
            for _, row in frame.iterrows():
                try:
                    path = resolve_reference(row["file_path"], row["file_stage"], roots)
                except ValueError as exc:
                    raise ValueError(f"Dataset '{dataset_name}': referencia inválida en {split}: {exc}") from exc
                if path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg"} or path.stat().st_size == 0:
                    raise ValueError(f"Dataset '{dataset_name}': audio ausente o fuera de su fuente en {split}.")
                try:
                    metadata = sf.info(path)
                    if metadata.frames <= 0 or metadata.samplerate <= 0 or metadata.channels <= 0:
                        raise ValueError('Audio vacío o metadata de codec inválida')
                except Exception as exc:
                    raise ValueError(f"Dataset '{dataset_name}': audio no decodificable en {split}: {path}") from exc
                if dataset_name == 'AvesChilenas':
                    identity = row.get('xc_id')
                elif 'source_id' in row:
                    source_id = row['source_id']
                    if not isinstance(source_id, str) or not source_id.strip():
                        raise ValueError('Identidad de origen de motor inválida')
                    # Match the prepared reader: importer IDs are class-scoped.
                    identity = json.dumps([row['clase'], source_id], ensure_ascii=False, separators=(',', ':'))
                else:
                    identity = f"{row['file_stage']}:{row['file_path']}"
                group = row.get('recordist')
                if not isinstance(identity, str) or not identity.strip():
                    raise ValueError('Identidad de grabación inválida')
                if group is not None and (not isinstance(group, str) or not group.strip()):
                    raise ValueError('Grupo de grabación inválido')
                admitted.append(LabelledRecording(identity, row['clase'], path,
                                                  row['file_path'], row['file_stage'], group))
            recordings[split] = tuple(admitted)
        for split, frame in (('val', val_df), ('test', test_df)):
            if not set(frame['clase']).issubset(set(train_df['clase'])):
                raise ValueError(f"Dataset '{dataset_name}': clases de {split} ausentes en train.")
        validate_recording_splits(recordings)
        return {"raw_dir": raw_dir, "roots": roots, "train_df": train_df,
                "val_df": val_df, "test_df": test_df, "recordings": recordings}

    def start_training(
        self,
        dataset_name: str,
        architecture: str = "EfficientNet-B0",
        epochs: int = 10,
        learning_rate: float = 1e-3,
        batch_size: int = 16,
        framework: str = "pytorch",
        is_tri_model: bool = False,
        models: Optional[List[Any]] = None,
        audio_config: Optional[Any] = None,
        windowing_config: Optional[Any] = None,
        regularization_config: Optional[Any] = None,
        weight_decay: float = 0.01,
        early_stopping: bool = True,
        seed: int = 42,
    ) -> Dict[str, Any]:
        """
        Inicia un nuevo ciclo de entrenamiento bioacústico en un hilo desacoplado.
        Soporta modo individual, pipeline secuencial de la Tríada Completa o Ensamble Dinámico (1 a 3 modelos),
        y parametrización universal multi-dominio de audio, ventaneo y regularización.
        """
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise ValueError("seed debe ser un entero entre 0 y 2**32 - 1.")

        with self._lock:
            if self.status in {"training", "evaluating"}:
                raise RuntimeError("Ya existe un proceso de entrenamiento en ejecución.")

            try:
                if dataset_name not in SUPPORTED_DATASETS:
                    raise ValueError(f"Dataset '{dataset_name}' no soportado para entrenamiento.")
                with SessionLocal() as db:
                    matches = [ds for ds in db.query(ConjuntoDatos).filter_by(nombre=dataset_name).all()
                               if ds.nombre == dataset_name]
                    if len(matches) != 1:
                        raise ValueError(f"Dataset '{dataset_name}' requiere un registro exacto y único.")
                    dataset_id = matches[0].id_conjunto_datos
                source = self._prepare_source(dataset_name)
                audio_config = _json_config(audio_config)
                windowing_config = _json_config(windowing_config)
                regularization_config = _json_config(regularization_config)
            except Exception as exc:
                self.status = "failed"
                self.current_job_id = None
                self.error_message = f"Dataset '{dataset_name}': {exc}"
                self.start_timestamp = None
                self.current_epoch = 0
                self.total_epochs = 0
                self.metrics_history = []
                self.logs = []
                self._add_log("ERROR", self.error_message)
                raise ValueError(self.error_message) from exc

            is_engine = dataset_name == "engine_diagnostics"
            triad_list = ENGINE_TRIAD_ARCHITECTURES if is_engine else TRIAD_ARCHITECTURES

            if models is not None and len(models) > 0:
                resolved_models = []
                for m in models:
                    if isinstance(m, dict):
                        m_epochs = m.get("epochs")
                        m_lr = m.get("learning_rate")
                        m_batch = m.get("batch_size")
                        resolved_models.append({
                            "architecture": m["architecture"],
                            "weight": float(m.get("weight", 1.0)),
                            "epochs": int(m_epochs) if m_epochs is not None else None,
                            "learning_rate": float(m_lr) if m_lr is not None else None,
                            "batch_size": int(m_batch) if m_batch is not None else None,
                        })
                    else:
                        m_epochs = getattr(m, "epochs", None)
                        m_lr = getattr(m, "learning_rate", None)
                        m_batch = getattr(m, "batch_size", None)
                        resolved_models.append({
                            "architecture": getattr(m, "architecture"),
                            "weight": float(getattr(m, "weight", 1.0)),
                            "epochs": int(m_epochs) if m_epochs is not None else None,
                            "learning_rate": float(m_lr) if m_lr is not None else None,
                            "batch_size": int(m_batch) if m_batch is not None else None,
                        })
                is_ensemble = len(resolved_models) > 1
            elif is_tri_model:
                resolved_models = [{"architecture": a, "weight": 1.0 / len(triad_list)} for a in triad_list]
                is_ensemble = True
            else:
                resolved_models = [{"architecture": architecture, "weight": 1.0}]
                is_ensemble = False

            mode_tag = "ensemble" if is_ensemble else resolved_models[0]["architecture"].lower().replace('-', '_')
            job_id = f"fama_{mode_tag}_{uuid.uuid4().hex}"
            self.current_job_id = job_id
            self.status = "training"
            self.is_tri_model = is_tri_model or (len(resolved_models) == 3)
            self.models_config = resolved_models
            self.total_models = len(resolved_models)
            self.current_model_index = 1
            self.current_architecture = resolved_models[0]["architecture"]
            self.current_epoch = 0
            self.total_epochs = max(1, epochs)
            self.current_train_loss = 0.0
            self.current_val_loss = 0.0
            self.current_train_acc = 0.0
            self.current_val_acc = 0.0
            self.metrics_history = []
            self.logs = []
            self.error_message = None
            self.start_timestamp = time.time()
            self._stop_requested = False

        config = {
            "job_id": job_id,
            "dataset_name": dataset_name,
            "dataset_id": dataset_id,
            "source": source,
            "architecture": architecture,
            "epochs": self.total_epochs,
            "learning_rate": learning_rate,
            "batch_size": batch_size,
            "framework": framework,
            "is_tri_model": self.is_tri_model,
            "models": resolved_models,
            "audio_config": audio_config,
            "windowing_config": windowing_config,
            "regularization_config": regularization_config,
            "weight_decay": weight_decay,
            "early_stopping": early_stopping,
            "seed": seed,
        }

        # Lanzar en hilo de fondo para no bloquear el servidor FastAPI
        thread = threading.Thread(
            target=self._run_training_worker,
            args=(config,),
            daemon=True,
            name=f"TrainingWorker-{job_id}",
        )
        thread.start()

        if is_ensemble:
            arch_summary = " -> ".join([m["architecture"] for m in resolved_models])
            msg = f"Pipeline de Ensamble ({len(resolved_models)} modelos: {arch_summary}) iniciado."
        else:
            msg = f"Entrenamiento de {resolved_models[0]['architecture']} iniciado para {self.total_epochs} épocas."

        return {
            "status": "started",
            "job_id": job_id,
            "message": msg,
        }


    def _build_model_instance(self, arch: str, num_classes: int, device: torch.device) -> torch.nn.Module:
        arch_lower = arch.lower().replace("-", "_")
        if "audiocnn" in arch_lower or "audio_cnn" in arch_lower:
            model = AudioCNN(num_classes=num_classes).to(device)
            model._fama_initialization_mode = "constructor_default"
            return model
        elif "panns" in arch_lower:
            from training.models.panns_cnn14 import PannsCNN14
            model = PannsCNN14(in_chans=1, num_classes=num_classes).to(device)
            model._fama_initialization_mode = "constructor_default"
            return model
        elif "resnet" in arch_lower:
            target_arch = "resnet34d"
        elif "convnext" in arch_lower:
            target_arch = "convnext_nano"
        elif "efficient" in arch_lower:
            target_arch = "efficientnet_b0"
        else:
            target_arch = arch_lower

        model = BioacousticModel(model_name=target_arch, num_classes=num_classes, pretrained=True, in_chans=1).to(device)
        model._fama_initialization_mode = "pretrained_constructor"
        return model

    def _write_checkpoint(self, path: Path, payload: Dict[str, Any]) -> tuple:
        """Publish a durable local checkpoint without replacing an existing file."""
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        owned_temporary = published = False
        try:
            with temporary.open("xb") as output:
                owned_temporary = True
                torch.save(payload, output)
                output.flush()
                os.fsync(output.fileno())
            file_size = temporary.stat().st_size
            if not file_size:
                raise RuntimeError("Checkpoint local vacío.")
            file_hash = hashlib.sha256(temporary.read_bytes()).hexdigest()
            # A same-directory hard link publishes atomically and fails on collision.
            os.link(temporary, path)
            published = True
            temporary.unlink()
            owned_temporary = False
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return file_size, file_hash
        except Exception:
            if owned_temporary:
                temporary.unlink(missing_ok=True)
            if published:
                path.unlink(missing_ok=True)
            raise

    def _evaluation_config(self, config, training_audio, preprocessing_contract=None):
        """Use the shared effective inference provenance builder."""
        from app.services.standard_evaluation_guard import build_evaluation_configuration

        settings = build_evaluation_configuration(config, training_audio, preprocessing_contract)
        if settings[0]['training_mismatch']:
            self._add_log('WARN', 'Discrepancia training/predictor: evaluación usa configuración publicada, sin cambiar filtros ni ventanas.')
        return settings

    @staticmethod
    def _checkpoint_hash(path):
        from app.services.standard_evaluation_guard import checkpoint_sha256
        return checkpoint_sha256(path)

    def _require_standard_reports(self, target, db):
        """Delegate standard-artifact eligibility to the shared integrity guard."""
        from app.services.standard_evaluation_guard import require_standard_reports
        require_standard_reports(target, db, self.checkpoints_dir)

    def _evaluate_registered_checkpoint(self, model_id, checkpoint_path, checkpoint_hash,
                                        config, classes, training_audio, preprocessing_contract,
                                        is_ensemble, architecture):
        """Registration is durable first; evaluation errors preserve the artifact."""
        with self._lock:
            self.status = 'evaluating'
        attempt_ids = []
        previous_active_ids = None
        try:
            if self._checkpoint_hash(checkpoint_path) != checkpoint_hash:
                raise ValueError('Checkpoint cambió antes de evaluación')
            predictor = published_predictor.TrainedModelPredictor(
                checkpoint_path, model_id=str(model_id), dataset_name=config['dataset_name'], lazy_load=True)
            if list(predictor.classes) != classes:
                raise ValueError('Clases restauradas distintas de la fuente admitida')
            if self._checkpoint_hash(checkpoint_path) != checkpoint_hash:
                raise ValueError('Checkpoint cambió durante restauración')
            for split in ('val', 'test'):
                for record in config['source']['recordings'][split]:
                    resolved = resolve_reference(record.reference, record.stage, config['source']['roots'])
                    if resolved != record.path:
                        raise ValueError('Referencia admitida cambió antes de evaluación')
            settings = self._evaluation_config(
                {**config, 'architecture': architecture}, training_audio, preprocessing_contract)
            evaluators = [RecordingEvaluator(config['source']['recordings'][split], predictor,
                id_modelo=model_id, dataset=config['dataset_name'], split=split,
                checkpoint_sha256=checkpoint_hash, predictor_config=settings[0],
                preprocessing_config=settings[1], aggregation_config=settings[2]) for split in ('val', 'test')]
            from app.services.standard_evaluation_guard import (
                ADMITTED_MANIFEST_PAIR_KEY, admitted_manifest_pair_provenance,
            )
            pair_provenance = admitted_manifest_pair_provenance(
                evaluators[0].identity.manifest_sha256, evaluators[1].identity.manifest_sha256)
            evaluation_identities = []
            for evaluator in evaluators:
                identity = evaluator.identity.model_dump()
                identity['predictor_config'] = {
                    **identity['predictor_config'], ADMITTED_MANIFEST_PAIR_KEY: pair_provenance,
                }
                evaluation_identities.append(identity)
            with SessionLocal() as evaluation_db:
                service = EvaluationService(evaluation_db)
                for identity in evaluation_identities:
                    attempt_ids.append(service.create(identity)['id_evaluation'])
                for attempt_id, evaluator in zip(attempt_ids, evaluators):
                    service.start(attempt_id)
                    report = evaluator.evaluate()
                    if self._checkpoint_hash(checkpoint_path) != checkpoint_hash:
                        raise ValueError('Checkpoint cambió durante inferencia')
                    service.complete(attempt_id, report)
            with SessionLocal() as publication_db:
                target = publication_db.get(Modelo, model_id)
                target.estado = 'standard_eval_completed'
                self._require_standard_reports(target, publication_db)
                if is_ensemble:
                    target.estado = 'standard_component_evaluated'
                else:
                    previous_active_ids = [row.id_modelo for row in publication_db.query(Modelo)
                                           .filter(Modelo.activo.is_(True), Modelo.id_modelo != model_id)
                                           .with_for_update().all()]
                    publication_db.query(Modelo).filter(Modelo.id_modelo != model_id).update({Modelo.activo: False})
                    target.activo = True
                publication_db.commit()
        except Exception as exc:
            try:
                with SessionLocal() as failure_db:
                    service = EvaluationService(failure_db)
                    rows = failure_db.query(ModelEvaluation).filter_by(id_modelo=model_id).all()
                    for row in rows:
                        if ((row.id_evaluation in attempt_ids or row.predictor_config.get('job_id') == config['job_id'])
                                and row.status in ('pending', 'running')):
                            service.fail(row.id_evaluation, str(exc).strip()[:2000] or type(exc).__name__)
                    target = failure_db.get(Modelo, model_id)
                    target.estado = 'standard_eval_failed'
                    target.activo = False
                    if previous_active_ids is not None:
                        # Compensation after a possibly committed publication, not
                        # a promise of filesystem/DB atomicity or guaranteed recovery.
                        failure_db.query(Modelo).filter(Modelo.id_modelo.in_(previous_active_ids)).update({Modelo.activo: True})
                    failure_db.commit()
            except Exception as failure_error:
                self._add_log('WARN', f'No se pudo persistir fallo de evaluación: {failure_error}; checkpoint conservado.')
            raise
        finally:
            with self._lock:
                if self.status == 'evaluating':
                    self.status = 'training'

    def _run_training_worker(self, config: Dict[str, Any]) -> None:
        """
        Worker que ejecuta las épocas de entrenamiento reales en PyTorch (GPU CUDA / CPU),
        calcula las métricas reales época a época, guarda el checkpoint binario con pesos
        y persiste los resultados en PostgreSQL.
        """
        seed = config["seed"]
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

        job_id = config["job_id"]
        dataset_name = config["dataset_name"]
        is_tri_model = config.get("is_tri_model", False)
        is_engine = dataset_name == "engine_diagnostics"

        if "models" in config and config["models"]:
            models_to_train = [m["architecture"] for m in config["models"]]
            model_weights = {m["architecture"]: m.get("weight", 1.0) for m in config["models"]}
            model_epochs_list = [m.get("epochs") for m in config["models"]]
            model_lr_list = [m.get("learning_rate") for m in config["models"]]
            model_batch_list = [m.get("batch_size") for m in config["models"]]
        else:
            triad_list = ENGINE_TRIAD_ARCHITECTURES if is_engine else TRIAD_ARCHITECTURES
            models_to_train = triad_list if is_tri_model else [config["architecture"]]
            model_weights = {a: 1.0 / len(models_to_train) for a in models_to_train}
            model_epochs_list = [None for _ in models_to_train]
            model_lr_list = [None for _ in models_to_train]
            model_batch_list = [None for _ in models_to_train]


        is_ensemble = len(models_to_train) > 1

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        device_str = device.type

        if is_ensemble:
            self._add_log("INFO", f"Iniciando Pipeline de Ensamble ({len(models_to_train)} modelos) para '{dataset_name}' en {device_str.upper()}.")
            self._add_log("INFO", f"Plan de ejecución secuencial: {' -> '.join(models_to_train)}")
        else:
            self._add_log("INFO", f"Iniciando pipeline en dispositivo: {device_str.upper()}. Arquitectura: {config['architecture']}")

        try:
            # Consume the admitted source snapshot, never re-resolve another dataset.
            source = config["source"]
            raw_dir = source["raw_dir"]
            train_df, val_df = source["train_df"], source["val_df"]
            classes = sorted(train_df["clase"].unique().tolist())
            label_to_idx = {c: i for i, c in enumerate(classes)}
            from app.services.standard_evaluation_guard import resolve_training_audio
            training_audio = resolve_training_audio(dataset_name, config.get("audio_config"))
            target_sr, duration_seconds, n_mels, n_fft, hop_length, f_min, f_max = (
                training_audio[key] for key in (
                    "target_sr", "duration_seconds", "n_mels", "n_fft", "hop_length", "f_min", "f_max"))
            preprocessing_contract = build_gpu_audio_frontend_contract(
                sample_rate=target_sr, duration_seconds=duration_seconds, n_mels=n_mels,
                n_fft=n_fft, hop_length=hop_length, f_min=f_min, f_max=f_max)

            self._add_log(
                "INFO",
                f"Dataset '{dataset_name}' preparado con éxito: {len(train_df)} audios de train, "
                f"{len(val_df)} audios de val | {len(classes)} clases detectadas."
            )

            for idx, arch in enumerate(models_to_train):
                if self._stop_requested:
                    break

                preset = ARCHITECTURE_PRESETS.get(arch, {})
                custom_epochs = model_epochs_list[idx] if idx < len(model_epochs_list) else None
                if custom_epochs is not None:
                    arch_epochs = int(custom_epochs)
                elif is_ensemble:
                    arch_epochs = preset.get("epochs", config["epochs"])
                else:
                    arch_epochs = config["epochs"]
                custom_lr = model_lr_list[idx] if idx < len(model_lr_list) else None
                if custom_lr is not None:
                    arch_lr = float(custom_lr)
                elif is_ensemble:
                    arch_lr = preset.get("lr", config["learning_rate"])
                else:
                    arch_lr = config["learning_rate"]

                custom_batch = model_batch_list[idx] if idx < len(model_batch_list) else None
                if custom_batch is not None:
                    arch_batch = int(custom_batch)
                elif is_ensemble:
                    arch_batch = preset.get("batch", config["batch_size"])
                else:
                    arch_batch = config["batch_size"]

                with self._lock:
                    self.current_model_index = idx + 1
                    self.total_models = len(models_to_train)
                    self.current_architecture = arch
                    self.current_epoch = 0
                    self.total_epochs = arch_epochs

                if is_ensemble:
                    self._add_log("INFO", f"[Paso {idx+1}/{len(models_to_train)}] Entrenando {arch} (LR: {arch_lr}, Batch: {arch_batch}, Épocas: {arch_epochs}, Peso: {model_weights.get(arch, 1.0):.2f})...")
                else:
                    self._add_log("INFO", f"Hiperparámetros -> LR: {arch_lr}, Batch: {arch_batch}, Épocas: {arch_epochs}")


                # Instanciar DataLoaders de PyTorch
                if is_engine or config.get("audio_config") is not None:
                    audio_cfg = AudioConfig(
                        target_sr=target_sr,
                        duration_seconds=duration_seconds,
                        n_mels=n_mels,
                        n_fft=n_fft,
                        hop_length=hop_length,
                        f_min=f_min,
                        f_max=f_max,
                    )
                    train_ds = GenericAudioDataset(
                        train_df,
                        roots=source["roots"],
                        audio_config=audio_cfg,
                        label_to_idx=label_to_idx,
                        is_train=True,
                        return_raw_waveform=True,
                    )
                    val_ds = GenericAudioDataset(
                        val_df,
                        roots=source["roots"],
                        audio_config=audio_cfg,
                        label_to_idx=label_to_idx,
                        is_train=False,
                        return_raw_waveform=True,
                    )
                else:
                    train_ds = _AcceptedAudioDataset(
                        train_df,
                        roots=source["roots"],
                        raw_dir=raw_dir,
                        label_to_idx=label_to_idx,
                        target_sr=target_sr,
                        duration_seconds=duration_seconds,
                        n_mels=n_mels,
                        is_train=True,
                        return_raw_waveform=True,
                    )
                    val_ds = _AcceptedAudioDataset(
                        val_df,
                        roots=source["roots"],
                        raw_dir=raw_dir,
                        label_to_idx=label_to_idx,
                        target_sr=target_sr,
                        duration_seconds=duration_seconds,
                        n_mels=n_mels,
                        is_train=False,
                        return_raw_waveform=True,
                    )

                train_loader = DataLoader(
                    train_ds,
                    batch_size=arch_batch,
                    shuffle=True,
                    num_workers=0,
                    pin_memory=(device.type == "cuda"),
                )
                val_loader = DataLoader(
                    val_ds,
                    batch_size=arch_batch,
                    shuffle=False,
                    num_workers=0,
                    pin_memory=(device.type == "cuda"),
                )

                # Frontend espectral y data augmentation en GPU
                frontend = GPUAudioFrontEnd(
                    sample_rate=preprocessing_contract["sample_rate"],
                    **preprocessing_contract["parameters"],
                ).to(device)
                spec_augment = GPUSpecAugment(
                    freq_mask_param=8,
                    time_mask_param=16,
                    prob=0.5,
                ).to(device)

                # Configuración de Regularización y Función de Pérdida
                reg_cfg_input = config.get("regularization_config")
                loss_type = "focal"
                focal_gamma = 2.0
                mixup_enabled = False
                mixup_alpha = 0.2

                if reg_cfg_input:
                    if isinstance(reg_cfg_input, dict):
                        loss_type = reg_cfg_input.get("loss_type", "focal")
                        focal_gamma = float(reg_cfg_input.get("focal_gamma", 2.0))
                        mixup_enabled = bool(reg_cfg_input.get("mixup_enabled", False))
                        mixup_alpha = float(reg_cfg_input.get("mixup_alpha", 0.2))
                    else:
                        loss_type = getattr(reg_cfg_input, "loss_type", "focal")
                        focal_gamma = float(getattr(reg_cfg_input, "focal_gamma", 2.0))
                        mixup_enabled = bool(getattr(reg_cfg_input, "mixup_enabled", False))
                        mixup_alpha = float(getattr(reg_cfg_input, "mixup_alpha", 0.2))

                model = self._build_model_instance(arch, len(classes), device)
                initialization_mode = getattr(model, "_fama_initialization_mode", "unspecified")
                if loss_type == "cross_entropy":
                    criterion = torch.nn.CrossEntropyLoss().to(device)
                else:
                    criterion = FocalLoss(gamma=focal_gamma).to(device)

                weight_decay = float(config.get("weight_decay", 0.01))
                optimizer = torch.optim.AdamW(model.parameters(), lr=arch_lr, weight_decay=weight_decay)
                self._add_log("INFO", f"Optimizador AdamW configurado: lr={arch_lr}, weight_decay={weight_decay}")
                scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=arch_epochs, eta_min=1e-6)

                checkpoint_filename = f"fama_{uuid.uuid4().hex}_best.pt"
                checkpoint_path = self.checkpoints_dir / checkpoint_filename
                best_val_acc = 0.0
                best_weights = None
                early_stopping_enabled = bool(config.get("early_stopping", True))
                patience = max(5, int(arch_epochs * 0.20))
                best_val_loss = float("inf")
                epochs_no_improve = 0

                if early_stopping_enabled:
                    self._add_log(
                        "INFO",
                        f"[{arch}] Early Stopping habilitado (Paciencia: {patience} épocas, métrica: Val Loss)."
                    )
                else:
                    self._add_log(
                        "INFO",
                        f"[{arch}] Early Stopping deshabilitado: El modelo completará las {arch_epochs} épocas fijas."
                    )

                for epoch in range(1, arch_epochs + 1):
                    if self._stop_requested:
                        self._add_log("WARN", f"Entrenamiento interrumpido por el usuario en la época {epoch - 1}.")
                        with self._lock:
                            self.status = "stopped"
                        return

                    t_start_epoch = time.time()
                    model.train()
                    tr_loss_total = 0.0
                    tr_correct = 0
                    tr_samples = 0

                    for x_batch, y_batch in train_loader:
                        if self._stop_requested:
                            break
                        x_batch = x_batch.to(device, non_blocking=True)
                        y_batch = y_batch.to(device, non_blocking=True)

                        mel_batch = frontend(x_batch)
                        mel_batch = spec_augment(mel_batch)

                        if mixup_enabled and mixup_alpha > 0.0:
                            mel_batch, y_a, y_b, lam = apply_mixup(mel_batch, y_batch, alpha=mixup_alpha, prob=1.0)
                            optimizer.zero_grad()
                            outputs = model(mel_batch)
                            if lam < 1.0:
                                loss = lam * criterion(outputs, y_a) + (1.0 - lam) * criterion(outputs, y_b)
                            else:
                                loss = criterion(outputs, y_batch)
                        else:
                            optimizer.zero_grad()
                            outputs = model(mel_batch)
                            loss = criterion(outputs, y_batch)

                        loss.backward()
                        optimizer.step()

                        bsz = x_batch.size(0)
                        tr_loss_total += float(loss.item()) * bsz
                        preds = torch.argmax(outputs, dim=-1)
                        tr_correct += int(torch.sum(preds == y_batch).item())
                        tr_samples += bsz

                    if self._stop_requested:
                        self._add_log("WARN", f"Entrenamiento interrumpido por el usuario en la época {epoch}.")
                        with self._lock:
                            self.status = "stopped"
                        return

                    if tr_samples > 0:
                        scheduler.step()
                    tr_loss = round(tr_loss_total / max(1, tr_samples), 4)
                    tr_acc = round((tr_correct / max(1, tr_samples)) * 100.0, 2)

                    # Validación
                    model.eval()
                    val_loss_total = 0.0
                    val_correct = 0
                    val_samples = 0

                    with torch.no_grad():
                        for x_batch, y_batch in val_loader:
                            if self._stop_requested:
                                break
                            x_batch = x_batch.to(device, non_blocking=True)
                            y_batch = y_batch.to(device, non_blocking=True)
                            mel_batch = frontend(x_batch)
                            outputs = model(mel_batch)
                            loss = criterion(outputs, y_batch)
                            bsz = x_batch.size(0)
                            val_loss_total += float(loss.item()) * bsz
                            preds = torch.argmax(outputs, dim=-1)
                            val_correct += int(torch.sum(preds == y_batch).item())
                            val_samples += bsz

                    val_loss = round(val_loss_total / max(1, val_samples), 4)
                    val_acc = round((val_correct / max(1, val_samples)) * 100.0, 2)
                    epoch_time = round(time.time() - t_start_epoch, 2)

                    if val_loss < best_val_loss - 1e-4:
                        best_val_loss = val_loss
                        epochs_no_improve = 0
                    else:
                        epochs_no_improve += 1

                    if val_acc > best_val_acc:
                        best_val_acc = val_acc
                        best_weights = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                    elif best_weights is None:
                        best_weights = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

                    metric_entry = {
                        "epoca": epoch,
                        "architecture": arch,
                        "model_index": idx + 1,
                        "train_loss": tr_loss,
                        "val_loss": val_loss,
                        "train_acc": tr_acc,
                        "val_acc": val_acc,
                        "tiempo_epoca": epoch_time,
                    }

                    with self._lock:
                        self.current_epoch = epoch
                        self.current_train_loss = tr_loss
                        self.current_val_loss = val_loss
                        self.current_train_acc = tr_acc
                        self.current_val_acc = val_acc
                        self.metrics_history.append(metric_entry)

                    prefix = f"[{arch}] " if is_ensemble else ""
                    self._add_log(
                        "SUCCESS",
                        f"{prefix}Época {epoch}/{arch_epochs} -> Loss: {tr_loss:.4f} | Val Loss: {val_loss:.4f} | "
                        f"Acc: {tr_acc:.1f}% | Val Acc: {val_acc:.1f}% ({epoch_time}s)"
                    )

                    if early_stopping_enabled and epochs_no_improve >= patience:
                        self._add_log(
                            "WARN",
                            f"[{arch}] Early Stopping activado en época {epoch}/{arch_epochs}: "
                            f"Sin mejora en Val Loss durante {patience} épocas consecutivas. "
                            f"Restaurando mejores pesos (Mejor Val Loss: {best_val_loss:.4f}, Mejor Val Acc: {best_val_acc:.1f}%)."
                        )
                        break

                # Guardar el artefacto de pesos real (.pt)
                saved_state = best_weights if best_weights is not None else {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                checkpoint_payload = {
                    "dataset_id": config["dataset_id"],
                    "dataset_name": dataset_name,
                    "job_id": job_id,
                    "source_directory": str(raw_dir),
                    "model_index": idx + 1,
                    "architecture": arch,
                    "seed": seed,
                    "initialization_mode": initialization_mode,
                    "epochs": arch_epochs,
                    "best_val_acc": best_val_acc,
                    "classes": classes,
                    "ensemble_weight": model_weights.get(arch, 1.0),
                    "ensemble_models": config.get("models"),
                    "audio_config": config.get("audio_config"),
                    "windowing_config": config.get("windowing_config"),
                    "preprocessing_contract": preprocessing_contract,
                    "regularization_config": config.get("regularization_config"),
                    "state_dict": saved_state,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                file_size, file_hash = self._write_checkpoint(checkpoint_path, checkpoint_payload)

                # A checkpoint is successful only after its registration commits.
                db = None
                commit_attempted = False
                try:
                    db = SessionLocal()
                    dataset = db.query(ConjuntoDatos).filter_by(
                        id_conjunto_datos=config["dataset_id"], nombre=dataset_name
                    ).with_for_update().one_or_none()
                    if dataset is None or dataset.nombre != dataset_name or config["dataset_id"] is None:
                        raise RuntimeError("El dataset aceptado ya no tiene un registro de origen válido.")
                    nuevo_modelo = Modelo(
                        id_conjunto_datos=config["dataset_id"],
                        clase_objetivo=f"{len(classes)} Clases ({dataset_name})",
                        arquitectura=arch,
                        epocas=arch_epochs,
                        tasa_aprendizaje=arch_lr,
                        tamano_lote=arch_batch,
                        precision=best_val_acc,
                        perdida=self.current_val_loss,
                        ruta_binario_gcp=f"models/{checkpoint_filename}",
                        tamano_bytes=file_size,
                        hash_binario=file_hash,
                        activo=False,
                        estado="standard_eval_pending",
                    )
                    db.add(nuevo_modelo)
                    db.flush()

                    model_metrics = [
                        m for m in self.metrics_history
                        if m.get("architecture") == arch and m.get("model_index") == idx + 1
                    ]
                    if not model_metrics:
                        raise RuntimeError("No hay métricas de época para registrar el modelo.")
                    for m in model_metrics:
                        rec = MetricaEntrenamiento(
                            id_modelo=nuevo_modelo.id_modelo,
                            epoca=m["epoca"],
                            precision=m["val_acc"],
                            perdida=m["val_loss"],
                            puntuacion_validacion=m["val_acc"],
                            tiempo_epoca=m["tiempo_epoca"],
                        )
                        db.add(rec)

                    model_id = nuevo_modelo.id_modelo
                    commit_attempted = True
                    db.commit()
                    self._add_log("SUCCESS", f"Checkpoint local {checkpoint_filename} ({file_size} bytes), modelo #{model_id} ({arch}) y métricas guardados.")
                except Exception:
                    if db is not None:
                        try:
                            db.rollback()
                        except Exception as rollback_error:
                            self._add_log("WARN", f"No se pudo confirmar rollback: {rollback_error}")
                    # Commit may have succeeded before the connection reported an error.
                    # Delete only this job's newly published, proven unregistered file.
                    unregistered = not commit_attempted
                    if commit_attempted:
                        try:
                            with SessionLocal() as verification:
                                unregistered = verification.query(Modelo).filter_by(
                                    ruta_binario_gcp=f"models/{checkpoint_filename}"
                                ).first() is None
                        except Exception:
                            self._add_log("WARN", f"Checkpoint {checkpoint_filename} conservado: resultado de commit indeterminado.")
                    if unregistered:
                        checkpoint_path.unlink(missing_ok=True)
                    raise
                finally:
                    if db is not None:
                        db.close()

                self._evaluate_registered_checkpoint(
                    model_id, checkpoint_path, file_hash, config, classes, training_audio,
                    preprocessing_contract, is_ensemble, arch)

                # Limpieza de memoria RAM y VRAM antes del siguiente modelo
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()

                if is_ensemble and idx < len(models_to_train) - 1:
                    self._add_log("INFO", f"Memoria liberada exitosamente. Pasando al siguiente modelo ({models_to_train[idx+1]})...")

            if not self._stop_requested:
                with self._lock:
                    self.status = "completed"
                if is_ensemble:
                    self._add_log("SUCCESS", f"Entrenamiento de {len(models_to_train)} componentes finalizado; informes individuales completos. Ensamble combinado sin evaluar ni publicar (EVAL-4).")
                else:
                    self._add_log("SUCCESS", f"Pipeline de modelado finalizado exitosamente. Mejor Val Acc: {best_val_acc:.2f}%")


        except Exception as exc:
            with self._lock:
                self.status = "failed"
                self.error_message = str(exc)
            self._add_log("ERROR", f"Fallo catastrófico en el entrenamiento: {exc}")

    def get_history(self, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """
        Retorna el historial de modelos entrenados enriquecido con la Ficha Técnica (CU_INV_04).
        """
        import re
        from training.pipelines.multitask_mapping import CLASS_NAMES_13

        aves_classes = [
            "Canastero", "Chercán", "Chincol", "Chucao", "Churrín de la Mocha",
            "Churrín del sur", "Colilarga", "Fío-fío", "Picaflor chico", "Rayadito",
            "Tapaculo", "Tijeral", "Tordo", "Turca", "Zorzal patagónico"
        ]
        engine_classes = list(CLASS_NAMES_13)

        history = []
        if db is not None:
            try:
                modelos = db.query(Modelo).order_by(Modelo.fecha_entrenamiento.desc()).all()

                # Para calcular la versión correlativa cronológica (v1, v2, ...) por par (dataset, arquitectura)
                # ordenamos cronológicamente (ascendente)
                from collections import defaultdict
                def _get_sort_key(m_obj):
                    dt = m_obj.fecha_entrenamiento
                    if dt is None:
                        return (0, m_obj.id_modelo or 0)
                    ts = dt.timestamp() if hasattr(dt, "timestamp") else 0
                    return (ts, m_obj.id_modelo or 0)

                modelos_asc = sorted(modelos, key=_get_sort_key)
                pair_counts: Dict[tuple, int] = defaultdict(int)
                calculated_versions: Dict[int, int] = {}

                for m in modelos_asc:
                    filename = Path(m.ruta_binario_gcp).name if m.ruta_binario_gcp else f"modelo_{m.id_modelo}.pt"
                    v_match = re.search(r"_v(\d+)\.pt$", filename)
                    if v_match:
                        v = int(v_match.group(1))
                    else:
                        target_lower = (m.clase_objetivo or "").lower()
                        is_birds = "aves" in target_lower or "chilenas" in target_lower
                        is_engine = "engine" in target_lower or "motores" in target_lower
                        if is_birds:
                            ds_key = "Aves Chilenas"
                        elif is_engine:
                            ds_key = "Motores"
                        else:
                            ds_key = m.clase_objetivo or "Personalizado"
                        arch_key = m.arquitectura or "AudioCNN"
                        pair_counts[(ds_key, arch_key)] += 1
                        v = pair_counts[(ds_key, arch_key)]
                    calculated_versions[m.id_modelo] = v

                for m in modelos:
                    filename = Path(m.ruta_binario_gcp).name if m.ruta_binario_gcp else f"modelo_{m.id_modelo}.pt"
                    target_lower = (m.clase_objetivo or "").lower()

                    is_birds = "aves" in target_lower or "chilenas" in target_lower
                    is_engine = "engine" in target_lower or "motores" in target_lower

                    if is_birds:
                        dataset_display = "Aves Chilenas"
                        classes_list = aves_classes
                    elif is_engine:
                        dataset_display = "Motores"
                        classes_list = engine_classes
                    else:
                        dataset_display = m.clase_objetivo or "Personalizado"
                        classes_list = aves_classes

                    version = calculated_versions.get(m.id_modelo, 1)

                    friendly_name = f"{dataset_display} · {m.arquitectura} (v{version})"

                    lr_val = float(m.tasa_aprendizaje) if m.tasa_aprendizaje is not None else 0.001
                    batch_val = int(m.tamano_lote) if m.tamano_lote is not None else 16
                    hyperparameters = {
                        "learning_rate": lr_val,
                        "batch_size": batch_val,
                        "optimizer": "AdamW",
                        "loss_type": "Focal Loss",
                    }

                    audio_specs = {
                        "target_sr": 22050 if is_birds else 32000,
                        "duration_seconds": 5.0 if is_birds else 1.5,
                        "n_mels": 128,
                        "n_fft": 2048,
                        "hop_length": 512,
                        "fmin": 50,
                        "fmax": 11025 if is_birds else 16000,
                    }

                    file_size = m.tamano_bytes or 0
                    if file_size == 0:
                        candidate_path = self.checkpoints_dir / filename
                        if candidate_path.exists():
                            file_size = candidate_path.stat().st_size
                        else:
                            file_size = 48822960

                    history.append({
                        "id": m.id_modelo,
                        "name": friendly_name,
                        "version": version,
                        "dataset": dataset_display,
                        "dataset_id": m.id_conjunto_datos,
                        "dataset_name": m.conjunto_datos.nombre if m.conjunto_datos else None,
                        "sha256": m.hash_binario,
                        "metrics": [{"epoca": metric.epoca, "precision": metric.precision,
                                     "perdida": metric.perdida, "tiempo_epoca": metric.tiempo_epoca}
                                    for metric in m.metricas],
                        "architecture": m.arquitectura,
                        "epochs": m.epocas,
                        "accuracy": m.precision,
                        "loss": m.perdida,
                        "active": m.activo,
                        "status": m.estado,
                        "filename": filename,
                        "hyperparameters": hyperparameters,
                        "audio_specs": audio_specs,
                        "classes": classes_list,
                        "classes_count": len(classes_list),
                        "file_size_bytes": file_size,
                        "created_at": m.fecha_entrenamiento.isoformat() if m.fecha_entrenamiento else None,
                    })
            except Exception:
                pass

        # Si la base de datos está vacía, mostrar los checkpoints históricos de referencia
        if not history and db is None:
            history = [
                {
                    "id": 1,
                    "name": "Aves Chilenas · Super-Ensamble Tri-Modelo (v1)",
                    "version": 1,
                    "dataset": "Aves Chilenas",
                    "architecture": "Super-Ensamble Tri-Modelo",
                    "epochs": 50,
                    "accuracy": 86.75,
                    "loss": 0.4521,
                    "active": True,
                    "status": "activo",
                    "filename": "super_ensemble_calibrated.pt",
                    "hyperparameters": {
                        "learning_rate": 0.0005,
                        "batch_size": 16,
                        "optimizer": "AdamW",
                        "loss_type": "Focal Loss",
                    },
                    "audio_specs": {
                        "target_sr": 22050,
                        "duration_seconds": 5.0,
                        "n_mels": 128,
                        "n_fft": 2048,
                        "hop_length": 512,
                        "fmin": 50,
                        "fmax": 11025,
                    },
                    "classes": aves_classes,
                    "classes_count": len(aves_classes),
                    "file_size_bytes": 48822960,
                    "created_at": "2026-09-10T14:30:00Z",
                },
                {
                    "id": 2,
                    "name": "Aves Chilenas · EfficientNet-B0 (Pitch Shift) (v2)",
                    "version": 2,
                    "dataset": "Aves Chilenas",
                    "architecture": "EfficientNet-B0 (Pitch Shift)",
                    "epochs": 40,
                    "accuracy": 83.71,
                    "loss": 0.5218,
                    "active": False,
                    "status": "entrenado",
                    "filename": "augmented_best.pt",
                    "hyperparameters": {
                        "learning_rate": 0.001,
                        "batch_size": 32,
                        "optimizer": "AdamW",
                        "loss_type": "Focal Loss",
                    },
                    "audio_specs": {
                        "target_sr": 22050,
                        "duration_seconds": 5.0,
                        "n_mels": 128,
                        "n_fft": 2048,
                        "hop_length": 512,
                        "fmin": 50,
                        "fmax": 11025,
                    },
                    "classes": aves_classes,
                    "classes_count": len(aves_classes),
                    "file_size_bytes": 48822960,
                    "created_at": "2026-09-08T18:15:00Z",
                },
                {
                    "id": 3,
                    "name": "Aves Chilenas · AudioCNN Baseline (v3)",
                    "version": 3,
                    "dataset": "Aves Chilenas",
                    "architecture": "AudioCNN Baseline",
                    "epochs": 15,
                    "accuracy": 55.56,
                    "loss": 1.1250,
                    "active": False,
                    "status": "entrenado",
                    "filename": "baseline_best.pt",
                    "hyperparameters": {
                        "learning_rate": 0.001,
                        "batch_size": 32,
                        "optimizer": "AdamW",
                        "loss_type": "CrossEntropy",
                    },
                    "audio_specs": {
                        "target_sr": 22050,
                        "duration_seconds": 5.0,
                        "n_mels": 128,
                        "n_fft": 2048,
                        "hop_length": 512,
                        "fmin": 50,
                        "fmax": 11025,
                    },
                    "classes": aves_classes,
                    "classes_count": len(aves_classes),
                    "file_size_bytes": 4313077,
                    "created_at": "2026-09-03T10:00:00Z",
                },
            ]

        return history

    def set_active_model(self, model_id: int, db: Optional[Session] = None) -> Dict[str, Any]:
        """
        Marca un modelo como el modelo activo para predicciones en tiempo real (CU_INV_05).
        """
        if db is not None:
            try:
                target = db.query(Modelo).filter_by(id_modelo=model_id).with_for_update().first()
                if target is None:
                    return {"success": False, "error": "Modelo inexistente"}
                self._require_standard_reports(target, db)
                if target:
                    db.query(Modelo).update({Modelo.activo: False})
                    target.activo = True
                    db.commit()

                    # Sincronizar el ModelRegistry global
                    try:
                        from app.services.registry import get_model_registry
                        reg = get_model_registry()
                        reg.register_from_db(db)
                    except Exception as reg_err:
                        print(f"[TrainingService] Advertencia al sincronizar registry: {reg_err}")

                    return {"success": True, "active_model_id": model_id, "architecture": target.arquitectura}

            except Exception as exc:
                db.rollback()
                return {"success": False, "error": str(exc)}

        return {"success": False, "error": "Activación requiere una sesión de persistencia."}


# Instancia singleton del servicio
training_service = TrainingService()
