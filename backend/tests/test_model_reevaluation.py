"""Explicit synthetic reevaluation through its public operation and CLI."""
import csv
from functools import wraps
import os
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import wave

import numpy as np
import pytest
import torch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from torch import nn

from app.database import Base
from app.models.dataset import ConjuntoDatos
from app.models.training import ModelEvaluation, Modelo


class TinyModel(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        self.logits = nn.Parameter(torch.tensor([4.0, -4.0][:num_classes]))

    def load_state_dict(self, state_dict, strict=True):
        assert strict
        self.logits.data.copy_(state_dict["logits"])

    def forward(self, inputs):
        return self.logits.unsqueeze(0).expand(inputs.shape[0], -1)


def wav(path, frequency):
    sample_rate = 22050
    samples = (0.25 * np.sin(2 * np.pi * frequency * np.arange(sample_rate) / sample_rate) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())


@pytest.fixture
def reevaluation_case(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'models.sqlite'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    dataset = ConjuntoDatos(nombre="engine_diagnostics", ruta_gcp="datasets/engine_diagnostics/")
    session.add(dataset)
    session.flush()
    checkpoint_root = tmp_path / "checkpoints"
    checkpoint_root.mkdir()
    checkpoint_path = checkpoint_root / "current.pt"
    torch.save({
        "dataset_id": dataset.id_conjunto_datos,
        "dataset_name": dataset.nombre,
        "job_id": "synthetic-job",
        "architecture": "AudioCNN",
        "classes": ["a", "b"],
        "audio_config": None,
        "windowing_config": None,
        "state_dict": {"logits": torch.tensor([4.0, -4.0])},
    }, checkpoint_path)
    checkpoint_hash = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    model = Modelo(id_modelo=81, conjunto_datos=dataset, arquitectura="AudioCNN",
                   epocas=1, tasa_aprendizaje=0.001, tamano_lote=1,
                   precision=0.375, perdida=1.25, ruta_binario_gcp="models/current.pt",
                   tamano_bytes=checkpoint_path.stat().st_size, hash_binario=checkpoint_hash,
                   activo=True, estado="standard_eval_failed")
    session.add(model)
    session.commit()

    roots = {"raw": tmp_path / "raw", "processed": tmp_path / "processed"}
    for root in roots.values():
        root.mkdir()
    for split, suffix in zip(("train", "val", "test"), ("train", "val", "test")):
        rows = []
        for index, label in enumerate(("a", "b")):
            filename = f"{suffix}-{label}.wav"
            wav(roots["raw"] / filename, 180 + 70 * index)
            rows.append({"file_path": filename, "file_stage": "raw", "recordist": f"{suffix}-{label}",
                         "clase": label, "source_id": f"{suffix}-{label}"})
        prepared = tmp_path / "prepared"
        prepared.mkdir(exist_ok=True)
        with (prepared / f"{split}_metadata.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    csv_names = [f"{split}_metadata.csv" for split in ("train", "val", "test")]
    (prepared / ".complete").write_text(json.dumps({
        "schema": 1, "dataset": "engine_diagnostics",
        "sha256": {name: hashlib.sha256((prepared / name).read_bytes()).hexdigest() for name in csv_names},
    }), encoding="utf-8")
    yield {"session": session, "engine": engine, "model": model, "checkpoint_root": checkpoint_root,
           "checkpoint_path": checkpoint_path, "checkpoint_hash": checkpoint_hash,
           "prepared": prepared, "roots": roots, "database_url": f"sqlite:///{tmp_path / 'models.sqlite'}"}
    session.close()
    engine.dispose()


def operation_args(case):
    return dict(session=case["session"], model_id=case["model"].id_modelo,
                checkpoint_root=case["checkpoint_root"], checkpoint_path=case["checkpoint_path"],
                expected_sha256=case["checkpoint_hash"], prepared_dir=case["prepared"],
                dataset_name="engine_diagnostics", roots=case["roots"])


def test_cli_and_reevaluation_imports_do_not_initialize_ambient_database_runtime():
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", DATABASE_URL="sqlite://")
    probe = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""
            import sys
            import dotenv
            import sqlalchemy
            calls = []
            def track_dotenv(*args, **kwargs):
                calls.append("dotenv")
            def forbid_engine(*args, **kwargs):
                calls.append("engine")
                raise AssertionError("ambient runtime engine created during CLI/model import")
            dotenv.load_dotenv = track_dotenv
            sqlalchemy.create_engine = forbid_engine

            import scripts.reevaluate_model
            import app.models
            from app.services.reevaluation import reevaluate_model
            import app.database as database
            from app.models.training import Modelo
            assert callable(reevaluate_model)
            assert Modelo.metadata is database.Base.metadata
            assert "engine" not in vars(database)
            assert "SessionLocal" not in vars(database)
            assert calls == []
            assert "app.services.training" not in sys.modules
            assert "app.services.registry" not in sys.modules
        """)],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert probe.returncode == 0, probe.stderr


def test_preflight_is_read_only_and_does_not_load_predictor(reevaluation_case, monkeypatch):
    from app.services.reevaluation import ReevaluationError, reevaluate_model
    from app.services.predictors.trained_predictor import TrainedModelPredictor

    def forbidden(*args, **kwargs):
        pytest.fail("Preflight must not instantiate a predictor")
    monkeypatch.setattr(TrainedModelPredictor, "__init__", forbidden)
    case = reevaluation_case
    args = operation_args(case)
    case["model"].precision = 0.9
    with pytest.raises(ReevaluationError, match="pending"):
        reevaluate_model(**args)
    case["session"].rollback()
    case["session"].refresh(case["model"])
    before = (case["model"].activo, case["model"].precision, case["model"].perdida,
              case["model"].estado, case["session"].query(Modelo).count())
    result = reevaluate_model(**operation_args(case))
    assert result["mode"] == "preflight"
    assert result["model_id"] == case["model"].id_modelo
    assert {split: info["sample_count"] for split, info in result["splits"].items()} == {"val": 2, "test": 2}
    assert case["session"].query(ModelEvaluation).count() == 0
    assert (case["model"].activo, case["model"].precision, case["model"].perdida,
            case["model"].estado, case["session"].query(Modelo).count()) == before


def test_execute_appends_val_test_with_shared_pair_and_preserves_model_state(reevaluation_case, monkeypatch):
    from app.services.reevaluation import reevaluate_model
    from app.services.predictors import trained_predictor

    monkeypatch.setattr(trained_predictor, "AudioCNN", lambda num_classes: TinyModel(num_classes))
    case = reevaluation_case
    model = case["model"]
    before = (model.activo, model.precision, model.perdida, model.estado)
    result = reevaluate_model(**operation_args(case), execute=True)
    assert result["mode"] == "execute"
    assert {split: value["status"] for split, value in result["attempts"].items()} == {
        "val": "completed", "test": "completed",
    }
    rows = case["session"].query(ModelEvaluation).order_by(ModelEvaluation.id_evaluation).all()
    assert len(rows) == 2
    assert rows[0].split == "val" and rows[1].split == "test"
    assert rows[0].predictor_config["admitted_val_test_manifest_pair"] == rows[1].predictor_config[
        "admitted_val_test_manifest_pair"]
    assert rows[0].report["sample_count"] == rows[1].report["sample_count"] == 2
    first_reports = [row.report for row in rows]
    retry = reevaluate_model(**operation_args(case), execute=True)
    rows = case["session"].query(ModelEvaluation).order_by(ModelEvaluation.id_evaluation).all()
    assert len(rows) == 4 and len({row.id_evaluation for row in rows}) == 4
    assert [row.status for row in rows] == ["completed"] * 4
    assert [row.report for row in rows[:2]] == first_reports
    assert set(retry["attempts"][split]["id_evaluation"] for split in ("val", "test")) == {
        row.id_evaluation for row in rows[2:]
    }
    assert rows[2].predictor_config["admitted_val_test_manifest_pair"] == rows[3].predictor_config[
        "admitted_val_test_manifest_pair"]
    assert (model.activo, model.precision, model.perdida, model.estado) == before


def test_second_attempt_commit_failure_recovers_and_preserves_completed_history(reevaluation_case, monkeypatch):
    from sqlalchemy import event
    from app.services.reevaluation import ReevaluationError, reevaluate_model
    from app.services.predictors import trained_predictor
    from app.services.predictors.trained_predictor import TrainedModelPredictor

    monkeypatch.setattr(trained_predictor, "AudioCNN", lambda num_classes: TinyModel(num_classes))
    case = reevaluation_case
    reevaluate_model(**operation_args(case), execute=True)
    previous_rows = case["session"].query(ModelEvaluation).order_by(ModelEvaluation.id_evaluation).all()
    previous = [
        (row.id_evaluation, row.split, row.status, row.report, row.error_reason)
        for row in previous_rows
    ]
    previous_ids = {row[0] for row in previous}

    commits = 0
    def fail_second_commit(session):
        nonlocal commits
        commits += 1
        if commits == 2:
            raise RuntimeError("injected one-shot second-attempt commit failure")

    def forbid_prediction(*args, **kwargs):
        pytest.fail("Predictor construction must wait until both attempts exist")

    event.listen(case["session"], "before_commit", fail_second_commit)
    monkeypatch.setattr(TrainedModelPredictor, "__init__", forbid_prediction)
    try:
        with pytest.raises(ReevaluationError, match="attempt creation"):
            reevaluate_model(**operation_args(case), execute=True)
    finally:
        event.remove(case["session"], "before_commit", fail_second_commit)

    rows = case["session"].query(ModelEvaluation).order_by(ModelEvaluation.id_evaluation).all()
    assert commits == 3  # val create, failed test create, durable val failure transition
    assert case["session"].is_active
    assert [
        (row.id_evaluation, row.split, row.status, row.report, row.error_reason)
        for row in rows if row.id_evaluation in previous_ids
    ] == previous
    new_rows = [row for row in rows if row.id_evaluation not in previous_ids]
    assert len(new_rows) == 1
    assert (new_rows[0].split, new_rows[0].status, new_rows[0].report, new_rows[0].error_reason) == (
        "val", "failed", None, "Reevaluation failed during attempt creation."
    )


def test_execution_mutations_fail_attempts_without_rewriting_completed_rows(reevaluation_case, monkeypatch):
    from app.services.reevaluation import ReevaluationError, reevaluate_model
    from app.services.predictors import trained_predictor

    monkeypatch.setattr(trained_predictor, "AudioCNN", lambda num_classes: TinyModel(num_classes))
    original = trained_predictor.TrainedModelPredictor.predict
    fired = False
    def mutate(predictor, path):
        nonlocal fired
        result = original(predictor, path)
        if path.name.startswith("test-") and not fired:
            fired = True
            path.write_bytes(b"mutated audio")
        return result
    monkeypatch.setattr(trained_predictor.TrainedModelPredictor, "predict", mutate)
    with pytest.raises(ReevaluationError, match="test inference"):
        reevaluate_model(**operation_args(reevaluation_case), execute=True)
    rows = reevaluation_case["session"].query(ModelEvaluation).order_by(ModelEvaluation.id_evaluation).all()
    assert [row.status for row in rows] == ["completed", "failed"]
    assert rows[0].report is not None and rows[1].report is None
    assert rows[1].error_reason == "Reevaluation failed during test inference."


def test_preflight_rejects_audio_change_during_decode_without_attempts(reevaluation_case, monkeypatch):
    from app.services.reevaluation import ReevaluationError, reevaluate_model
    from app.services import recording_evaluator

    original = recording_evaluator.librosa.load
    audio = reevaluation_case["roots"]["raw"] / "val-a.wav"
    @wraps(original)
    def mutate_after_decode(path, **kwargs):
        decoded = original(path, **kwargs)
        if Path(path) == audio:
            audio.write_bytes(b"changed during decoding")
        return decoded
    monkeypatch.setattr(recording_evaluator.librosa, "load", mutate_after_decode)
    with pytest.raises(ReevaluationError, match="audio admission"):
        reevaluate_model(**operation_args(reevaluation_case))
    assert reevaluation_case["session"].query(ModelEvaluation).count() == 0


def test_preflight_rejects_checkpoint_hash_change_and_leaking_groups(reevaluation_case):
    from app.services.reevaluation import ReevaluationError, reevaluate_model

    case = reevaluation_case
    case["checkpoint_path"].write_bytes(case["checkpoint_path"].read_bytes() + b"changed")
    with pytest.raises(ReevaluationError, match="integrity"):
        reevaluate_model(**operation_args(case))
    assert case["session"].query(ModelEvaluation).count() == 0


@pytest.mark.parametrize("mutation", ["load", "inference"])
def test_checkpoint_replacement_during_execution_fails_all_unfinished_attempts(reevaluation_case, monkeypatch, mutation):
    from app.services.reevaluation import ReevaluationError, reevaluate_model
    from app.services.predictors import trained_predictor

    monkeypatch.setattr(trained_predictor, "AudioCNN", lambda num_classes: TinyModel(num_classes))
    name = "_load_model" if mutation == "load" else "predict"
    original = getattr(trained_predictor.TrainedModelPredictor, name)
    fired = False
    def replace(predictor, *args, **kwargs):
        nonlocal fired
        result = original(predictor, *args, **kwargs)
        if not fired:
            fired = True
            reevaluation_case["checkpoint_path"].write_bytes(b"replaced during execution")
        return result
    monkeypatch.setattr(trained_predictor.TrainedModelPredictor, name, replace)
    with pytest.raises(ReevaluationError):
        reevaluate_model(**operation_args(reevaluation_case), execute=True)
    rows = reevaluation_case["session"].query(ModelEvaluation).all()
    assert [row.status for row in rows] == ["failed", "failed"]
    assert all(row.report is None and row.error_reason for row in rows)


def test_preflight_rejects_path_escape_and_split_overlap(reevaluation_case):
    from app.services.reevaluation import ReevaluationError, reevaluate_model

    case = reevaluation_case
    test_csv = case["prepared"] / "test_metadata.csv"
    with test_csv.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    rows[0]["file_path"] = "../outside.wav"
    with test_csv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    marker = case["prepared"] / ".complete"
    record = json.loads(marker.read_text(encoding="utf-8"))
    record["sha256"][test_csv.name] = hashlib.sha256(test_csv.read_bytes()).hexdigest()
    marker.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ReevaluationError):
        reevaluate_model(**operation_args(case))
    rows[0]["file_path"] = "test-a.wav"
    rows[0]["recordist"] = "train-a"
    with test_csv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    record["sha256"][test_csv.name] = hashlib.sha256(test_csv.read_bytes()).hexdigest()
    marker.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ReevaluationError):
        reevaluate_model(**operation_args(case))
    assert case["session"].query(ModelEvaluation).count() == 0


def _replace_checkpoint(case, **changes):
    payload = torch.load(case["checkpoint_path"], map_location="cpu", weights_only=True)
    payload.update(changes)
    torch.save(payload, case["checkpoint_path"])
    digest = hashlib.sha256(case["checkpoint_path"].read_bytes()).hexdigest()
    case["checkpoint_hash"] = digest
    case["model"].hash_binario = digest
    case["model"].tamano_bytes = case["checkpoint_path"].stat().st_size
    case["session"].commit()


def test_preflight_rejects_unknown_classes_and_missing_legacy_dataset_metadata(reevaluation_case):
    from app.services.reevaluation import ReevaluationError, reevaluate_model

    case = reevaluation_case
    _replace_checkpoint(case, classes=["a", "not-in-prepared-source"])
    with pytest.raises(ReevaluationError, match="classes"):
        reevaluate_model(**operation_args(case))
    _replace_checkpoint(case, classes=["a", "b"], dataset_name="unknown")
    with pytest.raises(ReevaluationError):
        reevaluate_model(**operation_args(case))
    assert case["session"].query(ModelEvaluation).count() == 0


def test_cli_defaults_to_preflight_and_requires_execute_for_attempts(reevaluation_case, monkeypatch, capsys):
    from app import database
    from app.services.predictors import trained_predictor
    from scripts.reevaluate_model import main

    missing = object()
    ambient_engine_before = vars(database).get("engine", missing)

    def forbid_dotenv(*args, **kwargs):
        pytest.fail("Explicit CLI engine must not initialize ambient app.database configuration")

    def forbid_ambient_engine(*args, **kwargs):
        pytest.fail("Explicit CLI must not request app.database's ambient engine")

    monkeypatch.setattr(database, "load_dotenv", forbid_dotenv)
    monkeypatch.setattr(database, "_runtime_engine", forbid_ambient_engine)
    monkeypatch.setattr(trained_predictor, "AudioCNN", lambda num_classes: TinyModel(num_classes))
    case = reevaluation_case
    args = ["--database-url", case["database_url"], "--model-id", "81",
            "--checkpoint-root", str(case["checkpoint_root"]), "--checkpoint", str(case["checkpoint_path"]),
            "--expected-sha256", case["checkpoint_hash"], "--prepared-dir", str(case["prepared"]),
            "--dataset", "engine_diagnostics", "--root", f"raw={case['roots']['raw']}",
            "--root", f"processed={case['roots']['processed']}"]
    assert main(args) == 0
    preflight = json.loads(capsys.readouterr().out)
    assert preflight["mode"] == "preflight" and case["session"].query(ModelEvaluation).count() == 0
    assert main(args + ["--execute"]) == 0
    execution_output = capsys.readouterr().out
    executed = json.loads(execution_output)
    assert executed["mode"] == "execute"
    assert str(case["checkpoint_path"]) not in execution_output
    assert vars(database).get("engine", missing) is ambient_engine_before
    assert case["session"].query(ModelEvaluation).count() == 2


def test_cli_requires_explicit_inputs_before_database_access():
    from scripts.reevaluate_model import main

    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
