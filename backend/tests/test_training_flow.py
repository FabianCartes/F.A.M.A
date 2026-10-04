"""Training admission tests at the public service interface; no real training."""
import os
from unittest.mock import patch

import numpy as np
import librosa
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Never load repository credentials while importing application modules.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
from app.database import Base
from app.models.dataset import ConjuntoDatos
from app.models.training import Modelo
from app.services import training


@pytest.fixture
def training_env(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(training, "SessionLocal", sessions)
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: tmp_path / "raw" / (name or ""))
    monkeypatch.setattr(training, "_BACKEND_DIR", tmp_path)
    service = training.TrainingService(tmp_path / "checkpoints")
    # Thread scheduling is an external execution boundary. Never run ML here.
    with patch("app.services.training.threading.Thread") as thread:
        yield service, sessions, tmp_path, thread
    engine.dispose()


def register(sessions, name):
    with sessions() as db:
        dataset = ConjuntoDatos(nombre=name, ruta_gcp=f"datasets/{name}/")
        db.add(dataset)
        db.commit()
        return dataset.id_conjunto_datos


def partitions(root, name):
    raw = root / "raw" / name
    raw.mkdir(parents=True)
    for split in ("train", "val"):
        audio = raw / "fixture" / f"{split}.wav"
        audio.parent.mkdir(exist_ok=True)
        audio.write_bytes(b"tiny audio fixture")
        frame = pd.DataFrame([{"clase": "Fixture", "nombre_archivo": audio.name,
                               "file_path": f"fixture/{split}.wav", "recordist": split}])
        suffix = "_metadata" if name == "engine_diagnostics" else ""
        frame.to_csv(raw / f"{split}{suffix}.csv", index=False)
    return raw


@pytest.mark.parametrize("name", ["medical_cough", "MotoresVehiculares", "aveschilenas", " AvesChilenas", "../AvesChilenas"])
def test_unsupported_identity_is_rejected_before_scheduling(training_env, name):
    service, sessions, _, thread = training_env
    register(sessions, name)
    with pytest.raises(ValueError, match="no soportado"):
        service.start_training(name)
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert progress["job_id"] is None
    assert name in progress["error_message"]
    thread.assert_not_called()


@pytest.mark.parametrize("registrations", [[], ["aveschilenas"], ["AvesChilenas_Train"]])
def test_requires_exact_unambiguous_registration(training_env, registrations):
    service, sessions, root, thread = training_env
    partitions(root, "AvesChilenas")
    for name in registrations:
        register(sessions, name)
    with sessions() as db:
        db.add(Modelo(arquitectura="existing", clase_objetivo="Historical", ruta_binario_gcp="existing.pt",
                      epocas=1, tasa_aprendizaje=0.001, tamano_lote=1))
        db.commit()
        before = service.get_history(db)
        with pytest.raises(ValueError, match="registro"):
            service.start_training("AvesChilenas")
        assert service.get_history(db) == before
    assert service.get_progress()["status"] == "failed"
    assert service.get_progress()["job_id"] is None
    thread.assert_not_called()


@pytest.mark.parametrize("name", ["AvesChilenas", "engine_diagnostics"])
@pytest.mark.parametrize("defect", ["missing_source", "missing_partition", "empty", "schema", "unknown_label", "missing_audio", "outside_source", "overlap"])
def test_invalid_source_is_rejected_before_scheduling(training_env, name, defect):
    service, sessions, root, thread = training_env
    register(sessions, name)
    if defect != "missing_source":
        raw = partitions(root, name)
        suffix = "_metadata" if name == "engine_diagnostics" else ""
        val_csv = raw / f"val{suffix}.csv"
        frame = pd.read_csv(val_csv)
        if defect == "missing_partition":
            # Rename within the temporary fixture, never delete repository files.
            val_csv.rename(raw / "unavailable.csv")
        elif defect == "empty":
            frame.iloc[:0].to_csv(val_csv, index=False)
        elif defect == "schema":
            frame.drop(columns="clase").to_csv(val_csv, index=False)
        elif defect == "unknown_label":
            frame.assign(clase="Unknown").to_csv(val_csv, index=False)
        elif defect == "missing_audio":
            frame.assign(file_path="fixture/missing.wav", nombre_archivo="missing.wav").to_csv(val_csv, index=False)
        elif defect == "outside_source":
            other = root / "outside.wav"
            other.write_bytes(b"not this dataset")
            frame.assign(file_path=str(other), nombre_archivo=str(other)).to_csv(val_csv, index=False)
        elif defect == "overlap":
            frame.assign(file_path="fixture/train.wav", nombre_archivo="train.wav").to_csv(val_csv, index=False)
    with pytest.raises(ValueError):
        service.start_training(name)
    assert service.get_progress()["status"] == "failed"
    assert service.get_progress()["error_message"]
    thread.assert_not_called()
    assert list(service.checkpoints_dir.iterdir()) == []


