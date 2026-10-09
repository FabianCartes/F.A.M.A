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
from training import paths
from training.prepare_data import prepare_dataset


@pytest.fixture
def training_env(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(training, "SessionLocal", sessions)
    monkeypatch.setattr(training, "get_raw_data_dir", lambda name=None: tmp_path / "raw" / (name or ""))
    monkeypatch.setattr(paths, "get_raw_data_dir", lambda name=None: tmp_path / "raw" / (name or ""))
    monkeypatch.setattr(paths, "get_processed_data_dir", lambda name=None: tmp_path / "processed" / (name or ""))
    monkeypatch.setattr(training, "get_prepared_data_dir", lambda name: tmp_path / "prepared" / name)
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


def partitions(root, name, stage="raw", extension=".wav", classes=("Fixture",)):
    raw = root / "raw" / name
    raw.mkdir(parents=True)
    audio_root = raw if stage == "raw" else root / "processed" / name / "processed_wav"
    rows = []
    for split in ("train", "val", "test"):
      for class_index, clase in enumerate(classes):
        folder = "fixture" if class_index == 0 else "other"
        audio = audio_root / folder / f"{split}{extension}"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"tiny audio fixture")
        frame = pd.DataFrame([{"clase": clase, "nombre_archivo": audio.name,
                               "file_path": f"{folder}/{split}{extension}", "file_stage": stage,
                               "recordist": split, "source_group": f"group-{split}",
                               "hash_sha256": "0" * 64, "xc_id": f"00{class_index}{split}", "feedback_id": "0006",
                               "labels": '["Fixture"]'}])
        suffix = "_metadata" if name == "engine_diagnostics" else ""
        rows.extend(frame.to_dict("records"))
    index = raw / "metadata.csv"
    pd.DataFrame(rows).to_csv(index, index=False)
    prepared = root / "prepared" / name
    prepared.parent.mkdir(exist_ok=True)
    prepare_dataset(index, roots=paths.get_dataset_roots(name), dataset_name=name,
                    output_dir=prepared, train_ratio=1/3, val_ratio=1/3, test_ratio=1/3)
    # Raw legacy copies remain decoys, never the admission authority.
    for csv in prepared.glob("*.csv"):
        (raw / csv.name).write_bytes(csv.read_bytes())
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
@pytest.mark.parametrize("defect", ["missing_source", "missing_partition", "empty", "schema", "unknown_label",
                                  "missing_audio", "outside_source", "overlap", "missing_stage", "unknown_stage",
                                  "blank_stage", "wrong_stage", "missing_path", "blank_path", "traversal", "alias",
                                  "legacy_alias", "unsupported_extension", "empty_audio"])
def test_invalid_source_is_rejected_before_scheduling(training_env, name, defect):
    service, sessions, root, thread = training_env
    register(sessions, name)
    if defect != "missing_source":
        raw = partitions(root, name)
        suffix = "_metadata" if name == "engine_diagnostics" else ""
        val_csv = root / "prepared" / name / f"val{suffix}.csv"
        frame = pd.read_csv(val_csv)
        if defect == "missing_partition":
            # Rename within the temporary fixture, never delete repository files.
            val_csv.rename(val_csv.with_name("unavailable.csv"))
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
        elif defect in {"missing_stage", "missing_path"}:
            frame.drop(columns="file_stage" if defect == "missing_stage" else "file_path").to_csv(val_csv, index=False)
        elif defect in {"unknown_stage", "blank_stage", "wrong_stage"}:
            stage = {"unknown_stage": "derived", "blank_stage": "", "wrong_stage": "processed"}[defect]
            frame.assign(file_stage=stage).to_csv(val_csv, index=False)
        elif defect in {"blank_path", "traversal"}:
            frame.assign(file_path="" if defect == "blank_path" else "fixture/../fixture/val.wav").to_csv(val_csv, index=False)
        elif defect == "alias":
            (raw / "alias").symlink_to(raw / "fixture", target_is_directory=True)
            frame.assign(file_path="alias/val.wav").to_csv(val_csv, index=False)
        elif defect == "legacy_alias":
            processed = root / "processed" / name / "processed_wav"
            processed.mkdir(parents=True)
            (processed / "val.wav").write_bytes(b"derived audio")
            (raw / "processed_wav").symlink_to(processed, target_is_directory=True)
            frame.assign(file_path="processed_wav/val.wav").to_csv(val_csv, index=False)
        elif defect == "unsupported_extension":
            (raw / "fixture" / "val.txt").write_bytes(b"not supported")
            frame.assign(file_path="fixture/val.txt").to_csv(val_csv, index=False)
        elif defect == "empty_audio":
            (raw / frame.iloc[0]["file_path"]).write_bytes(b"")
    with pytest.raises(ValueError):
        service.start_training(name)
    assert service.get_progress()["status"] == "failed"
    assert service.get_progress()["error_message"]
    thread.assert_not_called()
    assert list(service.checkpoints_dir.iterdir()) == []


