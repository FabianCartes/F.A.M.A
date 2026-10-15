"""Public read-only publication preflight with explicit synthetic runtime inputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from urllib.parse import quote
import wave

import pytest

import numpy as np
import torch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.dataset import ConjuntoDatos
from app.models.training import ModelEvaluation, Modelo
from poc.train import AudioCNN


def _write_audio(path, *, silence=False, noise=False):
    sample_rate = 22050
    if silence:
        samples = np.zeros(sample_rate, dtype=np.float32)
    elif noise:
        samples = np.random.default_rng(42).uniform(-0.25, 0.25, sample_rate).astype(np.float32)
    else:
        samples = 0.25 * np.sin(2 * np.pi * 330 * np.arange(sample_rate) / sample_rate)
    pcm = (samples * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def _publication_case(tmp_path):
    database_path = tmp_path / "candidate.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    dataset = ConjuntoDatos(nombre="engine_diagnostics", ruta_gcp="datasets/engine_diagnostics/")
    session.add(dataset)
    session.flush()

    checkpoints_root = tmp_path / "checkpoints"
    checkpoints_root.mkdir()
    checkpoint_path = checkpoints_root / "candidate.pt"
    predictor = AudioCNN(num_classes=2)
    torch.save({
        "architecture": "AudioCNN",
        "classes": ["clase-a", "clase-b"],
        "state_dict": predictor.state_dict(),
    }, checkpoint_path)
    expected_sha256 = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    model = Modelo(
        id_modelo=41,
        conjunto_datos=dataset,
        arquitectura="AudioCNN",
        epocas=1,
        tasa_aprendizaje=0.001,
        tamano_lote=1,
        precision=0.5,
        perdida=1.0,
        ruta_binario_gcp="models/candidate.pt",
        tamano_bytes=checkpoint_path.stat().st_size,
        hash_binario=expected_sha256,
        activo=False,
        estado="entrenado",
    )
    session.add(model)
    session.commit()
    return {
        "database_path": database_path,
        "engine": engine,
        "session": session,
        "model": model,
        "checkpoint_path": checkpoint_path,
        "checkpoints_root": checkpoints_root,
        "expected_sha256": expected_sha256,
        "audio_path": tmp_path / "controlled.wav",
    }


def _run_cli(case, *extra_args):
    script = Path(__file__).resolve().parents[1] / "scripts" / "preflight_publication.py"
    env = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}
    command = [
        sys.executable, str(script),
        "--database-url", f"sqlite:///{case['database_path']}",
        "--checkpoints-root", str(case["checkpoints_root"]),
        "--model-id", "fama_trained_model_41",
        "--expected-sha256", case["expected_sha256"],
        *extra_args,
    ]
    return subprocess.run(command, cwd=script.parents[1], env=env,
                          capture_output=True, text=True, check=False)


def test_cli_emits_bounded_json_and_read_only_result_for_expected_hash_failure(tmp_path):
    case = _publication_case(tmp_path)
    database_before = case["database_path"].read_bytes()
    checkpoint_before = case["checkpoint_path"].read_bytes()
    try:
        success = _run_cli(case)
        assert success.returncode == 0
        assert success.stderr == ""
        success_output = json.loads(success.stdout)
        assert success_output["ok"] is True
        assert success_output["model_id"] == "fama_trained_model_41"
        assert success_output["expected_sha256"] == case["expected_sha256"]
        assert success_output["runtime"] == {"validation": "lazy_metadata", "network_loaded": False}

        failure = _run_cli(case, "--expected-sha256", "0" * 64)
        assert failure.returncode == 1
        assert failure.stderr == ""
        failure_output = json.loads(failure.stdout)
        assert failure_output["ok"] is False
        assert failure_output["code"] == "expected_checkpoint_hash_mismatch"
        for output in (success.stdout, failure.stdout):
            assert str(case["database_path"]) not in output
            assert str(case["checkpoints_root"]) not in output

        assert case["database_path"].read_bytes() == database_before
        assert case["checkpoint_path"].read_bytes() == checkpoint_before
        assert sorted(path.name for path in case["checkpoints_root"].iterdir()) == ["candidate.pt"]
        assert case["model"].activo is False
        assert case["session"].query(Modelo).count() == 1
        assert case["session"].query(ModelEvaluation).count() == 0
    finally:
        case["session"].close()
        case["engine"].dispose()


def test_cli_rejects_missing_sqlite_database_without_creating_it_or_parent_entries(tmp_path):
    case = _publication_case(tmp_path)
    database_parent = tmp_path / "missing-candidate-runtime"
    database_parent.mkdir()
    database_path = database_parent / "not-created.sqlite"
    parent_entries_before = sorted(path.name for path in database_parent.iterdir())
    try:
        completed = _run_cli(case, "--database-url", f"sqlite:///{database_path}")
        assert completed.returncode == 1
        assert completed.stderr == ""
        result = json.loads(completed.stdout)
        assert result["ok"] is False
        assert result["code"] == "database_unavailable"
        assert not database_path.exists()
        assert sorted(path.name for path in database_parent.iterdir()) == parent_entries_before
    finally:
        case["session"].close()
        case["engine"].dispose()


@pytest.mark.parametrize("database_url", ["sqlite://", "sqlite:///:memory:", "not-a-sqlite-url"])
def test_cli_rejects_memory_and_malformed_database_urls_without_writes(tmp_path, database_url):
    case = _publication_case(tmp_path)
    database_parent = tmp_path / "rejected-candidate-runtime"
    database_parent.mkdir()
    database_path = database_parent / "candidate.sqlite"
    parent_entries_before = sorted(path.name for path in database_parent.iterdir())
    try:
        completed = _run_cli(case, "--database-url", database_url)
        assert completed.returncode == 1
        assert completed.stderr == ""
        result = json.loads(completed.stdout)
        assert result["ok"] is False
        assert result["code"] == "database_unavailable"
        assert not database_path.exists()
        assert sorted(path.name for path in database_parent.iterdir()) == parent_entries_before
    finally:
        case["session"].close()
        case["engine"].dispose()


@pytest.mark.parametrize("mode", ["rw", "rwc", "memory"])
def test_cli_rejects_conflicting_sqlite_uri_modes_without_writes(tmp_path, mode):
    case = _publication_case(tmp_path)
    database_parent = tmp_path / "rejected-candidate-runtime"
    database_parent.mkdir()
    database_path = database_parent / "candidate.sqlite"
    database_url = (
        f"sqlite:///file:{quote(str(database_path), safe='/')}?mode={mode}&uri=true"
    )
    parent_entries_before = sorted(path.name for path in database_parent.iterdir())
    try:
        completed = _run_cli(case, "--database-url", database_url)
        assert completed.returncode == 1
        assert completed.stderr == ""
        result = json.loads(completed.stdout)
        assert result["ok"] is False
        assert result["code"] == "database_unavailable"
        assert not database_path.exists()
        assert sorted(path.name for path in database_parent.iterdir()) == parent_entries_before
    finally:
        case["session"].close()
        case["engine"].dispose()


@pytest.mark.parametrize("mode", ["rw", "rwc"])
def test_cli_rejects_writable_sqlite_uri_modes_for_existing_database(tmp_path, mode):
    case = _publication_case(tmp_path)
    database_before = case["database_path"].read_bytes()
    database_url = (
        f"sqlite:///file:{quote(str(case['database_path']), safe='/')}"
        f"?mode={mode}&uri=true"
    )
    try:
        completed = _run_cli(case, "--database-url", database_url)
        assert completed.returncode == 1
        assert completed.stderr == ""
        result = json.loads(completed.stdout)
        assert result["ok"] is False
        assert result["code"] == "database_unavailable"
        assert case["database_path"].read_bytes() == database_before
    finally:
        case["session"].close()
        case["engine"].dispose()


def test_cli_preserves_percent_encoded_sqlite_database_paths(tmp_path):
    case = _publication_case(tmp_path)
    database_path = case["database_path"].with_name("candidate # 100%.sqlite")
    database_path.write_bytes(case["database_path"].read_bytes())
    database_before = database_path.read_bytes()
    database_url = f"sqlite:///{quote(str(database_path), safe='/')}"
    try:
        completed = _run_cli(case, "--database-url", database_url)
        assert completed.returncode == 0
        assert completed.stderr == ""
        result = json.loads(completed.stdout)
        assert result["ok"] is True
        assert result["model_id"] == "fama_trained_model_41"
        assert database_path.read_bytes() == database_before
    finally:
        case["session"].close()
        case["engine"].dispose()


def test_failure_of_an_unrelated_model_does_not_fail_the_required_publication(tmp_path):
    from app.services.publication_preflight import preflight_publication

    case = _publication_case(tmp_path)
    unrelated = Modelo(
        id_modelo=42,
        arquitectura="invalid unrelated fixture",
        epocas=1,
        tasa_aprendizaje=0.001,
        tamano_lote=1,
        ruta_binario_gcp="models/unrelated.pt",
        tamano_bytes=1,
        hash_binario=None,
        activo=False,
        estado="entrenado",
    )
    case["session"].add(unrelated)
    case["session"].commit()
    try:
        result = preflight_publication(
            case["session"],
            model_id="fama_trained_model_41",
            expected_sha256=case["expected_sha256"],
            checkpoints_root=case["checkpoints_root"],
        )
        assert result["ok"] is True
        assert result["model_id"] == "fama_trained_model_41"
        assert case["session"].query(Modelo).count() == 2
        assert unrelated.activo is False
    finally:
        case["session"].close()
        case["engine"].dispose()


@pytest.mark.parametrize(("signal", "expected_status"), [("silence", "silence"), ("noise", "noise")])
def test_smoke_rejects_signals_that_do_not_prove_a_network_forward(tmp_path, signal, expected_status):
    case = _publication_case(tmp_path)
    _write_audio(case["audio_path"], **{signal: True})
    database_before = case["database_path"].read_bytes()
    checkpoint_before = case["checkpoint_path"].read_bytes()
    audio_before = case["audio_path"].read_bytes()
    try:
        completed = _run_cli(case, "--smoke-audio", str(case["audio_path"]))
        assert completed.returncode == 1
        assert completed.stderr == ""
        result = json.loads(completed.stdout)
        assert result["ok"] is False
        assert result["code"] == "smoke_forward_not_proven"
        assert result["smoke"] == {"status": expected_status, "forward_proven": False}
        assert result["runtime"] == {
            "validation": "checkpoint_loaded_no_forward", "network_loaded": True,
        }
        assert str(case["audio_path"]) not in completed.stdout
        assert case["database_path"].read_bytes() == database_before
        assert case["checkpoint_path"].read_bytes() == checkpoint_before
        assert case["audio_path"].read_bytes() == audio_before
        assert sorted(path.name for path in case["checkpoints_root"].iterdir()) == ["candidate.pt"]
        assert case["session"].query(ModelEvaluation).count() == 0
        assert case["model"].activo is False
    finally:
        case["session"].close()
        case["engine"].dispose()


def test_smoke_uses_a_real_checkpoint_forward_on_controlled_audio(tmp_path):
    case = _publication_case(tmp_path)
    _write_audio(case["audio_path"])
    audio_before = case["audio_path"].read_bytes()
    database_before = case["database_path"].read_bytes()
    checkpoint_before = case["checkpoint_path"].read_bytes()
    try:
        completed = _run_cli(case, "--smoke-audio", str(case["audio_path"]))
        assert completed.returncode == 0
        assert completed.stderr == ""
        result = json.loads(completed.stdout)
        assert result["ok"] is True
        assert result["code"] == "smoke_passed"
        assert result["smoke"] == {"status": "classified", "forward_proven": True}
        assert result["runtime"] == {"validation": "network_forward", "network_loaded": True}
        assert str(case["audio_path"]) not in completed.stdout
        assert case["database_path"].read_bytes() == database_before
        assert case["checkpoint_path"].read_bytes() == checkpoint_before
        assert case["audio_path"].read_bytes() == audio_before
        assert sorted(path.name for path in case["checkpoints_root"].iterdir()) == ["candidate.pt"]
        assert case["session"].query(ModelEvaluation).count() == 0
        assert case["model"].activo is False
    finally:
        case["session"].close()
        case["engine"].dispose()


def test_cli_help_and_import_do_not_initialize_ambient_runtime(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "preflight_publication.py"
    env = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}
    help_result = subprocess.run(
        [sys.executable, str(script), "--help"], cwd=script.parents[1], env=env,
        capture_output=True, text=True, check=False,
    )
    assert help_result.returncode == 0
    assert help_result.stderr == ""
    assert "--database-url" in help_result.stdout
    assert "archivo SQLite existente" in help_result.stdout
    assert "--checkpoints-root" in help_result.stdout
    assert "--smoke-audio" in help_result.stdout

    invalid_arguments = subprocess.run(
        [sys.executable, str(script)], cwd=script.parents[1], env=env,
        capture_output=True, text=True, check=False,
    )
    assert invalid_arguments.returncode == 2
    assert invalid_arguments.stderr == ""
    assert json.loads(invalid_arguments.stdout)["code"] == "invalid_arguments"

    probe = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""
            import sys
            import dotenv
            import sqlalchemy
            calls = []
            def forbidden(*args, **kwargs):
                calls.append("runtime")
                raise AssertionError("import must not initialize runtime")
            dotenv.load_dotenv = forbidden
            sqlalchemy.create_engine = forbidden

            import scripts.preflight_publication
            import app.database as database
            assert "engine" not in vars(database)
            assert "SessionLocal" not in vars(database)
            assert database._RUNTIME == {}
            assert "app.main" not in sys.modules
            assert "app.services.training" not in sys.modules
            assert calls == []
        """)],
        cwd=script.parents[1], env=env, capture_output=True, text=True, check=False,
    )
    assert probe.returncode == 0, probe.stderr