@pytest.mark.parametrize("name", ["AvesChilenas", "engine_diagnostics"])
@pytest.mark.parametrize("audio_config", [None, {"target_sr": 16000}])
def test_accepted_source_reaches_ml_boundary_without_training(training_env, monkeypatch, name, audio_config):
    service, sessions, root, thread = training_env
    dataset_id = register(sessions, name)
    raw = partitions(root, name)
    # Both sources exist: choosing another dataset must never be a fallback.
    other_name = "engine_diagnostics" if name == "AvesChilenas" else "AvesChilenas"
    partitions(root, other_name)
    observed = []

    def decode_fixture(path, sr, **kwargs):
        observed.append(str(path))
        return np.zeros(8, dtype=np.float32), sr

    def disabled_loader(dataset, **kwargs):
        dataset[0]  # Observe the path actually requested at the audio I/O boundary.
        raise RuntimeError("ML execution disabled at DataLoader boundary")

    monkeypatch.setattr(librosa, "load", decode_fixture)
    monkeypatch.setattr("random.random", lambda: 1.0)
    monkeypatch.setattr(training, "DataLoader", disabled_loader)
    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            assert service.get_progress()["status"] == "training"
            assert self.args[0]["dataset_id"] == dataset_id
            # Change the filesystem after acceptance, before scheduled execution.
            suffix = "_metadata" if name == "engine_diagnostics" else ""
            (raw / f"train{suffix}.csv").write_text("invalid after acceptance\n")
            monkeypatch.setattr(training, "get_raw_data_dir", lambda *a: root / "wrong")
            self.target(*self.args)

    thread.side_effect = InlineThread
    result = service.start_training(name, architecture="AudioCNN", audio_config=audio_config)
    assert result["status"] == "started"
    assert observed == [str(raw / "fixture" / "train.wav")]
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert progress["error_message"] == "ML execution disabled at DataLoader boundary"
    assert list(service.checkpoints_dir.iterdir()) == []


def test_training_catalog_only_offers_supported_registered_datasets(training_env):
    service, sessions, root, _ = training_env
    register(sessions, "medical_cough")
    supported_id = register(sessions, "engine_diagnostics")
    partitions(root, "engine_diagnostics")
    with sessions() as db:
        catalog = service.get_available_datasets(db)
    assert [entry["id"] for entry in catalog] == ["engine_diagnostics"]
    assert catalog[0]["db_id"] == supported_id
    assert service.get_available_datasets() == []


@pytest.mark.parametrize("metadata_only", [False, True])
def test_bird_legacy_metadata_is_validated_before_acceptance(training_env, metadata_only):
    service, sessions, root, thread = training_env
    register(sessions, "AvesChilenas")
    raw = partitions(root, "AvesChilenas")
    if metadata_only:
        rows = []
        for i in range(10):
            (raw / "fixture" / f"{i}.wav").write_bytes(b"fixture")
            rows.append({"clase": "Fixture", "nombre_archivo": f"{i}.wav", "recordist": f"r{i}"})
        pd.DataFrame(rows).to_csv(raw / "metadata.csv", index=False)
        for split in ("train", "val"):
            (raw / f"{split}.csv").rename(raw / f"{split}.unused")
    else:
        for split in ("train", "val"):
            csv = raw / f"{split}.csv"
            pd.read_csv(csv).drop(columns="file_path").to_csv(csv, index=False)
    assert service.start_training("AvesChilenas")["status"] == "started"
    assert service.get_progress()["status"] == "training"
    assert list(service.checkpoints_dir.iterdir()) == []


def test_unavailable_registration_store_fails_closed(training_env, monkeypatch):
    service, _, _, thread = training_env
    def unavailable():
        raise RuntimeError("Registration store unavailable")
    monkeypatch.setattr(training, "SessionLocal", unavailable)
    with pytest.raises(ValueError, match="Registration store unavailable"):
        service.start_training("AvesChilenas")
    assert service.get_progress()["status"] == "failed"
    thread.assert_not_called()