@pytest.mark.parametrize("name", ["AvesChilenas", "engine_diagnostics"])
@pytest.mark.parametrize("audio_config", [None, {"target_sr": 16000}])
@pytest.mark.parametrize("stage,extension", [("raw", ".wav"), ("raw", ".mp3"), ("processed", ".wav")])
def test_accepted_source_reaches_ml_boundary_without_training(training_env, monkeypatch, name, audio_config,
                                                              stage, extension):
    service, sessions, root, thread = training_env
    dataset_id = register(sessions, name)
    raw = partitions(root, name, stage, extension)
    audio_root = raw if stage == "raw" else root / "processed" / name / "processed_wav"
    suffix = "_metadata" if name == "engine_diagnostics" else ""
    prepared = root / "prepared" / name
    expected = {split: pd.read_csv(prepared / f"{split}{suffix}.csv", dtype=str,
                                   keep_default_na=False) for split in ("train", "val", "test")}
    before = {csv: csv.read_bytes() for csv in prepared.iterdir()}
    alternate = root / "processed" / name / "processed_wav" if stage == "raw" else raw
    for split in ("train", "val"):
        decoy = alternate / "fixture" / f"{split}{extension}"
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_bytes(b"not the declared stage")
    # Both sources exist: choosing another dataset must never be a fallback.
    other_name = "engine_diagnostics" if name == "AvesChilenas" else "AvesChilenas"
    partitions(root, other_name)
    observed = []

    def decode_fixture(path, sr, **kwargs):
        observed.append(str(path))
        return np.zeros(8, dtype=np.float32), sr

    def disabled_loader(dataset, **kwargs):
        # Persist the admitted index exactly as an ordinary consumer would.
        snapshot = root / ("train-snapshot.csv" if kwargs["shuffle"] else "val-snapshot.csv")
        dataset.df.to_csv(snapshot, index=False)
        dataset[0]  # Observe actual codec input, without executing ML.
        if not kwargs["shuffle"]:
            raise RuntimeError("ML execution disabled at DataLoader boundary")
        return []

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
            source = self.args[0]["source"]
            for split in expected:
                pd.testing.assert_frame_equal(source[f"{split}_df"], expected[split])
            frozen = {split: source[f"{split}_df"] for split in expected}
            (raw / f"train{suffix}.csv").write_text("invalid after acceptance\n")
            monkeypatch.setattr(training, "get_raw_data_dir", lambda *a: root / "wrong")
            with patch.object(pd, "read_csv", side_effect=AssertionError("CSV read after admission")):
                self.target(*self.args)
            for split, frame in frozen.items():
                assert source[f"{split}_df"] is frame
                pd.testing.assert_frame_equal(frame, expected[split])
            assert {csv: csv.read_bytes() for csv in prepared.iterdir()} == before

    thread.side_effect = InlineThread
    result = service.start_training(name, architecture="AudioCNN", audio_config=audio_config)
    assert result["status"] == "started"
    assert observed == [str(audio_root / expected[split].iloc[0]["file_path"])
                        for split in ("train", "val")], service.get_progress()["error_message"]
    for split in ("train", "val"):
        snapshot = pd.read_csv(root / f"{split}-snapshot.csv", dtype=str, keep_default_na=False)
        pd.testing.assert_frame_equal(snapshot, expected[split])
        # The persisted index remains usable on a different physical host root.
        portable_root = root / "relocated" / split
        portable_audio = portable_root / snapshot.iloc[0]["file_path"]
        portable_audio.parent.mkdir(parents=True)
        portable_audio.write_bytes(b"portable fixture")
        portable = training.GenericAudioDataset(snapshot, training.AudioConfig(), {"Fixture": 0},
                                                roots={stage: portable_root})
        _, label = portable[0]
        assert label.item() == 0
        assert observed[-1] == str(portable_audio)
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
def test_bird_legacy_metadata_requires_offline_conversion(training_env, metadata_only):
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
    (root / "prepared/AvesChilenas/.complete").write_text("malformed")
    with pytest.raises(ValueError, match="preparación"):
        service.start_training("AvesChilenas")
    assert service.get_progress()["status"] == "failed"
    thread.assert_not_called()
    assert list(service.checkpoints_dir.iterdir()) == []