def test_standard_model_publication_uses_the_existing_evaluation_guard(tmp_path):
    from app.services.publication_preflight import preflight_publication

    case = _publication_case(tmp_path)
    case["model"].estado = "standard_eval_completed"
    case["session"].commit()
    try:
        result = preflight_publication(
            case["session"],
            model_id="fama_trained_model_41",
            expected_sha256=case["expected_sha256"],
            checkpoints_root=case["checkpoints_root"],
        )
        assert result["ok"] is False
        assert result["code"] == "standard_evaluation_invalid"
        assert "/private/" not in json.dumps(result)
        assert case["session"].query(ModelEvaluation).count() == 0
        assert case["model"].activo is False
    finally:
        case["session"].close()
        case["engine"].dispose()


def test_preflight_publishes_exact_model_and_labels_lazy_metadata_not_loaded_weights(tmp_path):
    from app.services.publication_preflight import preflight_publication

    case = _publication_case(tmp_path)
    try:
        result = preflight_publication(
            case["session"],
            model_id="fama_trained_model_41",
            expected_sha256=case["expected_sha256"],
            checkpoints_root=case["checkpoints_root"],
        )

        assert result == {
            "ok": True,
            "model_id": "fama_trained_model_41",
            "expected_sha256": case["expected_sha256"],
            "code": "published",
            "runtime": {"validation": "lazy_metadata", "network_loaded": False},
        }
        assert case["session"].query(Modelo).count() == 1
        assert case["model"].activo is False
        assert not case["session"].dirty
    finally:
        case["session"].close()
        case["engine"].dispose()