def test_canonical_metadata_only_source_preserves_rows_without_rewriting_indices(training_env):
    service, sessions, root, _ = training_env
    register(sessions, "AvesChilenas")
    raw = partitions(root, "AvesChilenas")
    rows = []
    for i in range(10):
        (raw / "fixture" / f"{i}.wav").write_bytes(b"fixture")
        rows.append({"clase": "Fixture", "file_path": f"fixture/{i}.wav", "file_stage": "raw",
                     "recordist": f"r{i}", "source_group": f"group-{i}", "xc_id": f"00{i}"})
    metadata_csv = raw / "metadata.csv"
    pd.DataFrame(rows).to_csv(metadata_csv, index=False)
    before = metadata_csv.read_bytes()
    for split in ("train", "val"):
        (raw / f"{split}.csv").rename(raw / f"{split}.unused")
    (root / "prepared/AvesChilenas").rename(root / "prepared/unused")
    with pytest.raises(ValueError, match="preparación"):
        service.start_training("AvesChilenas")
    assert service.get_progress()["status"] == "failed"
    assert metadata_csv.read_bytes() == before
    assert not (raw / "train.csv").exists()
    assert not (raw / "val.csv").exists()


@pytest.mark.parametrize("stage", ["raw", "processed"])
def test_selected_dataset_root_alias_fails_before_scheduling(training_env, stage):
    service, sessions, root, thread = training_env
    name = "AvesChilenas"
    register(sessions, name)
    raw = partitions(root, name, stage)
    selected = raw if stage == "raw" else root / "processed" / name / "processed_wav"
    physical = selected.with_name("physical")
    selected.rename(physical)
    selected.symlink_to(physical, target_is_directory=True)
    with pytest.raises(ValueError):
        service.start_training(name)
    assert service.get_progress()["status"] == "failed"
    thread.assert_not_called()
    assert list(service.checkpoints_dir.iterdir()) == []


def test_identical_relative_paths_in_distinct_stages_are_not_split_overlap(training_env):
    service, sessions, root, _ = training_env
    name = "AvesChilenas"
    register(sessions, name)
    raw = partitions(root, name)
    processed = root / "processed" / name / "processed_wav" / "fixture"
    processed.mkdir(parents=True)
    (processed / "train.wav").write_bytes(b"processed validation fixture")
    frame = pd.read_csv(raw / "val.csv", dtype=str, keep_default_na=False)
    frame.assign(file_path="fixture/train.wav", file_stage="processed").to_csv(raw / "val.csv", index=False)
    assert service.start_training(name)["status"] == "started"
    assert service.get_progress()["status"] == "training"


@pytest.mark.parametrize("name", ["AvesChilenas", "engine_diagnostics"])
@pytest.mark.parametrize("stage", ["raw", "processed"])
@pytest.mark.parametrize("defect", ["missing_prepared", "integrity", "test_audio"])
def test_prepared_trio_is_required_before_job_admission(training_env, name, stage, defect):
    service, sessions, root, thread = training_env
    register(sessions, name)
    raw = partitions(root, name, stage)
    prepared = root / "prepared" / name
    suffix = "_metadata" if name == "engine_diagnostics" else ""
    legacy_before = {csv: csv.read_bytes() for csv in raw.glob("*.csv")}
    if defect == "missing_prepared":
        prepared.rename(prepared.with_name("unavailable"))
    elif defect == "integrity":
        csv = prepared / f"test{suffix}.csv"
        frame = pd.read_csv(csv, dtype=str, keep_default_na=False)
        frame.assign(feedback_id="changed").to_csv(csv, index=False)
    else:
        frame = pd.read_csv(prepared / f"test{suffix}.csv")
        audio_root = paths.get_dataset_roots(name)[stage]
        (audio_root / frame.iloc[0]["file_path"]).write_bytes(b"")
    with pytest.raises(ValueError):
        service.start_training(name)
    progress = service.get_progress()
    assert progress["status"] == "failed"
    assert progress["job_id"] is None
    thread.assert_not_called()
    assert {csv: csv.read_bytes() for csv in raw.glob("*.csv")} == legacy_before
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
